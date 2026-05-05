"""
EdgarTools integration service.

Wraps the edgartools library for standardized XBRL data extraction from SEC EDGAR.
EdgarTools handles:
  - XBRL parsing (inline + attached)
  - Tag standardization (~2000 tags → 95 concepts)
  - Multi-period statement stitching
  - Dimensional/segment data
  - Rate limiting and identity management
  - Local file caching

This replaces our manual companyfacts JSON parsing for production use.
Test mode still uses local CIK*.json files via financial_data_service.
"""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_edgar_initialized = False


def _ensure_init():
    """Lazy-initialize edgartools with identity, caching, rate limiting, and SSL."""
    global _edgar_initialized
    if _edgar_initialized:
        return

    import os

    import edgar as edgar_lib

    from app.config import get_ssl_verify

    identity = settings.edgar_identity or settings.sec_user_agent
    if identity:
        edgar_lib.set_identity(identity)
    else:
        raise ValueError(
            "EDGAR_IDENTITY (or SEC_USER_AGENT) must be set for SEC compliance"
        )

    cache_dir = settings.edgar_cache_dir
    if cache_dir:
        cache_path = Path(cache_dir)
        if not cache_path.is_absolute():
            cache_path = Path(__file__).resolve().parents[2] / cache_dir
        cache_path.mkdir(parents=True, exist_ok=True)
        edgar_lib.set_local_storage_path(str(cache_path))
        edgar_lib.use_local_storage()
        logger.info(f"EdgarTools local cache: {cache_path}")

    ssl_bundle = get_ssl_verify()
    if isinstance(ssl_bundle, str) and os.path.isfile(ssl_bundle):
        os.environ["SSL_CERT_FILE"] = ssl_bundle
        os.environ["REQUESTS_CA_BUNDLE"] = ssl_bundle
        logger.info(f"EdgarTools SSL: using combined CA bundle ({ssl_bundle})")

    _edgar_initialized = True
    logger.info(f"EdgarTools initialized (identity={identity[:30]}...)")


def get_company_info(ticker: str) -> Dict[str, Any]:
    """Fetch basic company profile from SEC EDGAR."""
    _ensure_init()
    from edgar import Company

    company = Company(ticker.upper())
    return {
        "ticker": ticker.upper(),
        "name": company.name,
        "cik": str(company.cik),
    }


def fetch_statements(
    ticker: str, periods: int = 5
) -> Dict[str, pd.DataFrame]:
    """Fetch multi-year standardized financial statements as DataFrames.

    Returns a dict keyed by statement type ("IS", "BS", "CF") with
    pandas DataFrames containing standardized, stitched multi-period data.
    """
    _ensure_init()
    from edgar import Company
    from edgar.xbrl import XBRLS

    company = Company(ticker.upper())

    filings = company.get_filings(form="10-K").head(periods)
    try:
        filing_count = len(filings)
    except TypeError:
        filing_count = len(list(filings))
        filings = company.get_filings(form="10-K").head(periods)

    if filing_count == 0:
        for alt_form in ("20-F", "40-F"):
            alt = company.get_filings(form=alt_form).head(1)
            try:
                alt_count = len(alt)
            except TypeError:
                alt_count = len(list(alt))
            if alt_count > 0:
                raise ValueError(
                    f"{ticker} is a foreign filer ({alt_form}). "
                    f"Only US-GAAP companies (10-K) are supported. "
                    f"Foreign filers use IFRS and report in local currency."
                )
        raise ValueError(f"No annual filings found for {ticker}")

    logger.info(f"Fetching {filing_count} 10-K filings for {ticker}")
    xbrls = XBRLS.from_filings(filings)
    stmts = xbrls.statements

    result = {}
    accessors = [
        ("IS", "income_statement"),
        ("BS", "balance_sheet"),
        ("CF", "cashflow_statement"),
    ]

    for stmt_type, method_name in accessors:
        try:
            stmt = getattr(stmts, method_name)()
            df = stmt.to_dataframe()
            result[stmt_type] = df
            logger.info(f"  {stmt_type}: {len(df)} line items")
        except Exception as e:
            logger.warning(f"  {stmt_type}: not available ({e})")

    return result


def _extract_year_from_column(col: str) -> Optional[int]:
    """Try to extract a year from a DataFrame column name.

    EdgarTools uses various column formats: plain years ("2024"),
    dates ("2024-01-28"), or period labels ("Dec 2024").
    """
    col_str = str(col).strip()

    # Plain 4-digit year
    if len(col_str) == 4 and col_str.isdigit():
        year = int(col_str)
        if 1990 <= year <= 2035:
            return year

    # ISO date: "2024-01-28"
    if len(col_str) >= 10 and col_str[4] == "-":
        try:
            year = int(col_str[:4])
            if 1990 <= year <= 2035:
                return year
        except ValueError:
            pass

    # Month-year: "Dec 2024", "September 2023"
    parts = col_str.split()
    for part in parts:
        if len(part) == 4 and part.isdigit():
            year = int(part)
            if 1990 <= year <= 2035:
                return year

    return None


