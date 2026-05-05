from __future__ import annotations
from pydantic import BaseModel


class XBRLValue(BaseModel):
    """A numeric value with its XBRL provenance attached."""
    xbrl_concept: str
    values: dict[int, float]  # {fiscal_year: amount}


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


class ReceivableSegment(BaseModel):
    segment_label: str
    xbrl_member: str
    xbrl_concept: str
    dimension_axis: str
    values: dict[int, float]  # {fiscal_year: amount}


class AllowanceResponse(BaseModel):
    company: CompanyInfo
    totals: dict[str, XBRLValue]  # ar_net, allowance, gross_ar, revenue, total_assets
    computed: dict[str, dict[int, float | None]]  # allowance_ratio, bad_debt_ratio, dso
    disclosure_blocks: list[DisclosureBlock]
    historical: dict[str, dict[int, float]]  # {label: {year: value}}
    rollforward: dict[str, dict[int, float]] | None = None  # provision, write_offs, recoveries
    receivable_segments: list[ReceivableSegment] = []


class Observation(BaseModel):
    title: str
    insight: str
    follow_up: str


class AllowanceAnalysis(BaseModel):
    allowance_methodology: str = ""
    risk_factors: str = ""
    policy_highlights: list[str] = []
    allowance_ratio_pct: float | None = None
    observations: list[Observation] = []
    summary: str = ""


class ForensicFlag(BaseModel):
    severity: str  # red, yellow, green
    flag: str
    detail: str
    year: int | None = None


class ForensicResult(BaseModel):
    flags: list[ForensicFlag] = []
    summary: str = ""


class SensitivityResult(BaseModel):
    gross_ar: float
    current_allowance: float
    current_ratio: float
    scenario_ratio: float
    scenario_allowance: float
    bad_debt_expense_change: float
    pre_tax_income_impact: float
    after_tax_income_impact: float


class PeerSegmentSummary(BaseModel):
    """Lightweight segment info for a single peer in the comparables view."""
    segment_label: str
    xbrl_member: str
    latest_value: float | None = None
    pct_of_total: float | None = None


class PeerSummary(BaseModel):
    company: CompanyInfo
    ar_net: float | None = None
    allowance: float | None = None
    gross_ar: float | None = None
    allowance_ratio: float | None = None
    bad_debt_expense: float | None = None
    revenue: float | None = None
    bad_debt_to_revenue: float | None = None
    dso: float | None = None
    yoy_ratio_change: float | None = None
    segments: list[PeerSegmentSummary] = []
    dominant_segment: str | None = None
    dominant_segment_ar: float | None = None
    dominant_segment_ratio: float | None = None
    error: str | None = None


class CompareRequest(BaseModel):
    tickers: list[str]


class CompareResponse(BaseModel):
    peers: list[PeerSummary]
