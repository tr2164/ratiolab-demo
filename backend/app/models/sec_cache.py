"""Cached SEC API responses with a configurable TTL (default 7 days)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

CACHE_TTL_DAYS = 7


class SecResponseCache(Base):
    __tablename__ = "sec_response_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cache_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    response_body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_sec_cache_key", "cache_key"),
        Index("ix_sec_cache_created", "created_at"),
    )

    @property
    def is_expired(self) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(days=CACHE_TTL_DAYS)
        created = self.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return created < cutoff
