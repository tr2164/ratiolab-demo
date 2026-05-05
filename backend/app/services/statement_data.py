"""
Financial Statement data service for the Ratio Lab module.

Uses the Company Facts API for the line-item catalog and historical time
series (consolidated, undimensioned), and edgartools XBRL for footnotes.
"""

from __future__ import annotations

import re
import logging
from typing import Any

from app.services.sec_data import (
    get_company_facts,
    get_annual_values,
    get_xbrl_filing,
    extract_text_blocks,
    resolve_cik,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Financial statement categorisation heuristics
# ---------------------------------------------------------------------------

_BS_PATTERNS = re.compile(
    r"(^Assets$|^Liabilities|^Equity|^StockholdersEquity|Current$|Noncurrent$|"
    r"Receivable|Payable|Inventory|CashAndCash|Goodwill|IntangibleAsset|"
    r"PropertyPlantAndEquipment|AccumulatedDepreciation|"
    r"RetainedEarnings|TreasuryStock|AccumulatedOtherComprehensive|"
    r"LongTermDebt|ShortTermBorrow|NotesPayable|Deposits|"
    r"DeferredTax(?:Assets|Liabilities)|OperatingLease(?:Right|Liability)|"
    r"Allowance|MarketableSecurity|InvestmentSecurit|PrepaidExpens)",
    re.IGNORECASE,
)

_IS_PATTERNS = re.compile(
    r"(Revenue|SalesRevenue|CostOf(?:Goods|Revenue|Sales)|GrossProfit|"
    r"OperatingIncome|OperatingExpens|InterestExpens|IncomeTax|NetIncome|"
    r"EarningsPerShare|Diluted|BasicEarnings|SellingGeneral|"
    r"ResearchAndDevelopment|Depreciation|Amortization|"
    r"ComprehensiveIncome|OtherIncome|IncomeLoss|Provision|"
    r"WeightedAverage.*Shares)",
    re.IGNORECASE,
)

_CF_PATTERNS = re.compile(
    r"(CashFlow|PaymentsTo(?:Acquire|Repurchase)|ProceedsFrom|"
    r"NetCashProvided|CapitalExpenditure|Dividend|"
    r"RepurchaseOfCommonStock|IssuanceOf|Repayment|"
    r"DepreciationAndAmortization|StockBasedCompensation|"
    r"IncreaseDecreaseIn|OperatingActivities|InvestingActivities|"
    r"FinancingActivities|EffectOfExchangeRate)",
    re.IGNORECASE,
)


def _categorise_concept(concept: str, is_instant: bool) -> str:
    """Assign a financial-statement category to an XBRL concept."""
    name = concept.split(":")[-1] if ":" in concept else concept

    if _CF_PATTERNS.search(name):
        return "cash_flow"
    if _IS_PATTERNS.search(name):
        return "income_statement"
    if _BS_PATTERNS.search(name) or is_instant:
        return "balance_sheet"
    return "other"


def _humanise_concept(name: str) -> str:
    """Convert CamelCase XBRL concept name to a readable label."""
    short = name.split(":")[-1] if ":" in name else name
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", short)
    return spaced.strip()


# ---------------------------------------------------------------------------
# Line-item catalog
# ---------------------------------------------------------------------------

def get_all_line_items(ticker: str) -> dict[str, Any]:
    """
    Build a browsable catalog of every US-GAAP / DEI / IFRS concept
    reported by this company via the Company Facts API.

    Returns {company, items, category_counts}.
    """
    facts = get_company_facts(ticker)
    entity_name = facts.get("entityName", ticker.upper())
    cik = str(facts.get("cik", "")).zfill(10)

    items: list[dict] = []
    seen: set[str] = set()

    for namespace, concepts in facts.get("facts", {}).items():
        for concept_name, concept_data in concepts.items():
            full_concept = f"{namespace}:{concept_name}"
            if full_concept in seen:
                continue
            seen.add(full_concept)

            label = concept_data.get("label") or _humanise_concept(concept_name)
            units_data = concept_data.get("units", {})

            best_unit = ""
            best_entries: list[dict] = []
            for unit_key, entries in units_data.items():
                if len(entries) > len(best_entries):
                    best_unit = unit_key
                    best_entries = entries

            if not best_entries:
                continue

            # Determine instant vs duration from the entries
            is_instant = any("end" in e and "start" not in e for e in best_entries[:5])

            annual_values: dict[int, float] = {}
            filed_dates: dict[int, str] = {}
            for e in best_entries:
                fy = e.get("fy")
                fp = e.get("fp", "")
                if fy and fp == "FY":
                    yr = int(fy)
                    filed = e.get("filed") or ""
                    if yr not in annual_values or filed > filed_dates.get(yr, ""):
                        annual_values[yr] = e["val"]
                        filed_dates[yr] = filed

            clean_values = annual_values
            if not clean_values:
                continue

            latest_year = max(clean_values.keys())
            category = _categorise_concept(concept_name, is_instant)

            items.append({
                "concept": full_concept,
                "label": label,
                "category": category,
                "unit": best_unit,
                "years_available": len(clean_values),
                "latest_value": clean_values[latest_year],
                "is_instant": is_instant,
            })

    items.sort(key=lambda x: (-x["years_available"], x["label"] or ""))

    category_counts = {}
    for item in items:
        cat = item["category"]
        category_counts[cat] = category_counts.get(cat, 0) + 1

    return {
        "company": {
            "name": entity_name,
            "ticker": ticker.upper(),
            "cik": cik,
            "form": "Company Facts",
            "filing_date": "",
        },
        "items": items,
        "category_counts": category_counts,
    }


# ---------------------------------------------------------------------------
# Selected line-item data
# ---------------------------------------------------------------------------

def get_line_item_data(
    ticker: str, concepts: list[str]
) -> list[dict[str, Any]]:
    """
    Fetch full historical time series for a list of concepts.
    Returns list of {concept, label, values}.
    """
    facts = get_company_facts(ticker)
    results: list[dict] = []

    for concept in concepts:
        parts = concept.split(":")
        ns = parts[0] if len(parts) == 2 else "us-gaap"
        name = parts[-1]

        concept_data = facts.get("facts", {}).get(ns, {}).get(name, {})
        label = concept_data.get("label", _humanise_concept(name))

        values = get_annual_values(ticker, name, unit="USD", instant=True)
        if not values:
            values = get_annual_values(ticker, name, unit="USD", instant=False)
        if not values:
            # Try non-USD units (shares, pure, etc.)
            for unit_key in concept_data.get("units", {}).keys():
                values = get_annual_values(ticker, name, unit=unit_key, instant=True)
                if not values:
                    values = get_annual_values(ticker, name, unit=unit_key, instant=False)
                if values:
                    break

        results.append({
            "concept": concept,
            "label": label,
            "values": values or {},
        })

    return results


# ---------------------------------------------------------------------------
# Footnotes (via XBRL filing)
# ---------------------------------------------------------------------------

def get_related_footnotes(
    ticker: str, concepts: list[str]
) -> list[dict[str, Any]]:
    """
    For selected concepts, search the XBRL filing for related text-block
    disclosures. Derives search keywords from the concept names.
    """
    keywords = set()
    for concept in concepts:
        name = concept.split(":")[-1] if ":" in concept else concept
        # Split CamelCase into words and take significant terms
        words = re.findall(r"[A-Z][a-z]+", name)
        # Build search substring from the first few significant words
        if len(words) >= 2:
            keywords.add("".join(words[:3]))
            keywords.add("".join(words[:2]))
        if words:
            keywords.add(words[0])

    try:
        meta, facts_df = get_xbrl_filing(ticker)
    except Exception as e:
        logger.warning(f"Could not load XBRL filing for footnotes: {e}")
        return []

    blocks: list[dict] = []
    seen_concepts: set[str] = set()

    for keyword in sorted(keywords, key=len, reverse=True):
        for b in extract_text_blocks(facts_df, keyword):
            if b["xbrl_concept"] not in seen_concepts:
                seen_concepts.add(b["xbrl_concept"])
                b["matched_keyword"] = keyword
                blocks.append(b)

    return blocks


# ---------------------------------------------------------------------------
# Custom ratio computation
# ---------------------------------------------------------------------------

def compute_custom_ratios(
    ticker: str,
    ratios: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Compute user-defined ratios.

    Each ratio has:
      - name: str
      - numerator_terms: [{concept, sign}]
      - denominator_terms: [{concept, sign}]
      - multiply_by: float

    Returns list of {name, definition, values, trend}.
    """
    # Pre-fetch all needed concepts
    all_concepts = set()
    for ratio in ratios:
        for term in ratio.get("numerator_terms", []):
            all_concepts.add(term["concept"])
        for term in ratio.get("denominator_terms", []):
            all_concepts.add(term["concept"])

    series_cache: dict[str, dict[int, float]] = {}
    for concept in all_concepts:
        name = concept.split(":")[-1] if ":" in concept else concept
        values = get_annual_values(ticker, name, unit="USD", instant=True)
        if not values:
            values = get_annual_values(ticker, name, unit="USD", instant=False)
        series_cache[concept] = values or {}

    results: list[dict] = []
    for ratio in ratios:
        ratio_name = ratio["name"]
        num_terms = ratio.get("numerator_terms", [])
        den_terms = ratio.get("denominator_terms", [])
        multiply_by = ratio.get("multiply_by", 1.0)

        # Collect all years where we have data for every term
        all_years: set[int] = set()
        for term in num_terms + den_terms:
            all_years |= set(series_cache.get(term["concept"], {}).keys())

        values: dict[int, float | None] = {}
        for year in sorted(all_years):
            try:
                numerator = 0.0
                for term in num_terms:
                    val = series_cache.get(term["concept"], {}).get(year)
                    if val is None:
                        raise ValueError("missing")
                    sign = -1.0 if term.get("sign", "+") == "-" else 1.0
                    numerator += sign * val

                denominator = 0.0
                for term in den_terms:
                    val = series_cache.get(term["concept"], {}).get(year)
                    if val is None:
                        raise ValueError("missing")
                    sign = -1.0 if term.get("sign", "+") == "-" else 1.0
                    denominator += sign * val

                if abs(denominator) < 1e-10:
                    values[year] = None
                else:
                    values[year] = round(numerator / denominator * multiply_by, 4)
            except (ValueError, KeyError):
                values[year] = None

        # Compute trend from last two non-null values
        non_null = [(yr, v) for yr, v in sorted(values.items()) if v is not None]
        trend = ""
        if len(non_null) >= 2:
            prev_val = non_null[-2][1]
            curr_val = non_null[-1][1]
            if prev_val and abs(prev_val) > 1e-10:
                change_pct = (curr_val - prev_val) / abs(prev_val) * 100
                if change_pct > 2:
                    trend = "up"
                elif change_pct < -2:
                    trend = "down"
                else:
                    trend = "stable"

        results.append({
            "name": ratio_name,
            "definition": ratio,
            "values": values,
            "trend": trend,
        })

    return results


# ---------------------------------------------------------------------------
# Ratio templates
# ---------------------------------------------------------------------------

RATIO_TEMPLATES: list[dict[str, Any]] = [
    # Liquidity
    {
        "name": "Current Ratio",
        "category": "Liquidity",
        "numerator_terms": [{"concept": "us-gaap:AssetsCurrent", "sign": "+"}],
        "denominator_terms": [{"concept": "us-gaap:LiabilitiesCurrent", "sign": "+"}],
        "multiply_by": 1.0,
        "required_concepts": ["AssetsCurrent", "LiabilitiesCurrent"],
    },
    {
        "name": "Quick Ratio",
        "category": "Liquidity",
        "numerator_terms": [
            {"concept": "us-gaap:CashAndCashEquivalentsAtCarryingValue", "sign": "+"},
            {"concept": "us-gaap:ShortTermInvestments", "sign": "+"},
            {"concept": "us-gaap:AccountsReceivableNetCurrent", "sign": "+"},
        ],
        "denominator_terms": [{"concept": "us-gaap:LiabilitiesCurrent", "sign": "+"}],
        "multiply_by": 1.0,
        "required_concepts": [
            "CashAndCashEquivalentsAtCarryingValue",
            "AccountsReceivableNetCurrent",
            "LiabilitiesCurrent",
        ],
    },
    {
        "name": "Cash Ratio",
        "category": "Liquidity",
        "numerator_terms": [
            {"concept": "us-gaap:CashAndCashEquivalentsAtCarryingValue", "sign": "+"},
        ],
        "denominator_terms": [{"concept": "us-gaap:LiabilitiesCurrent", "sign": "+"}],
        "multiply_by": 1.0,
        "required_concepts": ["CashAndCashEquivalentsAtCarryingValue", "LiabilitiesCurrent"],
    },
    # Profitability
    {
        "name": "Gross Margin",
        "category": "Profitability",
        "numerator_terms": [{"concept": "us-gaap:GrossProfit", "sign": "+"}],
        "denominator_terms": [{"concept": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "sign": "+"}],
        "multiply_by": 100.0,
        "required_concepts": ["GrossProfit", "RevenueFromContractWithCustomerExcludingAssessedTax"],
        "fallback_concepts": {
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax": [
                "us-gaap:Revenues",
                "us-gaap:SalesRevenueNet",
            ],
        },
    },
    {
        "name": "Operating Margin",
        "category": "Profitability",
        "numerator_terms": [{"concept": "us-gaap:OperatingIncomeLoss", "sign": "+"}],
        "denominator_terms": [{"concept": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "sign": "+"}],
        "multiply_by": 100.0,
        "required_concepts": ["OperatingIncomeLoss", "RevenueFromContractWithCustomerExcludingAssessedTax"],
        "fallback_concepts": {
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax": [
                "us-gaap:Revenues",
                "us-gaap:SalesRevenueNet",
            ],
        },
    },
    {
        "name": "Net Profit Margin",
        "category": "Profitability",
        "numerator_terms": [{"concept": "us-gaap:NetIncomeLoss", "sign": "+"}],
        "denominator_terms": [{"concept": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "sign": "+"}],
        "multiply_by": 100.0,
        "required_concepts": ["NetIncomeLoss", "RevenueFromContractWithCustomerExcludingAssessedTax"],
        "fallback_concepts": {
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax": [
                "us-gaap:Revenues",
                "us-gaap:SalesRevenueNet",
            ],
        },
    },
    {
        "name": "Return on Assets (ROA)",
        "category": "Profitability",
        "numerator_terms": [{"concept": "us-gaap:NetIncomeLoss", "sign": "+"}],
        "denominator_terms": [{"concept": "us-gaap:Assets", "sign": "+"}],
        "multiply_by": 100.0,
        "required_concepts": ["NetIncomeLoss", "Assets"],
    },
    {
        "name": "Return on Equity (ROE)",
        "category": "Profitability",
        "numerator_terms": [{"concept": "us-gaap:NetIncomeLoss", "sign": "+"}],
        "denominator_terms": [{"concept": "us-gaap:StockholdersEquity", "sign": "+"}],
        "multiply_by": 100.0,
        "required_concepts": ["NetIncomeLoss", "StockholdersEquity"],
    },
    # Leverage
    {
        "name": "Debt-to-Equity",
        "category": "Leverage",
        "numerator_terms": [{"concept": "us-gaap:Liabilities", "sign": "+"}],
        "denominator_terms": [{"concept": "us-gaap:StockholdersEquity", "sign": "+"}],
        "multiply_by": 1.0,
        "required_concepts": ["Liabilities", "StockholdersEquity"],
    },
    {
        "name": "Debt-to-Assets",
        "category": "Leverage",
        "numerator_terms": [{"concept": "us-gaap:Liabilities", "sign": "+"}],
        "denominator_terms": [{"concept": "us-gaap:Assets", "sign": "+"}],
        "multiply_by": 1.0,
        "required_concepts": ["Liabilities", "Assets"],
    },
    {
        "name": "Equity Multiplier",
        "category": "Leverage",
        "numerator_terms": [{"concept": "us-gaap:Assets", "sign": "+"}],
        "denominator_terms": [{"concept": "us-gaap:StockholdersEquity", "sign": "+"}],
        "multiply_by": 1.0,
        "required_concepts": ["Assets", "StockholdersEquity"],
    },
    {
        "name": "Interest Coverage",
        "category": "Leverage",
        "numerator_terms": [{"concept": "us-gaap:OperatingIncomeLoss", "sign": "+"}],
        "denominator_terms": [{"concept": "us-gaap:InterestExpense", "sign": "+"}],
        "multiply_by": 1.0,
        "required_concepts": ["OperatingIncomeLoss", "InterestExpense"],
    },
    # Efficiency
    {
        "name": "Asset Turnover",
        "category": "Efficiency",
        "numerator_terms": [{"concept": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "sign": "+"}],
        "denominator_terms": [{"concept": "us-gaap:Assets", "sign": "+"}],
        "multiply_by": 1.0,
        "required_concepts": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Assets"],
        "fallback_concepts": {
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax": [
                "us-gaap:Revenues",
                "us-gaap:SalesRevenueNet",
            ],
        },
    },
    {
        "name": "Inventory Turnover",
        "category": "Efficiency",
        "numerator_terms": [{"concept": "us-gaap:CostOfGoodsAndServicesSold", "sign": "+"}],
        "denominator_terms": [{"concept": "us-gaap:InventoryNet", "sign": "+"}],
        "multiply_by": 1.0,
        "required_concepts": ["CostOfGoodsAndServicesSold", "InventoryNet"],
        "fallback_concepts": {
            "us-gaap:CostOfGoodsAndServicesSold": [
                "us-gaap:CostOfRevenue",
                "us-gaap:CostOfGoodsSold",
            ],
        },
    },
    {
        "name": "Receivables Turnover",
        "category": "Efficiency",
        "numerator_terms": [{"concept": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "sign": "+"}],
        "denominator_terms": [{"concept": "us-gaap:AccountsReceivableNetCurrent", "sign": "+"}],
        "multiply_by": 1.0,
        "required_concepts": ["RevenueFromContractWithCustomerExcludingAssessedTax", "AccountsReceivableNetCurrent"],
        "fallback_concepts": {
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax": [
                "us-gaap:Revenues",
                "us-gaap:SalesRevenueNet",
            ],
        },
    },
    {
        "name": "Days Sales Outstanding",
        "category": "Efficiency",
        "numerator_terms": [{"concept": "us-gaap:AccountsReceivableNetCurrent", "sign": "+"}],
        "denominator_terms": [{"concept": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "sign": "+"}],
        "multiply_by": 365.0,
        "required_concepts": ["AccountsReceivableNetCurrent", "RevenueFromContractWithCustomerExcludingAssessedTax"],
        "fallback_concepts": {
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax": [
                "us-gaap:Revenues",
                "us-gaap:SalesRevenueNet",
            ],
        },
    },
    {
        "name": "Days Inventory Outstanding",
        "category": "Efficiency",
        "numerator_terms": [{"concept": "us-gaap:InventoryNet", "sign": "+"}],
        "denominator_terms": [{"concept": "us-gaap:CostOfGoodsAndServicesSold", "sign": "+"}],
        "multiply_by": 365.0,
        "required_concepts": ["InventoryNet", "CostOfGoodsAndServicesSold"],
        "fallback_concepts": {
            "us-gaap:CostOfGoodsAndServicesSold": [
                "us-gaap:CostOfRevenue",
                "us-gaap:CostOfGoodsSold",
            ],
        },
    },
    {
        "name": "Days Payable Outstanding",
        "category": "Efficiency",
        "numerator_terms": [{"concept": "us-gaap:AccountsPayableCurrent", "sign": "+"}],
        "denominator_terms": [{"concept": "us-gaap:CostOfGoodsAndServicesSold", "sign": "+"}],
        "multiply_by": 365.0,
        "required_concepts": ["AccountsPayableCurrent", "CostOfGoodsAndServicesSold"],
        "fallback_concepts": {
            "us-gaap:CostOfGoodsAndServicesSold": [
                "us-gaap:CostOfRevenue",
                "us-gaap:CostOfGoodsSold",
            ],
        },
    },
]


def get_ratio_templates() -> list[dict[str, Any]]:
    """Return the pre-built ratio templates."""
    return RATIO_TEMPLATES


def resolve_template_concepts(
    ticker: str, template: dict[str, Any]
) -> dict[str, Any]:
    """
    Resolve fallback concepts for a template against a specific company.
    Returns the template with concepts swapped to the first available match.
    """
    facts = get_company_facts(ticker)
    all_concepts_in_facts = set()
    for ns, ns_data in facts.get("facts", {}).items():
        for concept_name in ns_data.keys():
            all_concepts_in_facts.add(concept_name)
            all_concepts_in_facts.add(f"{ns}:{concept_name}")

    resolved = {**template}
    fallbacks = template.get("fallback_concepts", {})

    def _resolve(concept: str) -> str:
        short = concept.split(":")[-1]
        if short in all_concepts_in_facts or concept in all_concepts_in_facts:
            return concept
        for alt in fallbacks.get(concept, []):
            alt_short = alt.split(":")[-1]
            if alt_short in all_concepts_in_facts or alt in all_concepts_in_facts:
                return alt
        return concept

    resolved["numerator_terms"] = [
        {**t, "concept": _resolve(t["concept"])}
        for t in template["numerator_terms"]
    ]
    resolved["denominator_terms"] = [
        {**t, "concept": _resolve(t["concept"])}
        for t in template["denominator_terms"]
    ]

    # Check availability
    missing = []
    for req in template.get("required_concepts", []):
        found = req in all_concepts_in_facts
        if not found:
            for alt_list in fallbacks.values():
                if any(a.split(":")[-1] in all_concepts_in_facts for a in alt_list):
                    found = True
                    break
        if not found:
            missing.append(req)

    resolved["available"] = len(missing) == 0
    resolved["missing_concepts"] = missing

    return resolved
