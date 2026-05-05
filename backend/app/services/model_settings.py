"""
Model Settings Service: Centralized configuration for 6-tab model parameters.

Manages:
- Default projection config (years, historical periods)
- Assumption definitions (step functions for each driver)
- LLM model selection
- DB-backed config overrides
"""
import os
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.admin import ModelConfig

logger = logging.getLogger(__name__)


def _parse_allowlist(value: Optional[str], fallback: List[str]) -> List[str]:
    if value:
        items = [item.strip() for item in value.split(",") if item.strip()]
        if items:
            return items
    return fallback


DEFAULT_LLM_ALLOWLIST = [
    "openai.gpt-5.2",
    "azure.gpt-4.1",
    "azure.gpt-4.1-mini",
    "claude-sonnet-4-20250514",
]

ALLOWED_LLM_MODELS = _parse_allowlist(
    os.getenv("LLM_MODEL_ALLOWLIST"),
    DEFAULT_LLM_ALLOWLIST,
)

DEFAULT_LLM_MODEL = os.getenv("DEFAULT_LLM_MODEL", ALLOWED_LLM_MODELS[0] if ALLOWED_LLM_MODELS else "")


# ─── Projection Config ────────────────────────────────────────────────────

DEFAULT_PROJECTION_CONFIG = {
    "projection_years": 5,
    "historical_periods": 3,
}


# ─── Assumption Definitions ───────────────────────────────────────────────
# These define the step-function assumptions for the 6-tab model.
# Each assumption has a base value, step increment, and type.

DEFAULT_ASSUMPTION_DEFINITIONS: List[Dict[str, Any]] = [
    # IS drivers
    {"name": "Unit Growth Rate",       "stmt": "IS",   "row": 7,  "base": 0.15,  "step": 0.0,   "type": "multiplicative", "is_active": True},
    {"name": "Price Growth Rate",      "stmt": "IS",   "row": 8,  "base": 0.02,  "step": 0.0,   "type": "multiplicative", "is_active": True},
    {"name": "R&D Growth Rate",        "stmt": "IS",   "row": 11, "base": 0.10,  "step": 0.0,   "type": "multiplicative", "is_active": True},
    {"name": "SG&A/Sales",             "stmt": "IS",   "row": 28, "base": 0.06,  "step": 0.0,   "type": "additive",       "is_active": True},
    {"name": "Other OpEx/Sales",       "stmt": "IS",   "row": 29, "base": 0.05,  "step": 0.0,   "type": "additive",       "is_active": True},
    {"name": "Tax Rate",               "stmt": "IS",   "row": 30, "base": 0.21,  "step": 0.0,   "type": "additive",       "is_active": True},
    # BS drivers
    {"name": "Cash/Sales",             "stmt": "BS",   "row": 31, "base": 0.10,  "step": 0.0,   "type": "additive",       "is_active": True},
    {"name": "DTL/Sales",              "stmt": "BS",   "row": 32, "base": 0.032, "step": 0.0,   "type": "additive",       "is_active": True},
    # PP&E drivers
    {"name": "Dep/CAPEX",              "stmt": "PPE",  "row": 17, "base": 0.60,  "step": 0.10,  "type": "additive",       "is_active": True},
    # WC drivers
    {"name": "DSO",                    "stmt": "WC",   "row": 52, "base": 45.0,  "step": 0.0,   "type": "additive",       "is_active": True},
    {"name": "DPO",                    "stmt": "WC",   "row": 51, "base": 90.0,  "step": 0.0,   "type": "additive",       "is_active": True},
    {"name": "Allowance/Gross AR",     "stmt": "WC",   "row": 53, "base": 0.20,  "step": 0.0,   "type": "additive",       "is_active": True},
    {"name": "Write-offs/prev sales",  "stmt": "WC",   "row": 54, "base": 0.135, "step": 0.0,   "type": "additive",       "is_active": True},
    {"name": "Inventory Policy",       "stmt": "WC",   "row": 57, "base": 0.20,  "step": 0.0,   "type": "additive",       "is_active": True},
    {"name": "Deferred Rev/Sales",     "stmt": "WC",   "row": 58, "base": 0.12,  "step": 0.0,   "type": "additive",       "is_active": True},
    {"name": "Prepaid/SG&A",           "stmt": "WC",   "row": 59, "base": 0.04,  "step": 0.0,   "type": "additive",       "is_active": True},
    {"name": "Other Op Liab/Other OpEx","stmt": "WC",  "row": 60, "base": 0.028, "step": 0.0,   "type": "additive",       "is_active": True},
    {"name": "Accrued Tax/Tax Owe",    "stmt": "WC",   "row": 61, "base": 0.25,  "step": 0.0,   "type": "additive",       "is_active": True},
    {"name": "Purchase Price Growth",  "stmt": "WC",   "row": 37, "base": 0.02,  "step": 0.0,   "type": "multiplicative", "is_active": True},
    # Debt drivers
    {"name": "LTD Interest Rate",      "stmt": "DEBT", "row": 18, "base": 0.025, "step": 0.0,   "type": "additive",       "is_active": True},
    {"name": "Revolver Borrow Rate",   "stmt": "DEBT", "row": 22, "base": 0.053, "step": 0.0,   "type": "additive",       "is_active": True},
    {"name": "Revolver Invest Rate",   "stmt": "DEBT", "row": 23, "base": 0.028, "step": 0.0,   "type": "additive",       "is_active": True},
    {"name": "Cash Interest Rate",     "stmt": "DEBT", "row": 30, "base": 0.0089,"step": 0.0,   "type": "additive",       "is_active": True},
    # SCF drivers
    {"name": "Dividend Payout %",      "stmt": "SCF",  "row": 17, "base": 0.25,  "step": 0.0,   "type": "additive",       "is_active": True},
]


