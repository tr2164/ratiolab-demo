"""
Earnings Call analysis service.

Parses PDF transcripts from a local directory, runs keyword/sentiment analysis
via LLM, and fetches financial KPIs from SEC EDGAR for cross-referencing.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.llm_service import chat_json

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword dictionaries
# ---------------------------------------------------------------------------

KEYWORD_CATEGORIES: dict[str, list[tuple[str, str]]] = {
    "growth": [
        ("growth", "positive"), ("accelerat", "positive"), ("momentum", "positive"),
        ("record", "positive"), ("strong", "positive"), ("outperform", "positive"),
        ("expand", "positive"), ("gain", "positive"), ("increase", "positive"),
        ("higher", "positive"),
    ],
    "risk": [
        ("headwind", "negative"), ("challeng", "negative"), ("pressure", "negative"),
        ("uncertain", "negative"), ("difficult", "negative"), ("disappointing", "negative"),
        ("decline", "negative"), ("weakness", "negative"), ("concern", "negative"),
        ("volatil", "negative"),
    ],
    "margin": [
        ("margin", "neutral"), ("profitab", "positive"), ("efficiency", "positive"),
        ("cost", "neutral"), ("expense", "neutral"), ("pricing", "neutral"),
        ("leverage", "positive"), ("dilution", "negative"),
    ],
    "guidance": [
        ("outlook", "neutral"), ("guidance", "neutral"), ("forecast", "neutral"),
        ("target", "neutral"), ("expect", "neutral"), ("anticipat", "neutral"),
        ("going forward", "neutral"), ("full year", "neutral"),
    ],
    "capital": [
        ("capital", "neutral"), ("investment", "neutral"), ("acquisition", "neutral"),
        ("dividend", "positive"), ("buyback", "positive"), ("repurchase", "positive"),
        ("capex", "neutral"), ("free cash flow", "positive"),
    ],
    "hedging": [
        ("approximately", "neutral"), ("roughly", "neutral"), ("we believe", "neutral"),
        ("we expect", "neutral"), ("we think", "neutral"), ("could be", "neutral"),
        ("may be", "neutral"), ("potentially", "neutral"), ("subject to", "neutral"),
        ("cautious", "negative"), ("uncertain", "negative"), ("depend", "neutral"),
    ],
}


def _count_keywords(text: str) -> list[dict]:
    """Count keyword hits per category from raw text."""
    text_lower = text.lower()
    hits = []
    for category, terms in KEYWORD_CATEGORIES.items():
        for term, sentiment in terms:
            count = text_lower.count(term)
            if count > 0:
                hits.append({
                    "keyword": term,
                    "category": category,
                    "count": count,
                    "sentiment": sentiment,
                })
    return hits


def _hedge_density(text: str) -> float:
    """Hedging phrases per 100 words."""
    words = len(text.split())
    if words == 0:
        return 0.0
    hedge_terms = [t for t, _ in KEYWORD_CATEGORIES["hedging"]]
    total = sum(text.lower().count(t) for t in hedge_terms)
    return round((total / words) * 100, 2)


# ---------------------------------------------------------------------------
# PDF parsing
# ---------------------------------------------------------------------------

def _extract_pdf_text(path: Path) -> tuple[str, int]:
    """Return (full_text, page_count) from a PDF. Requires pypdf."""
    try:
        import pypdf  # type: ignore
        with open(path, "rb") as f:
            reader = pypdf.PdfReader(f)
            pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages), len(pages)
    except ImportError:
        logger.error("pypdf not installed — cannot parse PDF. Run: pip install pypdf")
        raise


def _extract_text_file(path: Path) -> tuple[str, int]:
    """Return (full_text, page_count=0) from a plain-text transcript file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text, 0


