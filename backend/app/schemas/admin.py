"""
Admin schemas for prompt management and model configuration.
Adapted from RCSA's prompt/model-settings patterns.
"""
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Any, List


# --- Prompt Management ---

class PromptBase(BaseModel):
    name: str
    category: str  # mapping, sentiment, agent, projection
    description: Optional[str] = None
    prompt_text: str
    variables: List[str] = []


class PromptCreate(PromptBase):
    pass


class PromptUpdate(BaseModel):
    prompt_text: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    variables: Optional[List[str]] = None


class PromptResponse(PromptBase):
    id: int
    version: int
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PromptRenderRequest(BaseModel):
    name: str
    variables: dict = {}


class PromptRenderResponse(BaseModel):
    rendered: str
    name: str
    version: int


# --- Model Configuration ---

class ModelConfigBase(BaseModel):
    key: str
    value: Any
    description: Optional[str] = None
    category: Optional[str] = None


class ModelConfigCreate(ModelConfigBase):
    pass


class ModelConfigUpdate(BaseModel):
    value: Any
    description: Optional[str] = None


class ModelConfigResponse(ModelConfigBase):
    id: int
    updated_at: datetime

    class Config:
        from_attributes = True


# --- Driver Definitions (managed via ModelConfig) ---

class DriverDefinition(BaseModel):
    driver_name: str
    numerator_line: str
    denominator_line: str
    driver_type: str  # pct_of, days, growth
    is_active: bool = True


class ProjectionDefaults(BaseModel):
    projection_years: int = 4
    formula_method: str = "trailing_3yr_avg"  # trailing_3yr_avg, manual, regression
    driver_definitions: List[DriverDefinition] = []
