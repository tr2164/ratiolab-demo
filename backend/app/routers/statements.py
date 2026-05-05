"""
Ratio Lab module API — generic financial statement exploration and custom
ratio computation.
"""

from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException, Query

from app.schemas.statements import (
    LineItemCatalog,
    LineItem,
    CompanyInfo,
    SelectedItemsRequest,
    LineItemDataResponse,
    LineItemData,
    FootnoteRequest,
    FootnoteResponse,
    FootnoteBlock,
    RatioRequest,
    RatioResponse,
    RatioResult,
    RatioDefinition,
    RatioTerm,
    RatioAnalysis,
    Observation,
)
from app.services.statement_data import (
    get_all_line_items,
    get_line_item_data,
    get_related_footnotes,
    compute_custom_ratios,
    get_ratio_templates,
    resolve_template_concepts,
)
from app.services.llm_service import chat_json, chat, _fmt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/statements", tags=["statements"])


@router.get("/{ticker}/line-items", response_model=LineItemCatalog)
def list_line_items(
    ticker: str,
    category: str = Query("", description="Filter by category"),
    q: str = Query("", description="Search by label or concept name"),
):
    """Return a browsable catalog of all line items for this company."""
    try:
        catalog = get_all_line_items(ticker)
    except Exception as e:
        logger.error(f"Failed to fetch line items for {ticker}: {e}")
        raise HTTPException(status_code=404, detail=str(e))

    items = catalog["items"]

    if category:
        items = [i for i in items if i["category"] == category]

    if q:
        q_lower = q.lower()
        items = [
            i for i in items
            if q_lower in i["label"].lower() or q_lower in i["concept"].lower()
        ]

    return LineItemCatalog(
        company=CompanyInfo(**catalog["company"]),
        items=[LineItem(**i) for i in items],
        category_counts=catalog["category_counts"],
    )


@router.post("/{ticker}/data", response_model=LineItemDataResponse)
def fetch_selected_data(ticker: str, body: SelectedItemsRequest):
    """Fetch full historical time series for selected concepts."""
    if not body.concepts:
        raise HTTPException(status_code=400, detail="No concepts provided")
    if len(body.concepts) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 concepts per request")

    try:
        results = get_line_item_data(ticker, body.concepts)
    except Exception as e:
        logger.error(f"Failed to fetch data for {ticker}: {e}")
        raise HTTPException(status_code=404, detail=str(e))

    from app.services.sec_data import get_company_facts
    facts = get_company_facts(ticker)

    return LineItemDataResponse(
        company_name=facts.get("entityName", ticker.upper()),
        ticker=ticker.upper(),
        items=[LineItemData(**r) for r in results],
    )


@router.post("/{ticker}/footnotes", response_model=FootnoteResponse)
def fetch_footnotes(ticker: str, body: FootnoteRequest):
    """Fetch related footnotes for selected concepts from the XBRL filing."""
    if not body.concepts:
        raise HTTPException(status_code=400, detail="No concepts provided")

    try:
        blocks = get_related_footnotes(ticker, body.concepts)
    except Exception as e:
        logger.error(f"Failed to fetch footnotes for {ticker}: {e}")
        raise HTTPException(status_code=404, detail=str(e))

    from app.services.sec_data import get_company_facts
    facts = get_company_facts(ticker)

    return FootnoteResponse(
        company_name=facts.get("entityName", ticker.upper()),
        ticker=ticker.upper(),
        blocks=[FootnoteBlock(**b) for b in blocks],
    )


@router.post("/{ticker}/ratios", response_model=RatioResponse)
def compute_ratios(ticker: str, body: RatioRequest):
    """Compute user-defined ratios over time."""
    if not body.ratios:
        raise HTTPException(status_code=400, detail="No ratios provided")
    if len(body.ratios) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 ratios per request")

    ratio_dicts = [r.model_dump() for r in body.ratios]

    try:
        results = compute_custom_ratios(ticker, ratio_dicts)
    except Exception as e:
        logger.error(f"Failed to compute ratios for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    from app.services.sec_data import get_company_facts
    facts = get_company_facts(ticker)

    return RatioResponse(
        company_name=facts.get("entityName", ticker.upper()),
        ticker=ticker.upper(),
        results=[
            RatioResult(
                name=r["name"],
                definition=RatioDefinition(
                    name=r["definition"]["name"],
                    numerator_terms=[RatioTerm(**t) for t in r["definition"]["numerator_terms"]],
                    denominator_terms=[RatioTerm(**t) for t in r["definition"]["denominator_terms"]],
                    multiply_by=r["definition"].get("multiply_by", 1.0),
                ),
                values=r["values"],
                trend=r.get("trend", ""),
            )
            for r in results
        ],
    )


@router.get("/templates")
def list_templates():
    """Return pre-built ratio templates."""
    templates = get_ratio_templates()
    return {
        "templates": [
            {
                "name": t["name"],
                "category": t["category"],
                "numerator_terms": t["numerator_terms"],
                "denominator_terms": t["denominator_terms"],
                "multiply_by": t["multiply_by"],
            }
            for t in templates
        ],
    }


@router.get("/{ticker}/templates")
def list_templates_for_company(ticker: str):
    """Return templates with availability info for a specific company."""
    templates = get_ratio_templates()
    try:
        resolved = [resolve_template_concepts(ticker, t) for t in templates]
    except Exception as e:
        logger.error(f"Failed to resolve templates for {ticker}: {e}")
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "templates": [
            {
                "name": t["name"],
                "category": t["category"],
                "numerator_terms": t["numerator_terms"],
                "denominator_terms": t["denominator_terms"],
                "multiply_by": t["multiply_by"],
                "available": t["available"],
                "missing_concepts": t.get("missing_concepts", []),
            }
            for t in resolved
        ],
    }


