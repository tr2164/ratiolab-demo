"""
SEC EDGAR data accessor.

Two data sources, each serving a different purpose:

1. Company Facts JSON API (data.sec.gov)
   - Historical time-series of every US-GAAP concept
   - Fast, no parsing needed
   - No text blocks, no segment/dimension breakdowns

2. edgartools XBRL (full filing)
   - Text block disclosures (policy, footnotes, tables)
   - Dimensioned data (PP&E by asset type, useful lives)
   - Only for one filing at a time
"""

from __future__ import annotations

import re
import logging
from functools import lru_cache
from typing import Any

import requests
import pandas as pd
from bs4 import BeautifulSoup
from edgar import Company, set_identity
from edgar.xbrl import XBRL

logger = logging.getLogger(__name__)

SEC_EMAIL = "nyu.finsight@nyu.edu"
SEC_HEADERS = {"User-Agent": SEC_EMAIL, "Accept-Encoding": "gzip, deflate"}

set_identity(SEC_EMAIL)


# ---------------------------------------------------------------------------
# CIK resolution
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _ticker_map() -> dict[str, str]:
    """Fetch the SEC ticker → CIK mapping (cached for the process lifetime)."""
    from app.services.cache import cached_get_json

    url = "https://www.sec.gov/files/company_tickers.json"
    data = cached_get_json(url, headers=SEC_HEADERS, timeout=15)
    return {
        entry["ticker"].upper(): str(entry["cik_str"]).zfill(10)
        for entry in data.values()
    }


def resolve_cik(ticker: str) -> str:
    mapping = _ticker_map()
    key = ticker.upper()
    if key not in mapping:
        raise ValueError(f"Ticker '{ticker}' not found in SEC ticker list")
    return mapping[key]


# ---------------------------------------------------------------------------
# Company Facts JSON API
# ---------------------------------------------------------------------------

_facts_cache: dict[str, dict] = {}


def get_company_facts(ticker: str) -> dict:
    """Fetch the full Company Facts JSON from SEC EDGAR."""
    from app.services.cache import cached_get_json

    key = ticker.upper()
    if key in _facts_cache:
        return _facts_cache[key]

    cik = resolve_cik(key)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    data = cached_get_json(url, headers=SEC_HEADERS, timeout=30)
    _facts_cache[key] = data
    return data


def get_annual_values(
    ticker: str, concept: str, unit: str = "USD", instant: bool = True
) -> dict[int, float]:
    """
    Extract annual values for a specific GAAP concept from Company Facts.
    Returns {year: value} dict.
    """
    facts = get_company_facts(ticker)
    ns_data = facts.get("facts", {})

    concept_data = None
    for ns in ["us-gaap", "dei", "ifrs-full"]:
        concept_data = ns_data.get(ns, {}).get(concept)
        if concept_data:
            break
    if not concept_data:
        return {}

    entries = concept_data.get("units", {}).get(unit, [])
    result: dict[int, float] = {}

    for e in entries:
        frame = e.get("frame", "")
        fy = e.get("fy")

        if instant:
            if re.match(r"^CY\d{4}Q4I$", frame):
                year = int(frame[2:6])
            elif fy and e.get("fp") == "FY":
                year = int(fy)
            else:
                continue
        else:
            if re.match(r"^CY\d{4}$", frame):
                year = int(frame[2:6])
            elif fy and e.get("fp") == "FY":
                year = int(fy)
            else:
                continue

        if year not in result or e.get("filed", "") > result.get("_filed_" + str(year), ""):
            result[year] = e["val"]
            result["_filed_" + str(year)] = e.get("filed", "")

    return {k: v for k, v in result.items() if not str(k).startswith("_")}


# ---------------------------------------------------------------------------
# edgartools XBRL (full filing)
# ---------------------------------------------------------------------------

_xbrl_cache: dict[str, tuple[Any, pd.DataFrame]] = {}


