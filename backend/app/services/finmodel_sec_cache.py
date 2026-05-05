"""
Cached SEC companyfacts fetcher.

Caches the full companyfacts JSON to disk for 24 hours to avoid
repeated SEC API calls. Both the mapping engine and the XBRL tag
search use this shared layer.
"""
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from app.config import get_settings, get_ssl_verify

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 86400  # 24 hours


def _cache_path(cik: str) -> Path:
    settings = get_settings()
    cache_dir = Path(settings.edgar_cache_dir) / "companyfacts"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"CIK{cik.zfill(10)}.json"


def _read_cache(cik: str) -> Optional[Dict[str, Any]]:
    path = _cache_path(cik)
    if not path.exists():
        return None
    age = time.time() - path.stat().st_mtime
    if age > CACHE_TTL_SECONDS:
        logger.info(f"CompanyFacts cache expired for CIK {cik} (age={age:.0f}s)")
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        logger.info(f"CompanyFacts cache hit for CIK {cik} (age={age:.0f}s)")
        return data
    except Exception as e:
        logger.warning(f"CompanyFacts cache read failed: {e}")
        return None


def _write_cache(cik: str, data: Dict[str, Any]) -> None:
    path = _cache_path(cik)
    try:
        with open(path, "w") as f:
            json.dump(data, f)
        logger.info(f"CompanyFacts cached for CIK {cik} at {path}")
    except Exception as e:
        logger.warning(f"CompanyFacts cache write failed: {e}")


async def get_companyfacts(cik: str) -> Optional[Dict[str, Any]]:
    """Fetch companyfacts JSON from SEC, with 24-hour disk cache."""
    cached = _read_cache(cik)
    if cached is not None:
        return cached

    settings = get_settings()
    cik_padded = cik.zfill(10)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"

    try:
        async with httpx.AsyncClient(verify=get_ssl_verify()) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": settings.sec_user_agent},
                timeout=30.0,
            )
            if resp.status_code != 200:
                logger.warning(f"SEC companyfacts returned {resp.status_code} for CIK {cik_padded}")
                return None
            data = resp.json()
    except Exception as e:
        logger.error(f"Failed to fetch companyfacts for CIK {cik_padded}: {e}")
        return None

    _write_cache(cik, data)
    return data
