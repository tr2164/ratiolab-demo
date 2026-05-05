"""
Session-based auth middleware for FinSight.

In production (LTI mode), the session token comes from the LTI launch flow
and is passed via the X-Session-Token header.

In dev mode (DEV_USER_MODE=true), a synthetic user and session are created
automatically so all features work without LTI.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db, get_session

logger = logging.getLogger(__name__)


@dataclass
class SessionContext:
    """Injected into route handlers via Depends(get_current_user)."""
    user_id: int
    display_name: str
    email: Optional[str]
    role: str
    course_id: Optional[str]
    course_title: Optional[str]
    session_id: Optional[str]


_dev_user_id: Optional[int] = None
_dev_session_id: Optional[str] = None


async def _ensure_dev_user(db: AsyncSession) -> tuple[int, str]:
    """Create or retrieve the dev user and session. Cached after first call."""
    global _dev_user_id, _dev_session_id
    if _dev_user_id is not None and _dev_session_id is not None:
        return _dev_user_id, _dev_session_id

    from app.models.user import User, LTISession

    settings = get_settings()
    result = await db.execute(
        select(User).where(User.display_name == settings.dev_user_name, User.is_demo == True)
    )
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            display_name=settings.dev_user_name,
            email="demo@finsight.local",
            is_demo=True,
        )
        db.add(user)
        await db.flush()

    session_id = secrets.token_urlsafe(32)
    lti_session = LTISession(
        id=session_id,
        user_id=user.id,
        course_id=settings.dev_course_id,
        course_title=settings.dev_course_title,
        role=settings.dev_user_role,
        expires_at=datetime.now(timezone.utc) + timedelta(days=365),
    )
    db.add(lti_session)
    await db.commit()

    _dev_user_id = user.id
    _dev_session_id = session_id
    logger.info("Dev user created: %s (id=%d, session=%s)", user.display_name, user.id, session_id)
    return user.id, session_id


async def get_current_user(request: Request) -> SessionContext:
    """
    FastAPI dependency that resolves the current user from the session token.

    Checks X-Session-Token header first, then falls back to dev user mode.
    Returns a SessionContext dataclass with user identity and course context.
    """
    settings = get_settings()

    token = request.headers.get("X-Session-Token")

    db_session = await get_session()
    if db_session is None:
        if settings.dev_user_mode:
            return SessionContext(
                user_id=0,
                display_name=settings.dev_user_name,
                email="demo@finsight.local",
                role=settings.dev_user_role,
                course_id=settings.dev_course_id,
                course_title=settings.dev_course_title,
                session_id=None,
            )
        raise HTTPException(status_code=503, detail="Database not configured")

    async with db_session:
        if token:
            from app.models.user import LTISession, User
            result = await db_session.execute(
                select(LTISession).where(LTISession.id == token)
            )
            lti_session = result.scalar_one_or_none()

            if lti_session is None:
                raise HTTPException(status_code=401, detail="Invalid session token")

            if lti_session.expires_at < datetime.now(timezone.utc):
                raise HTTPException(status_code=401, detail="Session expired")

            user_result = await db_session.execute(
                select(User).where(User.id == lti_session.user_id)
            )
            user = user_result.scalar_one_or_none()
            if user is None:
                raise HTTPException(status_code=401, detail="User not found")

            user.last_seen_at = datetime.now(timezone.utc)
            await db_session.commit()

            return SessionContext(
                user_id=user.id,
                display_name=user.display_name,
                email=user.email,
                role=lti_session.role,
                course_id=lti_session.course_id,
                course_title=lti_session.course_title,
                session_id=lti_session.id,
            )

        if settings.dev_user_mode:
            user_id, session_id = await _ensure_dev_user(db_session)
            return SessionContext(
                user_id=user_id,
                display_name=settings.dev_user_name,
                email="demo@finsight.local",
                role=settings.dev_user_role,
                course_id=settings.dev_course_id,
                course_title=settings.dev_course_title,
                session_id=session_id,
            )

        raise HTTPException(status_code=401, detail="Authentication required")


async def get_optional_user(request: Request) -> Optional[SessionContext]:
    """Like get_current_user but returns None instead of raising 401."""
    try:
        return await get_current_user(request)
    except HTTPException:
        return None


def require_role(*allowed_roles: str):
    """Factory for role-checking dependencies."""
    async def _check(ctx: SessionContext = Depends(get_current_user)) -> SessionContext:
        if ctx.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{ctx.role}' not authorized. Required: {', '.join(allowed_roles)}",
            )
        return ctx
    return _check