# ─── Backward-compat aliases ──────────────────────────────────────────────
# Old code may reference these; they now point to the assumption system

DEFAULT_DRIVER_DEFINITIONS = DEFAULT_ASSUMPTION_DEFINITIONS

DEFAULT_PROJECTION_FORMULAS: List[Dict[str, Any]] = []

DEFAULT_DRIVER_FORMULAS: List[Dict[str, Any]] = []


# ─── Public API ────────────────────────────────────────────────────────────

def get_model_options() -> Dict[str, Any]:
    """Return available model options for the admin UI."""
    return {
        "llm_models": ALLOWED_LLM_MODELS,
        "defaults": {
            "llm_model": DEFAULT_LLM_MODEL,
            "projection_years": DEFAULT_PROJECTION_CONFIG["projection_years"],
            "historical_periods": DEFAULT_PROJECTION_CONFIG["historical_periods"],
        },
        "assumption_count": len(DEFAULT_ASSUMPTION_DEFINITIONS),
    }


async def get_config(session: AsyncSession, key: str) -> Optional[Any]:
    """Get a config value from the database, falling back to defaults."""
    result = await session.execute(
        select(ModelConfig).where(ModelConfig.key == key)
    )
    config = result.scalar_one_or_none()
    if config:
        return config.value

    defaults = {
        "projection_years": DEFAULT_PROJECTION_CONFIG["projection_years"],
        "historical_periods": DEFAULT_PROJECTION_CONFIG["historical_periods"],
        "assumption_definitions": DEFAULT_ASSUMPTION_DEFINITIONS,
        "projection_formulas": DEFAULT_PROJECTION_FORMULAS,
        "driver_formulas": DEFAULT_DRIVER_FORMULAS,
        "driver_definitions": DEFAULT_DRIVER_DEFINITIONS,
    }
    return defaults.get(key)


async def set_config(session: AsyncSession, key: str, value: Any, description: str = "", category: str = "general") -> ModelConfig:
    """Set a config value in the database."""
    result = await session.execute(
        select(ModelConfig).where(ModelConfig.key == key)
    )
    config = result.scalar_one_or_none()
    if config:
        config.value = value
        if description:
            config.description = description
    else:
        config = ModelConfig(key=key, value=value, description=description, category=category)
        session.add(config)

    await session.commit()
    await session.refresh(config)
    return config


async def list_configs(session: AsyncSession, category: Optional[str] = None) -> List[ModelConfig]:
    """List all configs, optionally filtered by category."""
    stmt = select(ModelConfig)
    if category:
        stmt = stmt.where(ModelConfig.category == category)
    stmt = stmt.order_by(ModelConfig.key.asc())
    result = await session.execute(stmt)
    return list(result.scalars().all())