def get_xbrl_filing(ticker: str, form: str = "10-K") -> tuple[Any, pd.DataFrame]:
    """
    Fetch the latest filing's XBRL data via edgartools.
    Returns (filing_metadata, facts_dataframe).
    """
    key = f"{ticker.upper()}_{form}"
    if key in _xbrl_cache:
        return _xbrl_cache[key]

    company = Company(ticker)
    filing = company.get_filings(form=form).latest()
    if filing is None:
        raise ValueError(
            f"No {form} filing found for '{ticker.upper()}'. "
            f"This company may file under a different form (e.g. 20-F for foreign issuers)."
        )
    xbrl = XBRL.from_filing(filing)
    facts_df = xbrl.facts.to_dataframe()

    meta = {
        "name": company.name,
        "ticker": ticker.upper(),
        "cik": str(company.cik),
        "form": filing.form,
        "filing_date": str(filing.filing_date),
    }
    _xbrl_cache[key] = (meta, facts_df)
    return meta, facts_df


# ---------------------------------------------------------------------------
# Text block extraction
# ---------------------------------------------------------------------------

def extract_text_blocks(facts_df: pd.DataFrame, concept_filter: str) -> list[dict]:
    """
    Find XBRL text block facts matching a concept substring.
    Returns list of {concept, html, text, xbrl_concept} dicts.
    """
    mask = facts_df["concept"].str.contains(concept_filter, case=False, na=False)
    blocks = []
    for _, row in facts_df[mask].iterrows():
        raw_value = str(row.get("value", ""))
        if len(raw_value) < 20:
            continue
        soup = BeautifulSoup(raw_value, "html.parser")
        clean_text = soup.get_text(separator="\n", strip=True)
        blocks.append({
            "xbrl_concept": row["concept"],
            "html": raw_value,
            "text": clean_text,
            "period": row.get("period_key", ""),
            "fiscal_year": row.get("fiscal_year"),
        })
    return blocks


def parse_html_table(html: str) -> list[dict[str, str]]:
    """
    Extract tabular data from an HTML text block.
    Returns list of row dicts keyed by col_0, col_1, …
    Preserves empty cells so column alignment stays correct.
    """
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if not tables:
        return []

    best = max(tables, key=lambda t: len(t.find_all("tr")))
    rows = best.find_all("tr")
    if len(rows) < 2:
        return []

    result = []
    for row in rows:
        cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
        row_dict = {f"col_{i}": c for i, c in enumerate(cells)}
        result.append(row_dict)
    return result


# ---------------------------------------------------------------------------
# Dimensioned PP&E facts
# ---------------------------------------------------------------------------

PPE_DIM_COL = "dim_us-gaap_PropertyPlantAndEquipmentByTypeAxis"
RANGE_DIM_COL = "dim_srt_RangeAxis"


def extract_ppe_useful_lives(facts_df: pd.DataFrame) -> list[dict]:
    """
    Extract useful life data, optionally dimensioned by asset type.
    Handles min/max ranges via the RangeAxis dimension.
    Falls back to undimensioned facts if no asset-type axis is present.
    """
    mask = facts_df["concept"].str.contains("PropertyPlantAndEquipmentUsefulLife", na=False)
    subset = facts_df[mask].copy()
    if subset.empty:
        return []

    # Determine the best axis to group by: prefer PropertyPlantAndEquipmentByTypeAxis,
    # then any other dim_ column that has populated values on these rows.
    group_col = None
    if PPE_DIM_COL in subset.columns and subset[PPE_DIM_COL].notna().any():
        group_col = PPE_DIM_COL
    else:
        for col in subset.columns:
            if col.startswith("dim_") and col != RANGE_DIM_COL and subset[col].notna().any():
                group_col = col
                break

    items: dict[str, dict] = {}
    for _, row in subset.iterrows():
        duration_str = str(row.get("value", ""))
        years = _parse_iso_duration(duration_str)
        if years is None:
            continue

        if group_col and pd.notna(row.get(group_col)):
            member = str(row[group_col])
            member_label = _clean_member(member)
        else:
            member = row["concept"]
            member_label = "General"

        range_member = str(row.get(RANGE_DIM_COL, "")) if RANGE_DIM_COL in facts_df.columns else ""

        if member_label not in items:
            items[member_label] = {
                "asset_type": member_label,
                "xbrl_member": member,
                "xbrl_concept": row["concept"],
                "useful_life_min": None,
                "useful_life_max": None,
                "useful_life_raw_min": None,
                "useful_life_raw_max": None,
            }

        if "Minimum" in range_member:
            items[member_label]["useful_life_min"] = years
            items[member_label]["useful_life_raw_min"] = duration_str
        elif "Maximum" in range_member:
            items[member_label]["useful_life_max"] = years
            items[member_label]["useful_life_raw_max"] = duration_str
        else:
            if items[member_label]["useful_life_min"] is None or years < items[member_label]["useful_life_min"]:
                items[member_label]["useful_life_min"] = years
                items[member_label]["useful_life_raw_min"] = duration_str
            if items[member_label]["useful_life_max"] is None or years > items[member_label]["useful_life_max"]:
                items[member_label]["useful_life_max"] = years
                items[member_label]["useful_life_raw_max"] = duration_str

    return list(items.values())


