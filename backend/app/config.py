"""
Unified application settings for FinSight.

Reads from environment variables (and .env file via pydantic-settings).
"""

from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# Cache the combined CA bundle path (built once per process)
_COMBINED_CA_PATH: str | None = None


_SSL_INSECURE_WARNED = False


def get_ssl_verify() -> str | bool:
    """Return a CA bundle that trusts both standard internet CAs and any corporate VPN CA.

    When a corporate cert env var is set (SSL_CERT_FILE / REQUESTS_CA_BUNDLE /
    CURL_CA_BUNDLE), combines certifi's standard bundle with the corporate cert
    into a temp PEM file so HTTPS to both internet endpoints (the LLM API, EDGAR,
    Tavily) and the corporate proxy work correctly.

    If `INSECURE_SSL_VERIFY=true` is set, returns False. This is an opt-in escape
    hatch for corporate networks that perform SSL inspection without a usable CA.
    NEVER enable in production — it disables certificate verification entirely.
    """
    global _COMBINED_CA_PATH, _SSL_INSECURE_WARNED

    if os.environ.get("INSECURE_SSL_VERIFY", "").strip().lower() in ("1", "true", "yes"):
        if not _SSL_INSECURE_WARNED:
            import logging
            logging.getLogger(__name__).warning(
                "INSECURE_SSL_VERIFY is enabled — TLS certificate verification is "
                "DISABLED. This is unsafe and intended only for local development "
                "behind corporate SSL inspection."
            )
            _SSL_INSECURE_WARNED = True
        return False

    corp_cert: str | None = None
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        p = os.environ.get(var, "")
        if p and os.path.isfile(p):
            corp_cert = p
            break

    if corp_cert is None:
        try:
            import certifi
            return certifi.where()
        except ImportError:
            return True

    # Build combined bundle once per process
    if _COMBINED_CA_PATH and os.path.isfile(_COMBINED_CA_PATH):
        return _COMBINED_CA_PATH

    try:
        import certifi
        standard = Path(certifi.where()).read_text(encoding="utf-8", errors="replace")
        corporate = Path(corp_cert).read_text(encoding="utf-8", errors="replace")
        fd, tmp = tempfile.mkstemp(prefix="finsight_ca_", suffix=".pem")
        os.write(fd, (standard + "\n" + corporate).encode())
        os.close(fd)
        _COMBINED_CA_PATH = tmp
        return tmp
    except ImportError:
        return corp_cert


class Settings(BaseSettings):
    # -- Database --
    database_url: str = "postgresql+asyncpg://finsight:finsight@db:5432/finsight"
    sync_database_url: str = "postgresql://finsight:finsight@db:5432/finsight"

    # -- AI providers --
    openai_api_key: str = ""
    openai_api_url: str = "https://api.openai.com"
    openai_api_type: str = "openai"
    azure_openai_api_version: str = "2024-12-01-preview"
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # -- LLM model management --
    default_llm_provider: str = "openai"
    default_llm_model: str = "gpt-4o-mini"
    validator_llm_model: str = ""
    llm_model_allowlist: str = ""

    # -- SEC / Financial data --
    sec_user_agent: str = "nyu.finsight@nyu.edu"
    edgar_identity: str = ""
    edgar_cache_dir: str = "./edgar_cache"
    edgar_rate_limit: int = 8
    fmp_api_key: str = ""
    news_api_key: str = ""
    tavily_api_key: str = ""

    # -- CORS --
    cors_allow_origins: str = "http://localhost:3000,http://localhost:3001,http://localhost:3002"

    # -- Auth / LTI --
    dev_user_mode: bool = True
    dev_user_name: str = "Demo Instructor"
    dev_user_role: str = "instructor"
    dev_course_id: str = "ACCT-UB-0001-SP26"
    dev_course_title: str = "(M2) Financial Data Management and Analysis"

    lti_enabled: bool = False
    lti_issuer: str = "http://localhost:8002"
    lti_client_id: str = "finsight-lti-client"
    lti_deployment_id: str = "1"
    lti_platform_jwks_url: str = "http://localhost:8002/api/simulator/jwks"
    lti_platform_auth_url: str = "http://localhost:8002/api/simulator/auth"
    lti_platform_token_url: str = "http://localhost:8002/api/simulator/token"
    lti_private_key_file: str = ""
    lti_tool_url: str = "http://localhost:8002"
    frontend_url: str = "http://localhost:3002"

    # -- Transcripts (Analyst Call Reviewer) --
    transcripts_dir: str = "../transcripts"

    # -- App --
    app_name: str = "FinSight"
    debug: bool = True
    log_level: str = "info"

    @property
    def allowed_llm_models(self) -> List[str]:
        return [m.strip() for m in self.llm_model_allowlist.split(",") if m.strip()]

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    class Config:
        env_file = (
            str(PROJECT_ROOT / ".env"),
            str(PROJECT_ROOT / ".env.local"),
        )


@lru_cache()
def get_settings() -> Settings:
    return Settings()


def get_openai_client():
    """Return an OpenAI client configured for the active provider."""
    import httpx
    import openai
    s = get_settings()
    # Use combined CA bundle so SSL inspection by corporate VPN doesn't break LLM calls
    http_client = httpx.Client(verify=get_ssl_verify())
    if s.openai_api_type == "azure":
        return openai.AzureOpenAI(
            api_key=s.openai_api_key,
            azure_endpoint=s.openai_api_url,
            api_version=s.azure_openai_api_version,
            http_client=http_client,
        )
    kwargs: dict = {"api_key": s.openai_api_key, "http_client": http_client}
    if s.openai_api_url:
        kwargs["base_url"] = f"{s.openai_api_url.rstrip('/')}/v1"
    return openai.OpenAI(**kwargs)


def get_anthropic_client():
    """Return an Anthropic client."""
    import anthropic
    s = get_settings()
    return anthropic.Anthropic(api_key=s.anthropic_api_key)
