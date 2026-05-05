"""Company ticker search — loads SEC company_tickers.json for autocomplete."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/tickers", tags=["tickers"])


@lru_cache(maxsize=1)
def _load_tickers() -> list[dict]:
    candidates = [
        Path(__file__).resolve().parents[3] / "company_tickers.json",
        Path(__file__).resolve().parents[2] / "company_tickers.json",
    ]
    for path in candidates:
        if path.exists():
            with open(path) as f:
                raw = json.load(f)
            return [
                {"cik": e.get("cik_str"), "ticker": e.get("ticker", ""), "title": e.get("title", "")}
                for e in raw.values()
            ]
    return []


@router.get("/search")
def search_tickers(q: str = Query("", min_length=1), limit: int = Query(15, le=30)):
    query = q.upper().strip()
    entries = _load_tickers()
    results = []
    for e in entries:
        ticker_match = query in e["ticker"].upper()
        title_match = query in e["title"].upper()
        if ticker_match or title_match:
            results.append(e)
            if len(results) >= limit:
                break
    return results
