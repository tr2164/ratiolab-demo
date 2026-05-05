from __future__ import annotations
from pydantic import BaseModel


class CompanyInfo(BaseModel):
    name: str
    ticker: str
    cik: str
    form: str
    filing_date: str


class LineItem(BaseModel):
    concept: str
    label: str
    category: str  # "balance_sheet", "income_statement", "cash_flow", "other"
    unit: str
    years_available: int
    latest_value: float | None = None
    is_instant: bool = True


class LineItemCatalog(BaseModel):
    company: CompanyInfo
    items: list[LineItem]
    category_counts: dict[str, int]


class SelectedItemsRequest(BaseModel):
    concepts: list[str]


class LineItemData(BaseModel):
    concept: str
    label: str
    values: dict[int, float]


class LineItemDataResponse(BaseModel):
    company_name: str
    ticker: str
    items: list[LineItemData]


class FootnoteBlock(BaseModel):
    xbrl_concept: str
    html: str
    text: str
    period: str = ""
    fiscal_year: int | None = None
    matched_keyword: str = ""


class FootnoteRequest(BaseModel):
    concepts: list[str]


class FootnoteResponse(BaseModel):
    company_name: str
    ticker: str
    blocks: list[FootnoteBlock]


class RatioTerm(BaseModel):
    concept: str
    sign: str = "+"  # "+" or "-"


class RatioDefinition(BaseModel):
    name: str
    numerator_terms: list[RatioTerm]
    denominator_terms: list[RatioTerm]
    multiply_by: float = 1.0  # 1 for ratio, 100 for %, 365 for days


class RatioResult(BaseModel):
    name: str
    definition: RatioDefinition
    values: dict[int, float | None]
    trend: str = ""  # "up", "down", "stable", ""


class RatioRequest(BaseModel):
    ratios: list[RatioDefinition]


class RatioResponse(BaseModel):
    company_name: str
    ticker: str
    results: list[RatioResult]


class Observation(BaseModel):
    title: str
    insight: str
    follow_up: str


class RatioAnalysis(BaseModel):
    ratio_highlights: list[str] = []
    observations: list[Observation] = []
    summary: str = ""
