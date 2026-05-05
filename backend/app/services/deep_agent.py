"""
FinModel Deep Agent: LangGraph-based agent with Tavily web research.
Adapted from RCSA's deep-agent pattern.

Modes:
  - research: Tavily web search for financial news, earnings, sector analysis
  - forecast: Financial forecasting grounded in spreadsheet context + news signals
  - general: General financial modeling Q&A

The agent can receive spreadsheet cell context from the Univer frontend
to provide analysis grounded in the actual model data.
"""
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI

from app.config import get_settings
from app.services.prompt_service import render_prompt

logger = logging.getLogger(__name__)
settings = get_settings()

RESEARCH_SYSTEM_PROMPT = """You are a financial research agent for FinModel AI. Your job is to:
1. Search for recent financial news, earnings reports, and analyst commentary about the company
2. Evaluate how news signals might affect the financial model drivers (revenue growth, margins, etc.)
3. Provide sourced, actionable intelligence for financial projections

Guidelines:
- Always use web_search to gather real, recent data. Do NOT fabricate sources.
- Focus on: earnings, revenue guidance, margin trends, capex plans, M&A, regulatory changes
- Map news signals to specific model drivers when possible
- Be concise and action-oriented

Output format (Markdown):
### Key Findings
- **[Headline]** — summary. Source: [Source]([URL])

---

### Impact on Model Drivers
- **Revenue Growth:** [signal] — rationale
- **COGS/Margins:** [signal] — rationale
- **CapEx:** [signal] — rationale

---

### Suggested Model Adjustments
- Adjustment 1...
- Adjustment 2...

---

### Follow-up Research Queries
- Query suggestions for deeper analysis
"""

FORECAST_SYSTEM_PROMPT = """You are a financial forecasting analyst for FinModel AI. The user will
provide spreadsheet context (model data, drivers, line items) and ask you to analyze, explain,
or suggest adjustments.

You have access to web_search to check your analysis against current market conditions.

Guidelines:
- Ground your analysis in the data provided
- Use web_search to validate assumptions against real market conditions
- Suggest specific driver adjustments with rationale
- Express uncertainty ranges where appropriate
- Reference specific line items and years from the model

When the user shares model data, analyze it for:
1. Reasonableness of assumptions
2. Key sensitivities
3. Risks to the forecast
4. Opportunities not captured
"""

GENERAL_SYSTEM_PROMPT = """You are a financial modeling expert assistant. Help the user with
questions about 3-statement financial models, valuation, accounting concepts, and modeling
best practices. Use web_search when you need current data or to verify facts.
"""

_agent_cache: Dict[str, Any] = {}


def _get_chat_model() -> ChatOpenAI:
    """Get LLM configured with the genai gateway."""
    api_key = settings.openai_api_key
    api_url = settings.openai_api_url or "https://api.openai.com/v1"
    model_name = settings.default_llm_model or "gpt-4o-mini"

    if not api_key:
        raise ValueError("OPENAI_API_KEY must be set")

    base_url = api_url.rstrip("/")
    if base_url == "https://api.openai.com/v1":
        return ChatOpenAI(model=model_name, api_key=api_key, temperature=0.2)
    return ChatOpenAI(model=model_name, api_key=api_key, base_url=base_url, temperature=0.2)


def _create_web_search_tool() -> StructuredTool:
    """Tavily web search tool (RCSA pattern)."""
    def web_search(query: str, max_results: int = 6) -> str:
        tavily_api_key = settings.tavily_api_key
        if not tavily_api_key:
            return json.dumps({"error": "TAVILY_API_KEY not configured"})
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": tavily_api_key,
                        "query": query,
                        "max_results": max_results,
                        "search_depth": "advanced",
                    },
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
                results = response.json()
            return json.dumps({
                "query": query,
                "count": len(results.get("results", [])),
                "results": [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "content": r.get("content", ""),
                        "published_date": r.get("published_date", ""),
                        "score": r.get("score", 0.0),
                    }
                    for r in results.get("results", [])
                ],
            }, indent=2)
        except Exception as e:
            return json.dumps({"error": f"Tavily search failed: {str(e)}"})

    return StructuredTool.from_function(
        func=web_search,
        name="web_search",
        description="Search the web for financial news, earnings, analyst reports using Tavily.",
    )


