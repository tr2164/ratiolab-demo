from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import relationship
from app.db import Base


class Model(Base):
    __tablename__ = "models"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    name = Column(String(255))
    status = Column(String(50), default="building")  # building, ready, error
    projection_years = Column(Integer, default=5)
    template_version = Column(String(20), default="v2")  # v1 = old 3-stmt, v2 = 6-tab
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    company = relationship("Company", back_populates="models")
    line_items = relationship("ModelLineItem", back_populates="model", cascade="all, delete-orphan")
    drivers = relationship("Driver", back_populates="model", cascade="all, delete-orphan")
    assumptions = relationship("ModelAssumption", back_populates="model", cascade="all, delete-orphan")
    formulas = relationship("ProjectionFormula", back_populates="model", cascade="all, delete-orphan")
    scenarios = relationship("Scenario", back_populates="model", cascade="all, delete-orphan")


class ModelLineItem(Base):
    __tablename__ = "model_line_items"

    id = Column(Integer, primary_key=True, index=True)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False)
    model_line = Column(String(255), nullable=False)
    statement_type = Column(String(10), nullable=False)  # IS, BS, SCF, WC, PPE, DEBT, INFO
    year = Column(Integer, nullable=False)
    amount = Column(Float)
    is_projected = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)

    model = relationship("Model", back_populates="line_items")


class Driver(Base):
    __tablename__ = "drivers"

    id = Column(Integer, primary_key=True, index=True)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False)
    driver_name = Column(String(255), nullable=False)
    year = Column(Integer, nullable=False)
    value = Column(Float)
    formula_method = Column(String(100))
    is_projected = Column(Boolean, default=False)
    is_overridden = Column(Boolean, default=False)
    override_source = Column(String(255))

    model = relationship("Model", back_populates="drivers")


class ModelAssumption(Base):
    """Step-function assumption for the 6-tab model.
    Each assumption has a base value and a per-period step increment,
    plus metadata for the Assumptions Panel UI.
    """
    __tablename__ = "model_assumptions"

    id = Column(Integer, primary_key=True, index=True)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False)
    name = Column(String(255), nullable=False)
    statement_type = Column(String(10), nullable=False)
    base_value = Column(Float, nullable=False)
    step_increment = Column(Float, default=0.0)
    step_type = Column(String(20), default="additive")
    is_overridden = Column(Boolean, default=False)
    category = Column(String(50), default="General")
    input_type = Column(String(20), default="percentage")
    display_name = Column(String(255))
    description = Column(String(500))
    min_value = Column(Float)
    max_value = Column(Float)

    model = relationship("Model", back_populates="assumptions")


class ProjectionFormula(Base):
    __tablename__ = "projection_formulas"

    id = Column(Integer, primary_key=True, index=True)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False)
    model_line = Column(String(255), nullable=False)
    formula_template = Column(String(1000))
    driver_refs = Column(JSON)

    model = relationship("Model", back_populates="formulas")


class ModelType(Base):
    __tablename__ = "model_types"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(String(500))
    icon = Column(String(50), default="FileSpreadsheet")
    is_active = Column(Boolean, default=False)
    is_coming_soon = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
