"""
LLM service for disclosure analysis and coaching.

Supports OpenAI, Azure OpenAI, and Google Gemini REST endpoints via env config.
Set DEFAULT_LLM_PROVIDER=gemini to route calls through Gemini generateContent.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import get_openai_client, get_settings, get_ssl_verify

logger = logging.getLogger(__name__)

_settings = get_settings()
LLM_PROVIDER = _settings.default_llm_provider.lower().strip()
DEFAULT_MODEL = (
    _settings.gemini_model
    if LLM_PROVIDER == "gemini"
    else _settings.default_llm_model
)
API_TYPE = _settings.openai_api_type

_client = None if LLM_PROVIDER == "gemini" else get_openai_client()


def _gemini_contents(messages: list[dict[str, str]]) -> tuple[list[dict[str, Any]], str]:
    """Convert OpenAI-style messages to Gemini REST contents and system instruction."""
    contents: list[dict[str, Any]] = []
    system_parts: list[str] = []

    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if not content:
            continue
        if role == "system":
            system_parts.append(content)
            continue
        contents.append({
            "role": "model" if role == "assistant" else "user",
            "parts": [{"text": content}],
        })

    if not contents:
        contents.append({"role": "user", "parts": [{"text": ""}]})

    return contents, "\n\n".join(system_parts)


def _chat_gemini(
    messages: list[dict[str, str]],
    model: str,
    temperature: float,
    max_tokens: int,
    response_mime_type: str | None = None,
) -> str:
    """Call Gemini with the raw generateContent REST API."""
    if not _settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not set. Add it to .env.local or .env.")

    import httpx

    contents, system_instruction = _gemini_contents(messages)
    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }
    if response_mime_type:
        payload["generationConfig"]["responseMimeType"] = response_mime_type
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{model}:generateContent"
    )
    logger.info("LLM request: model=%s, provider=gemini", model)

    try:
        with httpx.Client(verify=get_ssl_verify(), timeout=60.0) as client:
            response = client.post(
                url,
                params={"key": _settings.gemini_api_key},
                headers={"Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        raise RuntimeError(
            f"Gemini API error {exc.response.status_code}: {detail}"
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Gemini API request failed: {exc}") from exc

    data = response.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        detail = json.dumps(data)[:500]
        raise RuntimeError(f"Unexpected Gemini response: {detail}") from exc


def chat(
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    response_mime_type: str | None = None,
) -> str:
    """Send a chat completion request and return the assistant's text."""
    resolved_model = model or DEFAULT_MODEL
    if LLM_PROVIDER == "gemini":
        return _chat_gemini(
            messages,
            model=resolved_model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_mime_type=response_mime_type,
        )

    logger.info("LLM request: model=%s, type=%s", resolved_model, API_TYPE)
    if _client is None:
        raise RuntimeError("OpenAI client is not configured")
    create_kwargs: dict[str, Any] = {
        "model": resolved_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_mime_type == "application/json":
        create_kwargs["response_format"] = {"type": "json_object"}
    response = _client.chat.completions.create(**create_kwargs)
    return response.choices[0].message.content or ""


def chat_json(
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.2,
) -> dict[str, Any]:
    """Chat completion that parses the response as JSON."""
    raw = chat(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=3000,
        response_mime_type="application/json",
    )
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
    return json.loads(cleaned)


# ---------------------------------------------------------------------------
# Formatting helper
# ---------------------------------------------------------------------------

def _fmt(val: float | None) -> str:
    if val is None:
        return "not available"
    abs_v = abs(val)
    if abs_v >= 1e9:
        return f"${val / 1e9:,.1f}B"
    if abs_v >= 1e6:
        return f"${val / 1e6:,.0f}M"
    return f"${val:,.0f}"


def _lives_str(useful_lives: list[dict]) -> str:
    return ", ".join(
        f"{ul.get('asset_type', '?')}: {ul.get('useful_life_min', '?')}–{ul.get('useful_life_max', '?')} yr"
        for ul in useful_lives
    ) or "not available"


# ---------------------------------------------------------------------------
# Layer-specific analysis prompts
# ---------------------------------------------------------------------------

LAYER1_PROMPT = """\
You are an expert accounting educator. A student just pulled PP&E data from \
{company_name}'s {form_type}. Analyze the NUMBERS and return JSON (no markdown \
wrapping, no text outside the JSON):

{{
  "depreciation_method": "method if determinable from data, else 'see disclosure'",
  "capitalization_policy": "",
  "policy_highlights": [
    "3-5 observations about what the numbers reveal"
  ],
  "asset_age_pct": <accumulated_depreciation / gross_ppe * 100, rounded to 1 decimal>,
  "observations": [
    {{
      "title": "short title",
      "insight": "what this number means for the business",
      "follow_up": "question the student should investigate"
    }}
  ],
  "summary": "2-3 sentence summary focused on what the numbers tell us about capital investment"
}}

Focus on: asset age ratio, relative size of construction in progress, useful life \
ranges vs industry norms, and what the gross-to-net ratio implies about the company's \
investment cycle. Keep it concise.

Data:
- Gross PP&E: {gross}
- Accumulated Depreciation: {accum_depr}
- Net PP&E: {net}
- Useful lives: {useful_lives}
"""

LAYER2_PROMPT = """\
You are an expert accounting educator. A student is reading the PP&E footnote \
disclosure from {company_name}'s {form_type}. Analyze the DISCLOSURE TEXT and \
return JSON (no markdown wrapping, no text outside the JSON):

{{
  "depreciation_method": "the primary depreciation method stated",
  "capitalization_policy": "1-2 sentence summary of capitalization rules",
  "policy_highlights": [
    "3-5 key policy choices extracted from the text"
  ],
  "asset_age_pct": <accumulated_depreciation / gross_ppe * 100 if calculable>,
  "observations": [
    {{
      "title": "short title",
      "insight": "what this policy choice means or implies",
      "follow_up": "question about how this compares to peers or impacts financials"
    }}
  ],
  "summary": "2-3 sentence summary of the most important policy choices and disclosures"
}}

Focus on: depreciation method, useful life assumptions, capitalization thresholds, \
internal-use software treatment, leasehold improvement policy, any changes in \
estimates, and any unusual or noteworthy language. Keep it concise.

Data context:
- Gross PP&E: {gross}
- Accumulated Depreciation: {accum_depr}
- Net PP&E: {net}
- Useful lives: {useful_lives}

Disclosure text:
{disclosure_text}
"""

LAYER3_PROMPT = """\
You are an expert accounting educator. A student has computed PP&E analytics \
for {company_name}'s {form_type}. Help them interpret the DERIVED METRICS and \
return JSON (no markdown wrapping, no text outside the JSON):

{{
  "depreciation_method": "method if known, else 'see disclosure'",
  "capitalization_policy": "",
  "policy_highlights": [
    "3-5 interpretive insights about trends, ratios, and capital strategy"
  ],
  "asset_age_pct": <accumulated_depreciation / gross_ppe * 100, rounded to 1 decimal>,
  "observations": [
    {{
      "title": "short title",
      "insight": "what this metric reveals about capital investment strategy",
      "follow_up": "analytical question a student should explore"
    }}
  ],
  "summary": "2-3 sentence summary interpreting the overall capital investment story"
}}

Focus on: Is the asset base aging or being renewed? What do growth rates in gross \
vs net PP&E imply? How sensitive is earnings to useful-life assumptions? What would \
an analyst pay attention to? Keep it concise and analytical.

Data:
- Gross PP&E: {gross}
- Accumulated Depreciation: {accum_depr}
- Net PP&E: {net}
- Useful lives: {useful_lives}
"""

LAYER4_PROMPT = """\
You are an expert accounting educator. A student is comparing {company_name}'s \
PP&E to industry peers. Analyze the COMPARATIVE DATA and return JSON (no markdown \
wrapping, no text outside the JSON):

{{
  "depreciation_method": "method used by the primary company",
  "capitalization_policy": "",
  "policy_highlights": [
    "3-5 comparative observations about how peers differ on PP&E metrics"
  ],
  "asset_age_pct": <primary company's asset age % if calculable>,
  "observations": [
    {{
      "title": "short title",
      "insight": "what this cross-company comparison reveals",
      "follow_up": "question about why peers diverge or what it means strategically"
    }}
  ],
  "summary": "2-3 sentence comparative summary — who is investing most aggressively, \
whose asset base is oldest, and what strategic story the numbers tell"
}}

Focus on: Which companies have the oldest/newest assets? Who is investing most \
aggressively (highest growth)? Are useful life assumptions similar or divergent? \
What do differences imply about competitive positioning? Keep it concise.

Primary company:
- Gross PP&E: {gross}
- Accumulated Depreciation: {accum_depr}
- Net PP&E: {net}
- Useful lives: {useful_lives}

{disclosure_text}
"""

LAYER_PROMPTS = {
    1: LAYER1_PROMPT,
    2: LAYER2_PROMPT,
    3: LAYER3_PROMPT,
    4: LAYER4_PROMPT,
}


def analyze_disclosure(
    company_name: str,
    form_type: str,
    gross: float | None,
    accum_depr: float | None,
    net: float | None,
    useful_lives: list[dict],
    disclosure_text: str,
    layer: int = 2,
    segment_context: str = "",
) -> dict[str, Any]:
    """Run layer-specific LLM analysis on PP&E data."""
    template = LAYER_PROMPTS.get(layer, LAYER2_PROMPT)

    kwargs: dict[str, str] = {
        "company_name": company_name,
        "form_type": form_type,
        "gross": _fmt(gross),
        "accum_depr": _fmt(accum_depr),
        "net": _fmt(net),
        "useful_lives": _lives_str(useful_lives),
    }
    if "{disclosure_text}" in template:
        kwargs["disclosure_text"] = disclosure_text[:6000]

    prompt = template.format(**kwargs)
    if segment_context:
        prompt += "\n\n" + segment_context
    return chat_json([{"role": "user", "content": prompt}])


# ---------------------------------------------------------------------------
# Follow-up conversation
# ---------------------------------------------------------------------------

SYSTEM_CONTEXT = """\
You are an expert accounting professor helping a student understand PP&E \
(Property, Plant & Equipment) disclosures. The student is working with data \
from {company_name}'s {form_type} filing.

PP&E context:
- Gross PP&E: {gross}
- Accumulated Depreciation: {accum_depr}
- Net PP&E: {net}
- Useful lives: {useful_lives}
{disclosure_section}

Answer concisely and at a level appropriate for an accounting student. Reference \
specific numbers from the data when relevant. If the student asks about something \
outside PP&E, briefly answer but guide them back to the relevant concepts."""


def build_system_context(
    company_name: str,
    form_type: str,
    gross: float | None,
    accum_depr: float | None,
    net: float | None,
    useful_lives: list[dict],
    disclosure_text: str,
) -> str:
    disclosure_section = ""
    if disclosure_text:
        disclosure_section = f"\nDisclosure text (excerpt):\n{disclosure_text[:4000]}"

    return SYSTEM_CONTEXT.format(
        company_name=company_name,
        form_type=form_type,
        gross=_fmt(gross),
        accum_depr=_fmt(accum_depr),
        net=_fmt(net),
        useful_lives=_lives_str(useful_lives),
        disclosure_section=disclosure_section,
    )


def follow_up(
    system_context: str,
    conversation: list[dict[str, str]],
) -> str:
    """Continue a conversation with the PP&E data as context."""
    messages = [{"role": "system", "content": system_context}] + conversation
    return chat(messages, temperature=0.4, max_tokens=1500)


# ---------------------------------------------------------------------------
# Allowance for Doubtful Accounts — Layer-specific prompts
# ---------------------------------------------------------------------------

ALLOWANCE_LAYER1_PROMPT = """\
You are an expert accounting educator. A student just pulled Accounts Receivable \
and Allowance for Doubtful Accounts data from {company_name}'s {form_type}. \
Analyze the NUMBERS and return JSON (no markdown wrapping, no text outside the JSON):

{{
  "allowance_methodology": "methodology if determinable from data, else 'see disclosure'",
  "risk_factors": "",
  "policy_highlights": [
    "3-5 observations about what the numbers reveal about credit risk and provisioning"
  ],
  "allowance_ratio_pct": {allowance_ratio},
  "observations": [
    {{
      "title": "short title",
      "insight": "what this number means for credit quality and earnings",
      "follow_up": "question the student should investigate"
    }}
  ],
  "summary": "2-3 sentence summary of what the AR and allowance data reveal about this company's credit risk profile"
}}

Focus on: the allowance ratio (allowance / gross AR) and what it implies about expected \
credit losses, how DSO and bad debt expense relate, whether the provisioning level \
seems conservative or aggressive, and any red flags. Industry context: retail companies \
typically reserve 1-3%, telecom 3-6%, banks 1-4%, casino markers 25-50%.

Data:
- AR Net: {ar_net}
- Allowance for Credit Losses: {allowance}
- Gross AR (AR Net + Allowance): {gross_ar}
- Allowance Ratio: {allowance_ratio}%
- Revenue: {revenue}

Historical trends:
{historical_summary}
"""

ALLOWANCE_LAYER2_PROMPT = """\
You are an expert accounting educator. A student is reading the credit losses \
footnote disclosure from {company_name}'s {form_type}. Analyze the DISCLOSURE TEXT \
and return JSON (no markdown wrapping, no text outside the JSON):

{{
  "allowance_methodology": "the methodology described (aging schedule, historical loss rate, specific identification, CECL, etc.)",
  "risk_factors": "key risk factors mentioned (customer concentration, jurisdiction, collateral, economic conditions)",
  "policy_highlights": [
    "3-5 key policy choices and disclosures extracted from the text"
  ],
  "allowance_ratio_pct": {allowance_ratio},
  "observations": [
    {{
      "title": "short title",
      "insight": "what this disclosure reveals about management's judgment and credit risk approach",
      "follow_up": "question about how this compares to peers or impacts reported earnings"
    }}
  ],
  "summary": "2-3 sentence summary of the most important credit loss disclosures and what they imply"
}}

Focus on: the estimation methodology (aging, CECL, specific identification), key risk \
factors cited, whether there's a rollforward table (beginning → provisions → write-offs → \
recoveries → ending), any sensitivity disclosures, and any changes in methodology. \
The allowance is a management estimate that directly affects earnings.

Data context:
- AR Net: {ar_net}
- Allowance: {allowance}
- Gross AR: {gross_ar}
- Allowance Ratio: {allowance_ratio}%
- Revenue: {revenue}

Disclosure text:
{disclosure_text}
"""

ALLOWANCE_LAYER3_PROMPT = """\
You are an expert accounting educator with forensic accounting expertise. A student \
has computed allowance analytics for {company_name}'s {form_type}. Help them interpret \
the DERIVED METRICS AND TRENDS, focusing on earnings management detection. \
Return JSON (no markdown wrapping, no text outside the JSON):

{{
  "allowance_methodology": "methodology if known, else 'see disclosure'",
  "risk_factors": "trends that indicate changing risk profile",
  "policy_highlights": [
    "3-5 analytical insights about trends, ratio movements, and potential earnings management signals"
  ],
  "allowance_ratio_pct": {allowance_ratio},
  "observations": [
    {{
      "title": "short title",
      "insight": "what this metric reveals about accounting conservatism or potential manipulation",
      "follow_up": "analytical question a student should explore"
    }}
  ],
  "summary": "2-3 sentence summary interpreting the earnings management risk and credit quality trends"
}}

Four lenses to apply:
1. Credit Risk Trends — Is the ratio increasing (more expected defaults) or decreasing (better collections or aggressive accounting)?
2. Accounting Conservatism — Higher ratio vs. peers → more conservative provisioning
3. Earnings Management — "A 100 bps change in allowance percentage would change bad-debt expense materially." Declining ratio in a bad year = possible reserve release
4. Business Model — structural differences explain some ratio variation

Data:
- AR Net: {ar_net}
- Allowance: {allowance}
- Gross AR: {gross_ar}
- Allowance Ratio: {allowance_ratio}%
- Revenue: {revenue}

Historical trends:
{historical_summary}

{disclosure_text}
"""

ALLOWANCE_LAYER4_PROMPT = """\
You are an expert accounting educator. A student is comparing {company_name}'s \
Allowance for Doubtful Accounts to industry peers. Analyze the COMPARATIVE DATA \
and return JSON (no markdown wrapping, no text outside the JSON):

{{
  "allowance_methodology": "primary company's methodology if known",
  "risk_factors": "key differences in risk exposure across peers",
  "policy_highlights": [
    "3-5 comparative observations about how peers differ on allowance metrics"
  ],
  "allowance_ratio_pct": {allowance_ratio},
  "observations": [
    {{
      "title": "short title",
      "insight": "what this cross-company comparison reveals about accounting conservatism",
      "follow_up": "question about why peers diverge or what it means for financial analysis"
    }}
  ],
  "summary": "2-3 sentence comparative summary — who provisions most conservatively, \
whose credit risk exposure is highest, and what structural factors explain the differences"
}}

Focus on: Which company has the highest/lowest allowance ratio? Are the differences \
structural (business model) or accounting choice (judgment)? How do DSO and bad debt \
expense ratios compare? What would an analyst conclude about each company's conservatism?

Industry benchmarks: Retail 1-3%, Telecom 3-6%, Banks 1-4%, Casino markers 25-50%.

Primary company:
- AR Net: {ar_net}
- Allowance: {allowance}
- Gross AR: {gross_ar}
- Allowance Ratio: {allowance_ratio}%
- Revenue: {revenue}

{disclosure_text}
"""

ALLOWANCE_LAYER_PROMPTS = {
    1: ALLOWANCE_LAYER1_PROMPT,
    2: ALLOWANCE_LAYER2_PROMPT,
    3: ALLOWANCE_LAYER3_PROMPT,
    4: ALLOWANCE_LAYER4_PROMPT,
}


def analyze_allowance_disclosure(
    company_name: str,
    form_type: str,
    ar_net: float | None,
    allowance: float | None,
    gross_ar: float | None,
    allowance_ratio: float | None,
    revenue: float | None,
    disclosure_text: str,
    historical_summary: str = "",
    layer: int = 1,
    segment_context: str = "",
) -> dict[str, Any]:
    """Run layer-specific LLM analysis on allowance data."""
    template = ALLOWANCE_LAYER_PROMPTS.get(layer, ALLOWANCE_LAYER1_PROMPT)

    kwargs: dict[str, str] = {
        "company_name": company_name,
        "form_type": form_type,
        "ar_net": _fmt(ar_net),
        "allowance": _fmt(allowance),
        "gross_ar": _fmt(gross_ar),
        "allowance_ratio": f"{allowance_ratio:.1f}" if allowance_ratio else "not available",
        "revenue": _fmt(revenue),
    }
    if "{disclosure_text}" in template:
        kwargs["disclosure_text"] = disclosure_text[:6000]
    if "{historical_summary}" in template:
        kwargs["historical_summary"] = historical_summary[:3000]

    prompt = template.format(**kwargs)
    if segment_context:
        prompt += "\n\n" + segment_context
    return chat_json([{"role": "user", "content": prompt}])


ALLOWANCE_SYSTEM_CONTEXT = """\
You are an expert accounting professor helping a student understand the Allowance \
for Doubtful Accounts (credit losses) and its implications for earnings quality. \
The student is working with data from {company_name}'s {form_type} filing.

Allowance context:
- AR Net (on balance sheet): {ar_net}
- Allowance for Credit Losses: {allowance}
- Gross AR (AR Net + Allowance): {gross_ar}
- Allowance Ratio (Allowance / Gross AR): {allowance_ratio}%
- Revenue: {revenue}

Historical:
{historical_summary}
{disclosure_section}

Key concepts to reinforce:
- The allowance is a MANAGEMENT ESTIMATE that directly affects reported earnings
- Allowance Ratio = Allowance / Gross AR = Allowance / (AR Net + Allowance)
- A 100 basis point change in the ratio can materially change bad debt expense
- Industry norms: Retail 1-3%, Telecom 3-6%, Banks 1-4%, Casino 25-50%

Answer concisely and at a level appropriate for an accounting student. Reference \
specific numbers from the data when relevant. Help them think critically about \
whether the allowance level reflects genuine credit risk or potential earnings management."""


def build_allowance_system_context(
    company_name: str,
    form_type: str,
    ar_net: float | None,
    allowance: float | None,
    gross_ar: float | None,
    allowance_ratio: float | None,
    revenue: float | None,
    disclosure_text: str,
    historical_summary: str = "",
) -> str:
    disclosure_section = ""
    if disclosure_text:
        disclosure_section = f"\nDisclosure text (excerpt):\n{disclosure_text[:4000]}"

    return ALLOWANCE_SYSTEM_CONTEXT.format(
        company_name=company_name,
        form_type=form_type,
        ar_net=_fmt(ar_net),
        allowance=_fmt(allowance),
        gross_ar=_fmt(gross_ar),
        allowance_ratio=f"{allowance_ratio:.1f}" if allowance_ratio else "not available",
        revenue=_fmt(revenue),
        historical_summary=historical_summary[:2000],
        disclosure_section=disclosure_section,
    )
