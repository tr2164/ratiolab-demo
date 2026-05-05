"""
SEC API response cache backed by Postgres (sync engine).

Uses a separate sync connection (psycopg2) since this is called from
synchronous SEC data functions (edgartools, requests). The async engine
in db.py is used by finmodel's async routers.

Falls back to in-memory dict if no database is available.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models.sec_cache import CACHE_TTL_DAYS, SecResponseCache

logger = logging.getLogger(__name__)

_memory_cache: dict[str, tuple[datetime, Any]] = {}

_sync_engine = None
_SyncSession: sessionmaker[Session] | None = None

try:
    _settings = get_settings()
    if _settings.sync_database_url:
        _sync_engine = create_engine(
            _settings.sync_database_url,
            pool_pre_ping=True,
            pool_size=3,
            max_overflow=5,
        )
        _SyncSession = sessionmaker(bind=_sync_engine)
except Exception:
    logger.exception("Failed to create sync cache engine")


def _cache_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def cached_get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> Any:
    """
    GET a JSON endpoint with 7-day database caching.
    Sync interface — safe to call from sync code (sec_data.py).
    """
    key = _cache_key(url)

    # --- Try database ---
    if _SyncSession is not None:
        try:
            with _SyncSession() as session:
                row = session.execute(
                    select(SecResponseCache).where(SecResponseCache.cache_key == key)
                ).scalar_one_or_none()
                if row and not row.is_expired:
                    logger.debug("DB cache hit: %s", url[:120])
                    return json.loads(row.response_body)
        except Exception:
            logger.exception("DB cache read failed")

    # --- Check memory fallback ---
    if key in _memory_cache:
        cached_at, data = _memory_cache[key]
        cutoff = datetime.now(timezone.utc) - timedelta(days=CACHE_TTL_DAYS)
        if cached_at > cutoff:
            logger.debug("Memory cache hit: %s", url[:120])
            return data

    # --- Fetch from SEC ---
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    # --- Store ---
    if _SyncSession is not None:
        try:
            with _SyncSession() as session:
                existing = session.execute(
                    select(SecResponseCache).where(SecResponseCache.cache_key == key)
                ).scalar_one_or_none()
                body = json.dumps(data)
                if existing:
                    existing.response_body = body
                    existing.created_at = datetime.now(timezone.utc)
                else:
                    session.add(SecResponseCache(
                        cache_key=key,
                        url=url[:1024],
                        response_body=body,
                    ))
                session.commit()
                logger.debug("DB cache stored: %s", url[:120])
        except Exception:
            logger.exception("DB cache write failed")
            _memory_cache[key] = (datetime.now(timezone.utc), data)
    else:
        _memory_cache[key] = (datetime.now(timezone.utc), data)

    return data
