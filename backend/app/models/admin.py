"""
Admin models for centralized management of prompts, config, and parameters.
Adapted from RCSA's prompt versioning and model settings patterns.
"""
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text, JSON, func
from sqlalchemy.orm import relationship
from app.db import Base


class Prompt(Base):
    """Versioned prompt templates for all LLM interactions."""
    __tablename__ = "prompts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)
    category = Column(String(100), nullable=False)  # mapping, sentiment, agent, projection
    description = Column(Text)
    prompt_text = Column(Text, nullable=False)
    variables = Column(JSON, default=list)
    is_active = Column(Boolean, default=True)
    version = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    versions = relationship("PromptVersion", back_populates="prompt", cascade="all, delete-orphan")


class PromptVersion(Base):
    """Audit trail for prompt changes."""
    __tablename__ = "prompt_versions"

    id = Column(Integer, primary_key=True, index=True)
    prompt_id = Column(Integer, ForeignKey("prompts.id"), nullable=False)
    version = Column(Integer, nullable=False)
    prompt_text = Column(Text, nullable=False)
    variables = Column(JSON, default=list)
    is_active = Column(Boolean, default=False)
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    prompt = relationship("Prompt", back_populates="versions")


class ModelConfig(Base):
    """
    Centralized configuration for model-building parameters.
    Admins can adjust projection years, driver definitions, formula methods, etc.
    """
    __tablename__ = "model_configs"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(255), unique=True, nullable=False)
    value = Column(JSON, nullable=False)
    description = Column(Text)
    category = Column(String(100))  # projection, driver, formula, general
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
