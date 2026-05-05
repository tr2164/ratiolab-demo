from sqlalchemy import Column, Integer, String, DateTime, JSON, func, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base


class ModuleSession(Base):
    __tablename__ = "module_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    course_id = Column(String(255), nullable=True, index=True)
    module = Column(String(50), nullable=False)
    ticker = Column(String(20), nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="module_sessions")
    events = relationship("ModuleEvent", back_populates="session", cascade="all, delete-orphan")
    checkpoint_responses = relationship("CheckpointResponse", back_populates="session", cascade="all, delete-orphan")


class ModuleEvent(Base):
    __tablename__ = "module_events"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("module_sessions.id"), nullable=False, index=True)
    event_type = Column(String(50), nullable=False)
    event_data = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("ModuleSession", back_populates="events")
