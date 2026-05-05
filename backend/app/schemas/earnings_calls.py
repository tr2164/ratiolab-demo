from __future__ import annotations
from pydantic import BaseModel


class TranscriptFile(BaseModel):
    """Metadata about a parsed transcript file."""
    filename: str
    ticker: str
    quarter: str           # "Q4"
    fiscal_year: int       # 2025
    call_date: str         # "2026-02-10"
    doc_type: str          # "EarningsCall" | "EarningsRelease" | "NonGAAP" | "MarginSchedule"
    word_count: int
    page_count: int


class TranscriptSection(BaseModel):
    """A parsed speaker section from the transcript."""
    section_type: str      # "prepared_remarks" | "qa"
    speaker: str
    role: str              # "management" | "analyst" | "operator"
    text: str
    word_count: int


class ParsedTranscript(BaseModel):
    """Full parsed transcript with sections."""
    meta: TranscriptFile
    sections: list[TranscriptSection]
    full_text: str
    management_speakers: list[str]
    analyst_count: int
    prepared_word_count: int
    qa_word_count: int


class KeywordHit(BaseModel):
    keyword: str
    category: str          # "growth" | "risk" | "margin" | "guidance" | "capital" | "hedging"
    count: int
    sentiment: str         # "positive" | "negative" | "neutral"


class TopicBreakdown(BaseModel):
    topic: str
    pct: float
    sample_quote: str


class SentimentAnalysis(BaseModel):
    """LLM-generated sentiment and NLP analysis of a transcript."""
    overall_label: str           # "Bullish" | "Cautiously Optimistic" | "Neutral" | "Cautious" | "Bearish"
    overall_score: float         # 0–100, higher = more bullish
    management_confidence: float # 0–100
    hedge_density: float         # hedging phrases per 100 words (computed)
    key_quotes: list[str]
    guidance_statements: list[str]
    top_topics: list[TopicBreakdown]
    tone_narrative: str          # AI narrative paragraph
    keywords: list[KeywordHit]
    hedge_words_found: list[str]


class FinancialKPI(BaseModel):
    """A single financial metric for the comparison layer."""
    label: str
    value: float | None
    period: str
    unit: str              # "B" | "M" | "%" | "$/share"
    yoy_change: float | None = None


class ManagementSignal(BaseModel):
    """A pairing of what management said vs what actually happened."""
    topic: str
    what_was_said: str
    actual_result: str
    alignment: str         # "beat" | "miss" | "in_line" | "n/a"


class ComparisonAnalysis(BaseModel):
    """Layer 3: management language vs actual financial performance."""
    transcript_quarter: str      # "Q4 2025"
    financial_kpis: list[FinancialKPI]
    management_signals: list[ManagementSignal]
    beat_miss_summary: str
    ai_comparison: str
    data_source: str             # "SEC EDGAR XBRL" | "Earnings Release PDF"


class Observation(BaseModel):
    title: str
    insight: str
    follow_up: str


class EarningsCallAnalysis(BaseModel):
    """Full analysis result for a single earnings call."""
    meta: TranscriptFile
    sentiment: SentimentAnalysis
    comparison: ComparisonAnalysis | None = None
    ai_summary: str
    observations: list[Observation]


class TranscriptListResponse(BaseModel):
    """Response for listing available transcripts."""
    ticker: str
    transcripts: list[TranscriptFile]
    releases: list[TranscriptFile]
    other: list[TranscriptFile]


class ChatMessage(BaseModel):
    role: str   # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    transcript_filename: str | None = None