def extract_ppe_totals(facts_df: pd.DataFrame) -> dict:
    """
    Extract aggregate PP&E values (gross, accumulated depreciation, net)
    from undimensioned XBRL facts only — these are the consolidated totals.
    """
    concepts = {
        "gross": [
            "us-gaap:PropertyPlantAndEquipmentGross",
            "us-gaap:PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetBeforeAccumulatedDepreciationAndAmortization",
        ],
        "accumulated_depreciation": [
            "us-gaap:AccumulatedDepreciationDepletionAndAmortizationPropertyPlantAndEquipment",
            "us-gaap:PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAccumulatedDepreciationAndAmortization",
        ],
        "net": [
            "us-gaap:PropertyPlantAndEquipmentNet",
            "us-gaap:PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization",
        ],
    }

    is_dim = facts_df.get("is_dimensioned", pd.Series(False, index=facts_df.index)).astype(bool)

    result = {}
    for key, concept_list in concepts.items():
        for concept in concept_list:
            mask = (
                (facts_df["concept"] == concept)
                & (facts_df["numeric_value"].notna())
                & (~is_dim)
            )
            matches = facts_df[mask]
            if matches.empty:
                continue

            values = {}
            for _, row in matches.iterrows():
                fy = row.get("fiscal_year")
                if pd.notna(fy):
                    values[int(fy)] = float(row["numeric_value"])

            if values:
                result[key] = {
                    "xbrl_concept": concept,
                    "values": dict(sorted(values.items())),
                }
                break

    return result


# ---------------------------------------------------------------------------
# HTML table extraction for totals fallback
# ---------------------------------------------------------------------------

_TOTAL_ROW_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("gross",                    re.compile(r"(?i)total\s+(?:land|property|plant|pp)", re.I)),
    ("gross",                    re.compile(r"(?i)(?:land|property).*(?:plant|equipment).*(?:gross|before)", re.I)),
    ("accumulated_depreciation", re.compile(r"(?i)accum\w*\s+depreci", re.I)),
    ("net",                      re.compile(r"(?i)(?:total\s+)?(?:property|land|plant).*(?:net|after)", re.I)),
    ("net",                      re.compile(r"(?i)net\s+(?:property|land|plant)", re.I)),
]


def _parse_dollar(s: str) -> float | None:
    """Parse '$41,928' or '(33,525)' → float (units as shown in table)."""
    s = s.strip().replace("$", "").replace(",", "").replace("\xa0", "").replace(" ", "")
    if not s or s in ("—", "-", "–"):
        return None
    negative = s.startswith("(") and s.endswith(")")
    if negative:
        s = s[1:-1]
    try:
        val = float(s)
        return -val if negative else val
    except ValueError:
        return None


def _detect_scale(html: str) -> float:
    """Detect the reporting scale from the HTML: millions, thousands, etc."""
    lower = html.lower()
    if "in million" in lower or "(millions)" in lower:
        return 1_000_000
    if "in thousand" in lower or "(thousands)" in lower:
        return 1_000
    if "in billion" in lower or "(billions)" in lower:
        return 1_000_000_000
    return 1_000_000  # default assumption for SEC filings


