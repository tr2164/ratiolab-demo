from __future__ import annotations
from pydantic import BaseModel


class XBRLValue(BaseModel):
    """A numeric value with its XBRL provenance attached."""
    xbrl_concept: str
    values: dict[int, float]  # {fiscal_year: amount}


class UsefulLife(BaseModel):
    asset_type: str
    xbrl_member: str
    xbrl_concept: str
    useful_life_min: float | None = None
    useful_life_max: float | None = None
    useful_life_raw_min: str | None = None
    useful_life_raw_max: str | None = None


class DisclosureBlock(BaseModel):
    xbrl_concept: str
    html: str
    text: str
    period: str = ""
    fiscal_year: int | None = None


class CompanyInfo(BaseModel):
    name: str
    ticker: str
    cik: str
    form: str
    filing_date: str


class PPESegment(BaseModel):
    segment_label: str
    xbrl_member: str
    xbrl_concept: str
    dimension_axis: str
    values: dict[int, float]


class PPEResponse(BaseModel):
    company: CompanyInfo
    totals: dict[str, XBRLValue]
    useful_lives: list[UsefulLife]
    disclosure_blocks: list[DisclosureBlock]
    historical: dict[str, dict[int, float]]  # {concept_label: {year: value}}
    segments: list[PPESegment] = []


class PPEOverrideRequest(BaseModel):
    """Allow the user to override an XBRL concept mapping."""
    field: str                # e.g. "totals.gross"
    xbrl_concept: str         # the replacement concept


class Observation(BaseModel):
    title: str
    insight: str
    follow_up: str


class DisclosureAnalysis(BaseModel):
    depreciation_method: str = ""
    capitalization_policy: str = ""
    policy_highlights: list[str] = []
    asset_age_pct: float | None = None
    observations: list[Observation] = []
    summary: str = ""


class PeerSummary(BaseModel):
    company: CompanyInfo
    gross: float | None = None
    accumulated_depreciation: float | None = None
    net: float | None = None
    asset_age_pct: float | None = None
    avg_useful_life: float | None = None
    useful_life_range: list[float | None] = []
    yoy_net_growth: float | None = None
    depreciation_method: str = ""
    error: str | None = None


class CompareRequest(BaseModel):
    tickers: list[str]


class CompareResponse(BaseModel):
    peers: list[PeerSummary]
