"""
Async database engine and session management (SQLAlchemy 2 + asyncpg).

Falls back gracefully if DATABASE_URL is not set — the app runs with
in-memory caching only (fine for solo local development).
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

logger = logging.getLogger(__name__)

DATABASE_URL = get_settings().database_url

engine = None
async_session: async_sessionmaker[AsyncSession] | None = None


class Base(DeclarativeBase):
    pass


def _init_engine() -> None:
    global engine, async_session
    if not DATABASE_URL:
        logger.info("DATABASE_URL not set — running without database")
        return
    try:
        engine = create_async_engine(DATABASE_URL, echo=False, pool_size=5, max_overflow=10)
        async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        logger.info("Async database engine created: %s", DATABASE_URL.split("@")[-1])
    except Exception:
        logger.exception("Failed to create database engine — running without database")
        engine = None
        async_session = None


async def init_db() -> None:
    """Create tables and enable pgvector. Called once at app startup."""
    if engine is None:
        return
    try:
        import app.models  # noqa: F401 — register all models with Base.metadata

        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created")
    except Exception:
        logger.exception("Failed to initialize database tables")


async def get_db():
    """FastAPI dependency — yields an AsyncSession."""
    if async_session is None:
        raise RuntimeError("Database not configured")
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_session() -> AsyncSession | None:
    """Return a new async session, or None if no database is configured."""
    if async_session is None:
        return None
    return async_session()


_init_engine()