def _classify_query(query: str) -> str:
    """Classify user query into analysis mode."""
    q = query.lower()
    research_kw = ["news", "research", "latest", "recent", "earnings", "analyst", "market", "what's happening"]
    forecast_kw = ["forecast", "project", "adjust", "driver", "assumption", "sensitivity", "what if", "scenario"]

    if any(kw in q for kw in research_kw):
        return "research"
    if any(kw in q for kw in forecast_kw):
        return "forecast"
    return "general"


def _extract_urls(text: str) -> List[str]:
    urls = re.findall(r"https?://\S+", text or "")
    cleaned = [url.rstrip(").,]") for url in urls]
    unique = []
    for url in cleaned:
        if url not in unique:
            unique.append(url)
    return unique


async def run_deep_research(
    query: str,
    context: Dict[str, Any],
    model_id: Optional[int] = None,
    session_id: Optional[str] = None,
    spreadsheet_context: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the deep agent for financial analysis.

    Args:
        query: User's question
        context: Additional context (company info, etc.)
        model_id: ID of the financial model being analyzed
        session_id: Chat session ID for thread continuity
        spreadsheet_context: Cell data from Univer sent as reference
    """
    if not settings.tavily_api_key and not settings.openai_api_key:
        return {
            "response": "No API keys configured. Set OPENAI_API_KEY and TAVILY_API_KEY.",
            "sources": [],
            "confidence": 0.0,
            "analysis_type": "error",
        }

    mode = _classify_query(query)
    system_prompt = {
        "research": RESEARCH_SYSTEM_PROMPT,
        "forecast": FORECAST_SYSTEM_PROMPT,
        "general": GENERAL_SYSTEM_PROMPT,
    }[mode]

    model = _get_chat_model()
    tools = []
    if settings.tavily_api_key:
        web_search_tool = _create_web_search_tool()
        tools.append(web_search_tool)
        model = model.bind_tools(tools)

    ticker = context.get("ticker", "")
    company_name = context.get("company_name", "")

    user_content_parts = []
    if ticker or company_name:
        user_content_parts.append(f"Company: {company_name} ({ticker})")
    if spreadsheet_context:
        user_content_parts.append(f"Spreadsheet context:\n{spreadsheet_context}")
    user_content_parts.append(query)
    user_content = "\n\n".join(user_content_parts)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_content),
    ]

    try:
        response = await model.ainvoke(messages)

        if hasattr(response, 'tool_calls') and response.tool_calls:
            from langchain_core.messages import ToolMessage

            tool_results = []
            for tc in response.tool_calls:
                if tc['name'] == 'web_search':
                    result = web_search_tool.invoke(tc['args'])
                    tool_results.append(ToolMessage(content=result, tool_call_id=tc['id']))

            if tool_results:
                messages.append(response)
                messages.extend(tool_results)
                response = await model.ainvoke(messages)

                if hasattr(response, 'tool_calls') and response.tool_calls:
                    more_results = []
                    for tc in response.tool_calls:
                        if tc['name'] == 'web_search':
                            result = web_search_tool.invoke(tc['args'])
                            more_results.append(ToolMessage(content=result, tool_call_id=tc['id']))
                    if more_results:
                        messages.append(response)
                        messages.extend(more_results)
                        response = await model.ainvoke(messages)

        response_text = response.content if hasattr(response, 'content') else str(response)

        return {
            "response": response_text.strip(),
            "sources": _extract_urls(response_text),
            "confidence": 0.85 if mode == "research" else 0.75,
            "analysis_type": mode,
        }

    except Exception as e:
        logger.error(f"Deep agent failed: {e}")
        return {
            "response": f"Analysis failed: {str(e)}",
            "sources": [],
            "confidence": 0.0,
            "analysis_type": "error",
        }
