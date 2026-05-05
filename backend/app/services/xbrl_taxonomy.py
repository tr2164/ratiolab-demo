"""
XBRL Taxonomy Reference Service (Legacy / Test Mode Support)

For production use, edgartools (edgar_service.py) handles XBRL parsing
with its own standardization of ~2000 tags → 95 concepts.

This module is retained for:
1. Test mode: parsing local CIK*.json companyfacts files
2. Tag caching: keeping track of which tags a company uses
3. Backward compatibility with existing API endpoints
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_tag_cache: Dict[str, List[Dict]] = {}


def extract_tags_from_companyfacts(facts_json: dict) -> List[Dict]:
    """Extract all us-gaap tags with labels/descriptions from a companyfacts JSON.

    Used by the local JSON (test mode) data path. For production,
    edgartools handles tag extraction and standardization.
    """
    us_gaap = facts_json.get("facts", {}).get("us-gaap", {})
    dei = facts_json.get("facts", {}).get("dei", {})

    tags = []
    for source_name, source_data in [("us-gaap", us_gaap), ("dei", dei)]:
        for tag_name, tag_data in source_data.items():
            units = tag_data.get("units", {})
            unit_types = list(units.keys())
            has_usd = "USD" in unit_types
            has_shares = "shares" in unit_types

            stmt_hint = _infer_statement_type(tag_name, has_usd, has_shares)

            tags.append({
                "tag": f"{source_name}:{tag_name}",
                "tag_short": tag_name,
                "label": tag_data.get("label", tag_name),
                "description": tag_data.get("description", ""),
                "units": unit_types,
                "statement_hint": stmt_hint,
                "source": source_name,
            })

    return tags


def _infer_statement_type(tag_name: str, has_usd: bool, has_shares: bool) -> str:
    """Heuristic statement type inference from tag name patterns."""
    tag_lower = tag_name.lower()

    cf_patterns = [
        "cashprovided", "cashused", "netcash", "payments", "proceeds",
        "depreciation", "amortization", "sharebasedcomp",
        "increasedecrease", "dividendspaid", "repurchase",
        "capitalexpenditure", "paymentstoacquire",
    ]
    if any(p in tag_lower for p in cf_patterns):
        return "CF"

    bs_patterns = [
        "assets", "liabilities", "equity", "receivable", "payable",
        "inventory", "cash", "debt", "goodwill", "intangible",
        "retained", "treasury", "prepaid", "accrued", "deferred",
        "property", "stockholders", "investment", "current",
    ]
    if any(p in tag_lower for p in bs_patterns):
        return "BS"

    is_patterns = [
        "revenue", "income", "expense", "cost", "profit", "loss",
        "earning", "operating", "interest", "tax", "selling",
        "research", "development", "administrative", "impairment",
    ]
    if any(p in tag_lower for p in is_patterns):
        return "IS"

    if has_shares and not has_usd:
        return "BS"

    return "IS"


def get_cached_tags(ticker: str) -> Optional[List[Dict]]:
    """Get cached tags for a ticker."""
    return _tag_cache.get(ticker.upper())


def cache_tags(ticker: str, tags: List[Dict]):
    """Cache tags for a ticker."""
    _tag_cache[ticker.upper()] = tags


def get_tag_labels(tags: List[Dict]) -> Dict[str, str]:
    """Build a tag -> label lookup from extracted tags."""
    return {t["tag"]: t["label"] for t in tags}


def get_tags_for_statement(tags: List[Dict], stmt_type: str) -> List[Dict]:
    """Filter tags by statement type hint."""
    return [t for t in tags if t["statement_hint"] == stmt_type]