def _parse_filename(filename: str) -> dict[str, Any]:
    """
    Parse metadata from the naming convention:
      {TICKER}_{TYPE}_{QUARTER}_{YEAR}_{DATE}.pdf

    Example: KO_EarningsCall_Q4_2025_10-February-2026.pdf
    """
    stem = Path(filename).stem
    parts = stem.split("_")
    ticker = parts[0].upper() if parts else "UNKNOWN"
    year = 2025
    quarter = "Q4"
    doc_type = "Unknown"
    call_date = ""

    # Doc type: join middle tokens until we hit a Q\d pattern
    type_parts = []
    remaining = parts[1:]
    for i, p in enumerate(remaining):
        if re.match(r"^Q\d$", p):
            quarter = p
            year_parts = remaining[i + 1:]
            doc_type = "_".join(type_parts) if type_parts else "Unknown"
            # Extract year
            for yp in year_parts:
                if re.match(r"^\d{4}$", yp):
                    year = int(yp)
                    break
            # Date: last part after the year
            idx = year_parts.index(str(year)) + 1 if str(year) in year_parts else None
            if idx is not None and idx < len(year_parts):
                call_date = year_parts[idx]
            break
        type_parts.append(p)

    # Normalize doc type
    type_map = {
        "EarningsCall": "EarningsCall",
        "EarningsRelease": "EarningsRelease",
        "Margin_Analysis_Schedule": "MarginSchedule",
        "NonGAAP_Financial_Measures_EarningsCall": "NonGAAP_Call",
        "NonGAAP_Financial_Measures": "NonGAAP",
    }
    for key, val in type_map.items():
        if doc_type.startswith(key.split("_")[0]):
            if key.replace("_", "").lower() in doc_type.replace("_", "").lower():
                doc_type = val
                break

    return {
        "ticker": ticker,
        "quarter": quarter,
        "fiscal_year": year,
        "doc_type": doc_type,
        "call_date": call_date,
    }


# ---------------------------------------------------------------------------
# Transcript section parser  (handles FactSet CallStreet format)
# ---------------------------------------------------------------------------

# FactSet uses dotted separator lines like "....................  "
_SEPARATOR_RE = re.compile(r"^[\.\s]{20,}$")

# A name line: 2-4 words, mixed case, no colon, ≤50 chars
_NAME_RE = re.compile(r"^[A-Z][a-z]+(?:\s+[A-Za-z\-'\.]+){0,4}\s*$")

# FactSet title line keywords
_TITLE_KEYWORDS = (
    "vice president", "president", "chief", "officer", "ceo", "cfo", "coo", "director",
    "analyst", "managing", "head", "senior", "associate", "partner", "portfolio",
    "equity", "research", "investor relations",
)

# Operator instruction "Operator:" style
_OPERATOR_INLINE_RE = re.compile(r"^Operator\s*:\s*(.+)", re.DOTALL)

COMPANY_KEYWORDS = (
    "coca-cola", "the company", "ko", "coke",
)
ANALYST_FIRM_KEYWORDS = (
    "goldman", "morgan stanley", "jp morgan", "jpmorgan", "barclays", "citi",
    "ubs", "wells fargo", "raymond james", "bernstein", "credit suisse",
    "bank of america", "deutsche bank", "jefferies", "rbc", "evercore",
    "piper sandler", "cowen", "canaccord", "stifel",
)


def _is_title_line(line: str) -> bool:
    ll = line.lower()
    return any(kw in ll for kw in _TITLE_KEYWORDS)


def _classify_by_title(title_line: str, section_type: str) -> str:
    ll = title_line.lower()
    if any(kw in ll for kw in ANALYST_FIRM_KEYWORDS):
        return "analyst"
    if "analyst" in ll and section_type == "qa":
        return "analyst"
    if any(kw in ll for kw in ("operator", "moderator")):
        return "operator"
    return "management"


