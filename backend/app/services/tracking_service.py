"""
Lightweight event tracking for module activity.

Called from routers to log student actions. All writes are best-effort;
tracking failures never break the main request.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.db import get_session
from app.models.tracking import ModuleSession, ModuleEvent

logger = logging.getLogger(__name__)


async def start_module_session(
    user_id: int,
    module: str,
    ticker: Optional[str] = None,
    course_id: Optional[str] = None,
) -> Optional[int]:
    """Create a new module session row. Returns session ID or None."""
    db = await get_session()
    if db is None:
        return None
    try:
        async with db:
            session = ModuleSession(
                user_id=user_id,
                module=module,
                ticker=ticker,
                course_id=course_id,
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)
            return session.id
    except Exception:
        logger.warning("Failed to start module session", exc_info=True)
        return None


async def log_event(
    session_id: Optional[int],
    event_type: str,
    event_data: Optional[dict] = None,
) -> None:
    """Log a module event. Silently fails if DB is unavailable."""
    if session_id is None:
        return
    db = await get_session()
    if db is None:
        return
    try:
        async with db:
            event = ModuleEvent(
                session_id=session_id,
                event_type=event_type,
                event_data=event_data or {},
            )
            db.add(event)
            await db.commit()
    except Exception:
        logger.warning("Failed to log event %s", event_type, exc_info=True)


async def log_event_simple(
    user_id: int,
    module: str,
    event_type: str,
    event_data: Optional[dict] = None,
    course_id: Optional[str] = None,
) -> None:
    """
    Convenience: create a session (if needed) and log an event in one call.
    Used when the router doesn't maintain session state across requests.
    """
    session_id = await start_module_session(
        user_id=user_id,
        module=module,
        ticker=event_data.get("ticker") if event_data else None,
        course_id=course_id,
    )
    await log_event(session_id, event_type, event_data)
