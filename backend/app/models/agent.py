from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, JSON, Text, func
from sqlalchemy.orm import relationship
from app.db import Base


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id = Column(Integer, primary_key=True, index=True)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False)
    messages = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    suggestions = relationship("AgentSuggestion", back_populates="session", cascade="all, delete-orphan")


class AgentSuggestion(Base):
    __tablename__ = "agent_suggestions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("agent_sessions.id"), nullable=False)
    driver_name = Column(String(255))
    current_value = Column(Float)
    suggested_value = Column(Float)
    rationale = Column(Text)
    news_sources = Column(JSON)
    accepted = Column(Boolean)

    session = relationship("AgentSession", back_populates="suggestions")