def _find_numeric_cells(row: dict[str, str]) -> list[tuple[str, float]]:
    """Return all (col_key, value) pairs that contain a parseable number."""
    results = []
    for k, v in row.items():
        if k == "col_0":
            continue
        parsed = _parse_dollar(str(v))
        if parsed is not None:
            results.append((k, parsed))
    return results


def extract_totals_from_html(facts_df: pd.DataFrame) -> dict:
    """
    Parse the PP&E footnote HTML table to extract consolidated totals.
    This is the most reliable source for companies with complex segments.
    """
    html_concepts = [
        "PropertyPlantAndEquipmentTextBlock",
        "PropertyPlantAndEquipmentDisclosureTextBlock",
    ]

    for concept_substr in html_concepts:
        blocks = extract_text_blocks(facts_df, concept_substr)
        for block in blocks:
            html = block["html"]
            rows = parse_html_table(html)
            if len(rows) < 3:
                continue

            scale = _detect_scale(html)

            # Detect year columns: scan ALL rows for cells containing a 4-digit year
            year_cols: dict[int, int] = {}   # year → col_index
            for scan_row in rows[:5]:
                for col_key, val in scan_row.items():
                    m = re.search(r"(20\d{2})", str(val))
                    if m:
                        idx = int(col_key.split("_")[1]) if col_key.startswith("col_") else 0
                        yr = int(m.group(1))
                        if yr not in year_cols:
                            year_cols[yr] = idx

            if not year_cols:
                continue

            result: dict[str, dict] = {}
            for row in rows:
                # Build the label from the first non-empty cell
                label = ""
                for i in range(min(3, len(row))):
                    v = row.get(f"col_{i}", "")
                    if v and not re.match(r'^[\s$,.()\d—–-]*$', v):
                        label = v
                        break
                if not label:
                    continue

                for key, pattern in _TOTAL_ROW_PATTERNS:
                    if key in result:
                        continue
                    if not pattern.search(label):
                        continue

                    # Grab all numeric cells from this row
                    numerics = _find_numeric_cells(row)
                    if not numerics:
                        continue

                    # Match numeric cells to years by proximity to the year column
                    values: dict[int, float] = {}
                    for yr, yr_col_idx in year_cols.items():
                        best = None
                        best_dist = 999
                        for col_key, val in numerics:
                            ci = int(col_key.split("_")[1]) if col_key.startswith("col_") else 0
                            dist = abs(ci - yr_col_idx)
                            if dist < best_dist and dist <= 3:
                                best = val
                                best_dist = dist
                        if best is not None:
                            values[yr] = abs(best) * scale

                    if values:
                        result[key] = {
                            "xbrl_concept": f"HTML footnote table ({label.strip()[:80]})",
                            "values": dict(sorted(values.items())),
                        }

            if result:
                logger.info(f"HTML table extraction found: {list(result.keys())}")
                return result

    return {}


# ---------------------------------------------------------------------------
# Segment breakdowns (dimensioned PP&E)
# ---------------------------------------------------------------------------

_PPE_AXES = [
    "dim_us-gaap_PropertyPlantAndEquipmentByTypeAxis",
    "dim_us-gaap_StatementBusinessSegmentsAxis",
    "dim_srt_ConsolidationItemsAxis",
]

_PPE_CONCEPT_PATTERN = re.compile(r"PropertyPlantAndEquipment", re.IGNORECASE)


