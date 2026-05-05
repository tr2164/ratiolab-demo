from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Dict, Any, List


class ModelCreate(BaseModel):
    ticker: str
    projection_years: int = 5


class DCFModelCreate(BaseModel):
    ticker: str
    projection_years: int = 5
    source_model_id: Optional[int] = None


class ModelResponse(BaseModel):
    id: int
    company_id: int
    name: Optional[str]
    status: str
    projection_years: int
    template_version: Optional[str] = "v2"
    created_at: datetime

    class Config:
        from_attributes = True


class DriverResponse(BaseModel):
    driver_name: str
    year: int
    value: Optional[float]
    is_projected: bool
    is_overridden: bool
    formula_method: Optional[str]

    class Config:
        from_attributes = True


class LineItemResponse(BaseModel):
    model_line: str
    statement_type: str
    year: int
    amount: Optional[float]
    is_projected: bool
    sort_order: int

    class Config:
        from_attributes = True


class AssumptionResponse(BaseModel):
    id: int
    name: str
    statement_type: str
    base_value: float
    step_increment: float
    step_type: str
    is_overridden: bool
    category: Optional[str] = "General"
    input_type: Optional[str] = "percentage"
    display_name: Optional[str] = None
    description: Optional[str] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None

    class Config:
        from_attributes = True


class AssumptionUpdate(BaseModel):
    name: str
    base_value: Optional[float] = None
    step_increment: Optional[float] = None


class AssumptionBulkUpdate(BaseModel):
    updates: List[AssumptionUpdate]


class SensitivityRequest(BaseModel):
    row_variable: str
    col_variable: str
    output_metric: str
    row_increments: List[float]
    col_increments: List[float]


class MappingInfo(BaseModel):
    raw_account_name: str
    xbrl_tag: Optional[str] = None
    sign_flip: int = 1
    mapping_method: Optional[str] = None
    confidence: Optional[float] = None


class FullModelResponse(BaseModel):
    model: ModelResponse
    line_items: List[LineItemResponse]
    drivers: List[DriverResponse]
    assumptions: List[AssumptionResponse] = []
    company: dict
    mappings: Optional[Dict[str, MappingInfo]] = None


class DriverUpdate(BaseModel):
    driver_name: str
    year: int
    value: float
    source: str = "manual"


class ScenarioCreate(BaseModel):
    name: str
    driver_overrides: Dict[str, float]


class ScenarioResponse(BaseModel):
    id: int
    model_id: int
    name: str
    driver_overrides: Dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


class AgentMessage(BaseModel):
    message: str
    model_id: int
    spreadsheet_context: Optional[str] = None


class AgentResponse(BaseModel):
    reply: str
    suggestions: List[dict] = []
    sources: List[Any] = []
    analysis_type: Optional[str] = None


class ValidatorMessage(BaseModel):
    message: str
    model_id: int
    history: List[dict] = []
    llm_model: Optional[str] = None


class ValidatorResponse(BaseModel):
    reply: str
    sources: List[Any] = []