# Columns that are metadata, not financial period data
_META_COLUMNS = frozenset({
    "label", "standard_concept", "concept", "level",
    "abstract", "negated", "units", "decimals",
})


def statements_to_records(
    statements: Dict[str, pd.DataFrame],
) -> List[Dict[str, Any]]:
    """Convert edgartools DataFrames to flat records suitable for DB storage.

    Each record has: account_name, raw_label, standard_concept,
    year, amount, statement_type, source_api.
    """
    records = []

    for stmt_type, df in statements.items():
        if df is None or df.empty:
            continue

        year_cols = []
        for col in df.columns:
            if str(col).lower() in _META_COLUMNS:
                continue
            year = _extract_year_from_column(col)
            if year is not None:
                year_cols.append((col, year))

        if not year_cols:
            logger.warning(f"No year columns found in {stmt_type} DataFrame")
            continue

        for _, row in df.iterrows():
            label = str(row.get("label", ""))
            standard_concept = str(row.get("standard_concept", "")) if "standard_concept" in df.columns else ""

            if row.get("abstract", False):
                continue
            if not label:
                continue

            account_name = standard_concept if standard_concept else label

            for col, year in year_cols:
                value = row.get(col)
                if value is None:
                    continue
                if isinstance(value, float) and pd.isna(value):
                    continue
                try:
                    amount = float(value)
                except (ValueError, TypeError):
                    continue

                records.append({
                    "account_name": account_name,
                    "raw_label": label,
                    "standard_concept": standard_concept,
                    "year": year,
                    "amount": amount,
                    "statement_type": stmt_type,
                    "source_api": "edgartools",
                })

    return records


def get_preliminary_analysis(
    ticker: str, periods: int = 5
) -> Dict[str, Any]:
    """Analyze a company's XBRL structure for operator review.

    This is "Step 1" of the data map workflow:
    1. Fetch standardized data via edgartools
    2. Catalog what line items exist, which are standard vs custom
    3. Present to the operator for review before building the model
    """
    info = get_company_info(ticker)
    statements = fetch_statements(ticker, periods)
    records = statements_to_records(statements)

    all_items: Dict[str, Dict] = {}
    years = set()

    for rec in records:
        key = f"{rec['statement_type']}:{rec['account_name']}"
        if key not in all_items:
            all_items[key] = {
                "account_name": rec["account_name"],
                "raw_label": rec.get("raw_label", ""),
                "standard_concept": rec.get("standard_concept", ""),
                "statement_type": rec["statement_type"],
                "years_with_data": [],
                "sample_values": {},
            }
        all_items[key]["years_with_data"].append(rec["year"])
        all_items[key]["sample_values"][rec["year"]] = rec["amount"]
        years.add(rec["year"])

    standard_items = [i for i in all_items.values() if i["standard_concept"]]
    custom_items = [i for i in all_items.values() if not i["standard_concept"]]

    return {
        "ticker": ticker.upper(),
        "company_info": info,
        "years_available": sorted(years),
        "total_line_items": len(all_items),
        "standard_items_count": len(standard_items),
        "custom_items_count": len(custom_items),
        "statements": {
            "IS": sorted(
                [i for i in all_items.values() if i["statement_type"] == "IS"],
                key=lambda x: x["account_name"],
            ),
            "BS": sorted(
                [i for i in all_items.values() if i["statement_type"] == "BS"],
                key=lambda x: x["account_name"],
            ),
            "CF": sorted(
                [i for i in all_items.values() if i["statement_type"] == "CF"],
                key=lambda x: x["account_name"],
            ),
        },
        "standard_items": standard_items,
        "custom_items": custom_items,
    }


def get_standardized_metrics(ticker: str) -> Dict[str, Any]:
    """Get key financial metrics using edgartools' standardized accessors.

    These work consistently across all companies regardless of their
    custom XBRL concepts.
    """
    _ensure_init()
    from edgar import Company

    company = Company(ticker.upper())
    financials = company.get_financials()

    if not financials:
        return {}

    metrics = {}
    accessors = {
        "revenue": "get_revenue",
        "net_income": "get_net_income",
        "total_assets": "get_total_assets",
        "total_liabilities": "get_total_liabilities",
        "stockholders_equity": "get_stockholders_equity",
        "operating_cash_flow": "get_operating_cash_flow",
        "capital_expenditures": "get_capital_expenditures",
        "free_cash_flow": "get_free_cash_flow",
        "current_assets": "get_current_assets",
        "current_liabilities": "get_current_liabilities",
    }

    for key, method_name in accessors.items():
        try:
            method = getattr(financials, method_name, None)
            if method:
                metrics[key] = method()
        except Exception:
            metrics[key] = None

    return metrics