def extract_ppe_segments(facts_df: pd.DataFrame) -> list[dict]:
    """
    Extract PP&E by dimension (asset type or business segment).

    Uses a dimension-first approach: the XBRL axis determines relevance,
    with a broad concept substring filter to exclude unrelated rows that
    companies sometimes report on the same axis.
    """
    available_axes = [ax for ax in _PPE_AXES if ax in facts_df.columns]
    if not available_axes:
        return []

    numeric = facts_df[facts_df["numeric_value"].notna()].copy()
    concept_mask = numeric["concept"].str.contains(_PPE_CONCEPT_PATTERN, na=False)
    ppe_rows = numeric[concept_mask]

    if ppe_rows.empty:
        return []

    segments: list[dict] = []
    seen: set[str] = set()

    for ax in available_axes:
        if ax not in ppe_rows.columns:
            continue
        ax_rows = ppe_rows[ppe_rows[ax].notna()]

        # Prefer FY rows per-axis to avoid dropping rows with no fiscal_period
        if "fiscal_period" in ax_rows.columns:
            fy_rows = ax_rows[
                ax_rows["fiscal_period"].eq("FY") | ax_rows["fiscal_period"].isna()
            ]
            if not fy_rows.empty:
                ax_rows = fy_rows
        if ax_rows.empty:
            continue

        for member, grp in ax_rows.groupby(ax):
            member_str = str(member)
            member_label = _clean_member(member_str)

            for concept, concept_grp in grp.groupby("concept"):
                dedup_key = f"{member_label}|{concept}"
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                year_vals: dict[int, float] = {}
                for _, row in concept_grp.iterrows():
                    fy = row.get("fiscal_year")
                    if pd.notna(fy):
                        yr = int(fy)
                        val = float(row["numeric_value"])
                        if yr not in year_vals or abs(val) > abs(year_vals[yr]):
                            year_vals[yr] = val

                if year_vals:
                    segments.append({
                        "segment_label": member_label,
                        "xbrl_member": member_str,
                        "xbrl_concept": str(concept),
                        "dimension_axis": ax.replace("dim_", ""),
                        "values": dict(sorted(year_vals.items())),
                    })

    return segments


# ---------------------------------------------------------------------------
# Combined totals with multi-level fallback
# ---------------------------------------------------------------------------

def get_totals_with_fallback(ticker: str, facts_df: pd.DataFrame) -> dict:
    """
    Get PP&E consolidated totals using a waterfall of sources:
      1. Undimensioned XBRL facts (most companies)
      2. Company Facts API (SEC historical JSON)
      3. HTML footnote table parsing (authoritative for complex filers)
    """
    totals = extract_ppe_totals(facts_df)

    # Fallback 2: Company Facts API
    fallback_map = {
        "gross": [
            "PropertyPlantAndEquipmentGross",
            "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetBeforeAccumulatedDepreciationAndAmortization",
        ],
        "accumulated_depreciation": [
            "AccumulatedDepreciationDepletionAndAmortizationPropertyPlantAndEquipment",
            "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAccumulatedDepreciationAndAmortization",
        ],
        "net": [
            "PropertyPlantAndEquipmentNet",
            "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization",
        ],
    }

    for key, concept_list in fallback_map.items():
        if key in totals:
            continue
        for concept in concept_list:
            try:
                values = get_annual_values(ticker, concept, instant=True)
                if values:
                    logger.info(f"{key}: using Company Facts API fallback ({concept})")
                    totals[key] = {
                        "xbrl_concept": f"us-gaap:{concept} (via Company Facts API)",
                        "values": dict(sorted(values.items())),
                    }
                    break
            except Exception:
                pass

    # Fallback 3: parse the HTML footnote table
    missing = [k for k in ("gross", "accumulated_depreciation", "net") if k not in totals]
    if missing:
        logger.info(f"Missing {missing} — trying HTML footnote table extraction")
        html_totals = extract_totals_from_html(facts_df)
        for key, val in html_totals.items():
            if key not in totals:
                logger.info(f"{key}: filled from HTML table → {val['xbrl_concept']}")
                totals[key] = val

    return totals


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_member(raw: str) -> str:
    if ":" in raw:
        raw = raw.split(":")[-1]
    raw = raw.replace("Member", "")
    raw = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", raw)
    return raw.strip()


def _parse_iso_duration(s: str) -> float | None:
    """Convert ISO 8601 duration like 'P5Y0M' or 'P10Y' to years."""
    m = re.match(r"P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)D)?", s)
    if not m:
        return None
    years = int(m.group(1) or 0)
    months = int(m.group(2) or 0)
    days = int(m.group(3) or 0)
    return years + months / 12 + days / 365