def _split_sections(text: str) -> tuple[list[dict], list[str], int]:
    """
    Split transcript into speaker sections.
    Handles FactSet CallStreet format (name on own line, title on next line, text follows).
    Also handles inline 'Operator: text' format.
    Returns (sections, management_speakers, analyst_count).
    """
    # Detect Q&A boundary — match the section header on its own line
    # (avoid matching inline references like "there will be a question-and-answer session")
    qa_boundary_re = re.compile(
        r"^\s*(?:QUESTION[\s&\-]+AND[\s&\-]+ANSWER\s+SECTION|Q\s*&\s*A\s+SECTION)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    qa_match = qa_boundary_re.search(text)
    qa_start_idx = qa_match.start() if qa_match else len(text)

    lines = text.split("\n")
    # Build cumulative character offsets for each line
    line_offsets: list[int] = []
    pos = 0
    for ln in lines:
        line_offsets.append(pos)
        pos += len(ln) + 1  # +1 for the \n

    sections: list[dict] = []

    # Walk lines, detect name→title→text blocks
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Skip section headers and separators
        if _SEPARATOR_RE.match(line) or not line:
            i += 1
            continue

        # Determine section type by actual character offset
        section_type = "qa" if line_offsets[i] >= qa_start_idx else "prepared_remarks"

        # Inline "Operator: text" format
        op_match = _OPERATOR_INLINE_RE.match(lines[i])
        if op_match:
            body_lines = [op_match.group(1).strip()]
            i += 1
            while i < len(lines):
                nl = lines[i].strip()
                if not nl or _SEPARATOR_RE.match(lines[i]):
                    i += 1
                    break
                if _NAME_RE.match(lines[i]) or _OPERATOR_INLINE_RE.match(lines[i]):
                    break
                body_lines.append(nl)
                i += 1
            body = " ".join(body_lines).strip()
            if body and len(body) > 20:
                sections.append({
                    "section_type": section_type,
                    "speaker": "Operator",
                    "role": "operator",
                    "text": body,
                    "word_count": len(body.split()),
                })
            continue

        # FactSet name+title+text block
        if _NAME_RE.match(lines[i]) and i + 1 < len(lines) and _is_title_line(lines[i + 1]):
            speaker_name = line
            title_line = lines[i + 1].strip()
            role = _classify_by_title(title_line, section_type)
            i += 2

            # Collect text until next separator, name, or operator line
            body_lines: list[str] = []
            while i < len(lines):
                nl = lines[i].strip()
                # Stop at separator
                if _SEPARATOR_RE.match(lines[i]):
                    i += 1
                    break
                # Stop at next speaker block
                if (
                    _NAME_RE.match(lines[i]) and
                    i + 1 < len(lines) and
                    _is_title_line(lines[i + 1])
                ):
                    break
                if _OPERATOR_INLINE_RE.match(lines[i]):
                    break
                if nl:
                    body_lines.append(nl)
                i += 1

            body = " ".join(body_lines).strip()
            if body and len(body) > 20:
                sections.append({
                    "section_type": section_type,
                    "speaker": speaker_name,
                    "role": role,
                    "text": body,
                    "word_count": len(body.split()),
                })
            continue

        i += 1

    # Fallback: if sections is empty, use the full text
    if not sections:
        sections.append({
            "section_type": "prepared_remarks",
            "speaker": "Management",
            "role": "management",
            "text": text.strip(),
            "word_count": len(text.split()),
        })

    management_speakers = list({
        s["speaker"] for s in sections
        if s["role"] == "management"
    })
    analyst_count = len({
        s["speaker"] for s in sections if s["role"] == "analyst"
    })

    return sections, management_speakers, analyst_count


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def get_transcripts_dir() -> Path:
    settings = get_settings()
    d = Path(settings.transcripts_dir)
    if not d.is_absolute():
        # Resolve relative to the process working directory (works in both Docker and local)
        d = (Path.cwd() / d).resolve()
    return d


def list_transcript_files(ticker: str) -> dict[str, list[dict]]:
    """
    Scan the transcripts directory for files matching ticker.
    Returns {transcripts, releases, other} each as a list of TranscriptFile dicts.
    """
    d = get_transcripts_dir()
    result: dict[str, list[dict]] = {"transcripts": [], "releases": [], "other": []}
    if not d.exists():
        logger.warning("Transcripts dir not found: %s", d)
        return result

    for f in sorted(d.iterdir()):
        if not f.name.lower().endswith((".pdf", ".txt")):
            continue
        if not f.name.upper().startswith(ticker.upper() + "_"):
            continue

        meta = _parse_filename(f.name)
        try:
            if f.name.lower().endswith(".txt"):
                _, page_count = _extract_text_file(f)
            else:
                _, page_count = _extract_pdf_text(f)
        except Exception:
            page_count = 0

        entry = {
            "filename": f.name,
            "ticker": meta["ticker"],
            "quarter": meta["quarter"],
            "fiscal_year": meta["fiscal_year"],
            "call_date": meta["call_date"],
            "doc_type": meta["doc_type"],
            "word_count": 0,   # filled during parse
            "page_count": page_count,
        }

        dt = meta["doc_type"]
        if dt == "EarningsCall":
            result["transcripts"].append(entry)
        elif dt == "EarningsRelease":
            result["releases"].append(entry)
        else:
            result["other"].append(entry)

    return result


def parse_transcript(filename: str) -> dict:
    """Parse a transcript PDF and return a ParsedTranscript-compatible dict."""
    d = get_transcripts_dir()
    path = d / filename
    if not path.exists():
        raise FileNotFoundError(f"Transcript not found: {filename}")

    if path.suffix.lower() == ".txt":
        text, page_count = _extract_text_file(path)
    else:
        text, page_count = _extract_pdf_text(path)
    meta = _parse_filename(filename)
    word_count = len(text.split())

    sections, management_speakers, analyst_count = _split_sections(text)

    prep_wc = sum(s["word_count"] for s in sections if s["section_type"] == "prepared_remarks")
    qa_wc = sum(s["word_count"] for s in sections if s["section_type"] == "qa")

    return {
        "meta": {
            **meta,
            "filename": filename,
            "word_count": word_count,
            "page_count": page_count,
        },
        "sections": sections,
        "full_text": text,
        "management_speakers": management_speakers,
        "analyst_count": analyst_count,
        "prepared_word_count": prep_wc,
        "qa_word_count": qa_wc,
    }


# ---------------------------------------------------------------------------
# LLM sentiment analysis
# ---------------------------------------------------------------------------

def analyze_sentiment(transcript_text: str, ticker: str, period: str) -> dict:
    """
    Use LLM to perform deep NLP analysis on a transcript.
    Returns SentimentAnalysis-compatible dict.
    """
    # Truncate to avoid token limits (keep first 8000 chars)
    excerpt = transcript_text[:8000]

    keywords = _count_keywords(transcript_text)
    hedge_dens = _hedge_density(transcript_text)

    prompt = f"""You are a financial analyst specializing in earnings call analysis.
Analyze this {ticker} earnings call transcript for {period}.

TRANSCRIPT EXCERPT:
{excerpt}

Return a JSON object with exactly this structure:
{{
  "overall_label": "Bullish | Cautiously Optimistic | Neutral | Cautious | Bearish",
  "overall_score": <number 0-100, higher=more bullish>,
  "management_confidence": <number 0-100>,
  "key_quotes": [<3-5 most significant verbatim quotes, each under 150 chars>],
  "guidance_statements": [<3-5 forward-looking statements management made>],
  "top_topics": [
    {{"topic": "<topic name>", "pct": <estimated % of call>, "sample_quote": "<brief quote>"}}
    ... (5 topics)
  ],
  "tone_narrative": "<2-3 sentence narrative describing management's overall tone and posture>"
}}"""

    result = chat_json([{"role": "user", "content": prompt}])

    # Merge in computed fields
    hedge_words_found = [
        t for t, _ in KEYWORD_CATEGORIES["hedging"]
        if transcript_text.lower().count(t) > 0
    ]

    return {
        **result,
        "hedge_density": hedge_dens,
        "keywords": keywords,
        "hedge_words_found": hedge_words_found,
    }


# ---------------------------------------------------------------------------
# Financial comparison
# ---------------------------------------------------------------------------

def _get_financial_kpis(ticker: str, fiscal_year: int, quarter: str) -> list[dict]:
    """
    Fetch key financial metrics from SEC EDGAR for the given period.
    Returns a list of FinancialKPI-compatible dicts.
    """
    from app.services.sec_data import get_annual_values

    concept_map = {
        "Revenue": ("Revenues", False),
        "Net Income": ("NetIncomeLoss", False),
        "EPS (Diluted)": ("EarningsPerShareDiluted", False),
        "Gross Profit": ("GrossProfit", False),
        "Operating Income": ("OperatingIncomeLoss", False),
        "CapEx": ("PaymentsToAcquirePropertyPlantAndEquipment", False),
    }

    kpis = []
    for label, (concept, is_instant) in concept_map.items():
        try:
            values = get_annual_values(ticker, concept, instant=is_instant)
            if values:
                # Pick the closest year
                val = values.get(fiscal_year) or values.get(fiscal_year - 1)
                if val is not None:
                    # Determine unit
                    if label == "EPS (Diluted)":
                        unit = "$/share"
                    elif abs(val) >= 1e9:
                        val = val / 1e9
                        unit = "B"
                    elif abs(val) >= 1e6:
                        val = val / 1e6
                        unit = "M"
                    else:
                        unit = ""

                    # YoY change
                    prev = values.get(fiscal_year - 1)
                    yoy = None
                    if prev and prev != 0 and fiscal_year in values:
                        curr = values[fiscal_year]
                        yoy = round((curr - prev) / abs(prev) * 100, 1)

                    kpis.append({
                        "label": label,
                        "value": round(val, 2),
                        "period": f"FY{fiscal_year}",
                        "unit": unit,
                        "yoy_change": yoy,
                    })
        except Exception as e:
            logger.debug("KPI fetch failed for %s / %s: %s", ticker, concept, e)

    return kpis


def analyze_comparison(
    ticker: str,
    fiscal_year: int,
    quarter: str,
    transcript_text: str,
    sentiment: dict,
) -> dict:
    """
    Compare management language to actual financial performance.
    Returns ComparisonAnalysis-compatible dict.
    """
    kpis = _get_financial_kpis(ticker, fiscal_year, quarter)
    kpi_summary = "\n".join(
        f"- {k['label']}: {k['value']}{k['unit']} (FY{fiscal_year})"
        for k in kpis
    ) or "Not available from SEC EDGAR"

    guidance = "\n".join(f"- {g}" for g in sentiment.get("guidance_statements", []))
    tone = sentiment.get("overall_label", "Neutral")
    excerpt = transcript_text[:4000]

    prompt = f"""You are a financial analyst comparing earnings call language to actual results.

TICKER: {ticker} | PERIOD: {quarter} {fiscal_year}
MANAGEMENT TONE: {tone}

GUIDANCE STATEMENTS FROM CALL:
{guidance}

ACTUAL FINANCIAL RESULTS (SEC EDGAR):
{kpi_summary}

TRANSCRIPT EXCERPT:
{excerpt}

Return a JSON object:
{{
  "beat_miss_summary": "<1-2 sentences: did results align with the tone/guidance?>",
  "ai_comparison": "<3-4 sentence analytical comparison of what management communicated vs what the numbers show>",
  "management_signals": [
    {{
      "topic": "<e.g. Revenue Growth>",
      "what_was_said": "<brief paraphrase of management's language>",
      "actual_result": "<what the financials show>",
      "alignment": "beat | miss | in_line | n/a"
    }}
    ... (3-5 items)
  ]
}}"""

    result = chat_json([{"role": "user", "content": prompt}])
    return {
        **result,
        "transcript_quarter": f"{quarter} {fiscal_year}",
        "financial_kpis": kpis,
        "data_source": "SEC EDGAR XBRL",
    }


# ---------------------------------------------------------------------------
# Full analysis pipeline
# ---------------------------------------------------------------------------

def full_analysis(filename: str, ticker: str) -> dict:
    """
    Parse + analyze a single earnings call transcript.
    Returns EarningsCallAnalysis-compatible dict.
    """
    parsed = parse_transcript(filename)
    meta = parsed["meta"]
    period = f"{meta['quarter']} {meta['fiscal_year']}"

    sentiment = analyze_sentiment(parsed["full_text"], ticker, period)
    comparison = analyze_comparison(
        ticker=ticker,
        fiscal_year=meta["fiscal_year"],
        quarter=meta["quarter"],
        transcript_text=parsed["full_text"],
        sentiment=sentiment,
    )

    # AI summary
    prompt = f"""Summarize this {ticker} {period} earnings call in 3 sentences for a finance student.
Tone: {sentiment.get('overall_label')}
Key topics: {', '.join(t['topic'] for t in sentiment.get('top_topics', [])[:3])}
Comparison: {comparison.get('beat_miss_summary', '')}
Give an educational summary that connects management language to financial outcomes."""

    from app.services.llm_service import chat
    ai_summary = chat([{"role": "user", "content": prompt}])

    observations_prompt = f"""Generate 3 educational observations about this {ticker} {period} earnings call.
Sentiment: {sentiment.get('overall_label')}
Comparison: {comparison.get('ai_comparison', '')}

Return JSON: [{{"title": "...", "insight": "...", "follow_up": "..."}}]
Each observation should teach something about how to read management communication."""

    observations = chat_json([{"role": "user", "content": observations_prompt}])
    if not isinstance(observations, list):
        observations = []

    return {
        "meta": meta,
        "sentiment": sentiment,
        "comparison": comparison,
        "ai_summary": ai_summary,
        "observations": observations,
    }