RATIO_ANALYSIS_PROMPT = """\
You are a financial analyst and accounting educator reviewing ratio data pulled \
directly from SEC EDGAR XBRL filings for {company_name} ({ticker}). Analyze the \
ratios and return JSON (no markdown wrapping, no text outside the JSON):

{{
  "ratio_highlights": [
    "3-5 key observations that reference the actual ratio numbers"
  ],
  "observations": [
    {{
      "title": "short title",
      "insight": "what this ratio or trend means for the business",
      "follow_up": "one specific thing an auditor should investigate further based on these numbers"
    }}
  ],
  "summary": "2-3 sentence summary of the company's financial health based on these ratios"
}}

Focus on: what the ratios reveal about liquidity, profitability, leverage, and \
efficiency. Identify any concerning trends or notable strengths. Compare to \
general industry benchmarks where possible. Be specific, reference the actual \
numbers, and avoid generic disclaimers.

Ratio data:
{ratio_data}
"""


@router.get("/{ticker}/analyze", response_model=RatioAnalysis)
def analyze_ratios(
    ticker: str,
    ratios_json: str = Query("", description="JSON-encoded ratio results"),
):
    """Run AI analysis on computed ratios."""
    if not ratios_json:
        raise HTTPException(status_code=400, detail="No ratio data provided")

    import json
    try:
        ratio_data = json.loads(ratios_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    from app.services.sec_data import get_company_facts
    facts = get_company_facts(ticker)
    company_name = facts.get("entityName", ticker.upper())

    ratio_summary_lines = []
    for r in ratio_data:
        name = r.get("name", "Unknown")
        values = r.get("values", {})
        vals_str = ", ".join(f"{yr}: {v}" for yr, v in sorted(values.items()) if v is not None)
        trend = r.get("trend", "")
        ratio_summary_lines.append(f"- {name}: {vals_str} (trend: {trend})")

    ratio_text = "\n".join(ratio_summary_lines)

    prompt = RATIO_ANALYSIS_PROMPT.format(
        company_name=company_name,
        ticker=ticker.upper(),
        ratio_data=ratio_text[:4000],
    )

    try:
        result = chat_json([{"role": "user", "content": prompt}])
        return RatioAnalysis(**result)
    except Exception as e:
        logger.error(f"AI analysis failed for {ticker}: {e}")
        raise HTTPException(status_code=502, detail=f"AI analysis failed: {e}")


RATIO_SYSTEM_CONTEXT = """\
You are an expert accounting professor helping a student understand financial \
ratios. The student is analyzing {company_name} using data from SEC EDGAR.

Ratio context:
{ratio_data}

Help the student interpret what these ratios mean, how they relate to each \
other, and what they reveal about the company's financial position and \
performance. Reference specific ratios and values when relevant. Keep \
answers concise and educational."""


DISCLOSURE_SYSTEM_CONTEXT = """\
You are an expert accounting professor helping a student read and understand \
a financial disclosure from {company_name}'s SEC filing.

The student is currently viewing the following disclosure:

--- DISCLOSURE: {disclosure_name} ---
{disclosure_text}
--- END DISCLOSURE ---

Help the student understand:
- What this disclosure is about and why the company is required to report it
- Key accounting policies, estimates, or judgments described
- What the numbers (if any) mean in practical terms
- Any risks, contingencies, or notable items a careful reader should flag

Use plain language. When you reference specific figures from the disclosure, \
explain what they represent. Keep answers concise and educational."""


@router.post("/{ticker}/chat")
def chat_about_ratios(ticker: str, body: dict):
    """Continue a conversation about ratios or disclosures."""
    messages = body.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    context_type = body.get("context_type", "ratios")
    context_data = body.get("ratio_context", "")

    from app.services.sec_data import get_company_facts
    facts = get_company_facts(ticker)
    company_name = facts.get("entityName", ticker.upper())

    if context_type == "disclosure" and context_data:
        lines = context_data.split("\n", 1)
        disclosure_name = lines[0] if lines else "Financial Disclosure"
        disclosure_text = lines[1] if len(lines) > 1 else context_data
        system_ctx = DISCLOSURE_SYSTEM_CONTEXT.format(
            company_name=company_name,
            disclosure_name=disclosure_name,
            disclosure_text=disclosure_text[:6000],
        )
    else:
        system_ctx = RATIO_SYSTEM_CONTEXT.format(
            company_name=company_name,
            ratio_data=context_data[:3000] if context_data else "No ratios computed yet.",
        )

    try:
        all_messages = [{"role": "system", "content": system_ctx}] + messages
        reply = chat(all_messages, temperature=0.4, max_tokens=1500)
        return {"role": "assistant", "content": reply}
    except Exception as e:
        logger.error(f"Chat failed for {ticker}: {e}")
        raise HTTPException(status_code=502, detail=f"Chat failed: {e}")
