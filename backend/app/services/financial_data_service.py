"""
Stage 1: Data Ingestion

Fetches financial data from SEC EDGAR via edgartools and stores it in the database.
EdgarTools standardizes ~2000 XBRL tags into ~95 concepts, handling multi-period
stitching, consolidated reporting, and SEC rate limiting automatically.
"""
import logging
from typing import Optional

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings, get_ssl_verify
from app.models.company import Company
from app.models.financial_data import FinancialData

logger = logging.getLogger(__name__)
settings = get_settings()


async def resolve_cik(ticker: str) -> Optional[str]:
    """Resolve ticker to CIK. Checks local company_tickers.json first, then SEC API."""
    import json as json_mod
    from pathlib import Path

    for candidate in [
        Path(__file__).resolve().parents[2] / "company_tickers.json",
        Path(__file__).resolve().parents[3] / "company_tickers.json",
    ]:
        if candidate.exists():
            with open(candidate) as f:
                data = json_mod.load(f)
            for entry in data.values():
                if entry.get("ticker", "").upper() == ticker.upper():
                    return str(entry["cik_str"]).zfill(10)
            break

    tickers_url = "https://www.sec.gov/files/company_tickers.json"
    async with httpx.AsyncClient(verify=get_ssl_verify()) as client:
        resp = await client.get(
            tickers_url, headers={"User-Agent": settings.sec_user_agent}
        )
        if resp.status_code == 200:
            data = resp.json()
            for entry in data.values():
                if entry.get("ticker", "").upper() == ticker.upper():
                    return str(entry["cik_str"]).zfill(10)
    return None


async def fetch_financials(
    ticker: str, db: AsyncSession, periods: int = 7
) -> Company:
    """Fetch financial data using edgartools (standardized XBRL parsing).

    EdgarTools handles:
    - ~2000 XBRL tags standardized to ~95 concepts
    - Multi-period stitching across filings
    - Consolidated vs dimensional reporting
    - Custom/extension taxonomy tags
    - SEC rate limiting and identity
    """
    from app.services.edgar_service import (
        fetch_statements,
        get_company_info,
        statements_to_records,
    )

    info = get_company_info(ticker)
    cik = info.get("cik", "")
    company_name = info.get("name", ticker.upper())

    result = await db.execute(
        select(Company).where(Company.ticker == ticker.upper())
    )
    company = result.scalar_one_or_none()
    if not company:
        company = Company(ticker=ticker.upper(), cik=cik, name=company_name)
        db.add(company)
        await db.flush()
    else:
        company.name = company_name
        company.cik = cik

    await db.execute(
        delete(FinancialData).where(FinancialData.company_id == company.id)
    )

    statements = fetch_statements(ticker, periods)
    records = statements_to_records(statements)

    seen = {}
    for rec in records:
        key = (rec["account_name"], rec["year"], rec["statement_type"])
        seen[key] = rec

    for rec in seen.values():
        db.add(
            FinancialData(
                company_id=company.id,
                account_name=rec["account_name"],
                xbrl_tag=None,
                year=rec["year"],
                amount=rec["amount"],
                statement_type=rec["statement_type"],
                join_key=f"{rec['account_name']}_{rec['year']}",
                source_api="edgartools",
            )
        )

    await db.commit()
    await db.refresh(company)
    logger.info(
        f"EdgarTools: loaded {len(seen)} standardized facts for {ticker} "
        f"({len(statements)} statements)"
    )
    return company
