"""
Agent Orchestrator: Chat interface for interacting with the financial model.
Routes queries to the deep agent (for research/forecasting) or direct LLM
(for simple Q&A and driver suggestions).
"""
import json
import logging
import re
from typing import Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.model import Model, ModelLineItem, Driver
from app.models.company import Company
from app.services.prompt_service import render_prompt
from app.services.deep_agent import run_deep_research, _classify_query
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def chat_with_model(
    message: str,
    model_id: int,
    history: List[dict],
    db: AsyncSession,
    spreadsheet_context: Optional[str] = None,
) -> Dict:
    """Process a chat message about the financial model.
    Routes to deep agent for research/forecast queries, direct LLM for quick Q&A.
    """
    model = await db.get(Model, model_id)
    if not model:
        return {"reply": "Model not found.", "suggestions": [], "sources": []}

    company = await db.get(Company, model.company_id)
    ticker = company.ticker if company else ""
    company_name = company.name if company else ""

    result = await db.execute(
        select(Driver).where(Driver.model_id == model_id).order_by(Driver.year)
    )
    drivers = result.scalars().all()
    driver_summary = {}
    for d in drivers:
        driver_summary.setdefault(d.driver_name, {})[d.year] = {
            "value": round(d.value, 4) if d.value else 0,
            "projected": d.is_projected,
        }

    result = await db.execute(
        select(ModelLineItem).where(
            ModelLineItem.model_id == model_id,
            ModelLineItem.model_line.in_(["Revenue", "Net Income", "Free Cash Flow"]),
        ).order_by(ModelLineItem.year)
    )
    key_items = result.scalars().all()
    projections = {}
    for item in key_items:
        projections.setdefault(item.model_line, {})[item.year] = {
            "amount": round(item.amount, 2) if item.amount else 0,
            "projected": item.is_projected,
        }

    query_mode = _classify_query(message)

    if query_mode in ("research", "forecast"):
        deep_result = await run_deep_research(
            query=message,
            context={
                "ticker": ticker,
                "company_name": company_name,
                "model_id": model_id,
                "driver_summary": driver_summary,
                "key_projections": projections,
            },
            model_id=model_id,
            spreadsheet_context=spreadsheet_context,
        )

        suggestions = _extract_suggestions(deep_result.get("response", ""))

        return {
            "reply": deep_result.get("response", ""),
            "suggestions": suggestions,
            "sources": deep_result.get("sources", []),
            "analysis_type": deep_result.get("analysis_type", query_mode),
        }

    rendered = await render_prompt(
        db, "agent_system",
        driver_summary=json.dumps(driver_summary, indent=2),
        projections=json.dumps(projections, indent=2),
    )

    system_prompt = rendered or f"""You are a financial modeling assistant analyzing a 3-statement model
for {company_name} ({ticker}).

Current Model Drivers:
{json.dumps(driver_summary, indent=2)}

Key Projections:
{json.dumps(projections, indent=2)}

You can suggest driver adjustments. When you do, include them in your response as a JSON block
wrapped in <suggestions> tags like:
<suggestions>
[{{"driver": "Revenue Growth", "year": 2026, "current": 0.32, "suggested": 0.38, "reason": "..."}}]
</suggestions>

Be concise, data-driven, and reference specific numbers from the model."""

    if spreadsheet_context:
        system_prompt += f"\n\nThe user is sharing spreadsheet data:\n{spreadsheet_context}"

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history[-10:])
    messages.append({"role": "user", "content": message})

    try:
        from app.config import get_openai_client, get_anthropic_client

        if settings.anthropic_api_key:
            client = get_anthropic_client()
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                system=system_prompt,
                messages=[m for m in messages if m["role"] != "system"],
            )
            reply = response.content[0].text
        elif settings.openai_api_key:
            client = get_openai_client()
            response = client.chat.completions.create(
                model=settings.default_llm_model,
                messages=messages,
                max_tokens=1500,
            )
            reply = response.choices[0].message.content
        else:
            reply = "No AI API key configured. Please set OPENAI_API_KEY or ANTHROPIC_API_KEY."

        suggestions = _extract_suggestions(reply)
        reply = re.sub(r"<suggestions>.*?</suggestions>", "", reply, flags=re.DOTALL).strip()

        return {"reply": reply, "suggestions": suggestions, "sources": []}

    except Exception as e:
        logger.error(f"Agent chat failed: {e}")
        return {"reply": f"Error: {str(e)}", "suggestions": [], "sources": []}


def _extract_suggestions(text: str) -> List[Dict]:
    """Extract <suggestions> JSON from agent response."""
    if "<suggestions>" not in text:
        return []
    match = re.search(r"<suggestions>(.*?)</suggestions>", text, re.DOTALL)
    if not match:
        return []
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
