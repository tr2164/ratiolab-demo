"""
Model Validator: Uses Claude Opus 4.6 via GenAI shared service to analyze
the full financial model workbook and answer questions about data quality,
formula logic, and projection sensibility.
"""
import json
import logging
from typing import Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.model import Model, ModelLineItem, ModelAssumption
from app.models.company import Company
from app.config import get_settings, get_openai_client

logger = logging.getLogger(__name__)
settings = get_settings()

TABS = ["IS", "BS", "SCF", "WC", "PPE", "DEBT", "INFO"]

SYSTEM_PROMPT = """You are a financial model validator — an expert CFA-level analyst reviewing
a 6-tab integrated financial model built from SEC EDGAR data. The model follows
professor-style conventions:

- All IS expense items are positive; EBIT = Sales - SUM(expenses)
- Blue font = editable input, Black = formula, Green = cross-sheet reference
- Working Capital, PP&E, and Debt are supporting schedules that feed the BS and SCF
- The model uses 3 years of historical data and projects forward

You receive the COMPLETE workbook data as JSON organized by tab. Each tab contains
line items with historical and projected values.

When analyzing:
1. Check if projected values make directional sense vs. historical trends
2. Flag any suspiciously large jumps, sign flips, or zero values that should be non-zero
3. Verify cross-tab consistency (e.g., BS Cash should match SCF Ending Cash)
4. Check ratio reasonableness (margins, growth rates, leverage)
5. If the user asks about news or market context, use your knowledge to provide relevant insights

Be specific — reference exact line items, years, and values. Be concise but thorough.
Format your response with clear sections using markdown."""


async def build_workbook_context(model_id: int, db: AsyncSession) -> Optional[Dict]:
    """Build a structured JSON representation of the full workbook."""
    model = await db.get(Model, model_id)
    if not model:
        return None

    company = await db.get(Company, model.company_id)

    result = await db.execute(
        select(ModelLineItem)
        .where(ModelLineItem.model_id == model_id)
        .order_by(ModelLineItem.statement_type, ModelLineItem.sort_order, ModelLineItem.year)
    )
    items = result.scalars().all()

    result = await db.execute(
        select(ModelAssumption).where(ModelAssumption.model_id == model_id)
    )
    assumptions = result.scalars().all()

    tabs: Dict[str, Dict[str, Dict[int, float]]] = {t: {} for t in TABS}
    for item in items:
        tab = item.statement_type
        if tab not in tabs:
            tabs[tab] = {}
        line = item.model_line
        if line not in tabs[tab]:
            tabs[tab][line] = {}
        tabs[tab][line][item.year] = round(item.amount, 2) if item.amount else 0

    assumption_data = {}
    for a in assumptions:
        assumption_data[a.name] = {
            "base_value": round(a.base_value, 6) if a.base_value else 0,
            "step_increment": round(a.step_increment, 6) if a.step_increment else 0,
            "step_type": a.step_type,
        }

    return {
        "company": {
            "ticker": company.ticker if company else "Unknown",
            "name": company.name if company else "Unknown",
        },
        "model_id": model_id,
        "projection_years": model.projection_years,
        "tabs": tabs,
        "assumptions": assumption_data,
    }


async def validate_chat(
    model_id: int,
    message: str,
    history: List[Dict[str, str]],
    db: AsyncSession,
    llm_model: Optional[str] = None,
) -> Dict:
    """Send a validation query with full workbook context. Uses the configured
    validator model by default, but can be overridden via llm_model."""
    workbook = await build_workbook_context(model_id, db)
    if not workbook:
        return {"reply": "Model not found.", "sources": []}

    ticker = workbook["company"]["ticker"]
    company_name = workbook["company"]["name"]

    workbook_json = json.dumps(workbook["tabs"], indent=1, default=str)
    assumptions_json = json.dumps(workbook["assumptions"], indent=1, default=str)

    system = f"""{SYSTEM_PROMPT}

## Company: {company_name} ({ticker})
## Projection Years: {workbook['projection_years']}

## Model Assumptions
{assumptions_json}

## Full Workbook Data (by tab)
{workbook_json}"""

    messages = []
    for h in history[-20:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})

    try:
        use_model = llm_model or settings.validator_llm_model
        client = get_openai_client()
        response = client.chat.completions.create(
            model=use_model,
            messages=[{"role": "system", "content": system}] + messages,
            max_tokens=4096,
            temperature=0.3,
        )
        reply = response.choices[0].message.content
        return {"reply": reply, "sources": []}

    except Exception as e:
        logger.error(f"Validator chat failed: {e}", exc_info=True)
        return {"reply": f"Validator error: {str(e)}", "sources": []}
