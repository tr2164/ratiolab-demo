import logging
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env.local", override=True)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import init_db

# Only the two routers needed for the Ratio Lab demo.
from app.routers import tickers, statements

logger = logging.getLogger(__name__)
settings = get_settings()

import app.models  # noqa: F401 — register all models with Base.metadata


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create database tables on startup."""
    await init_db()
    logger.info("Database initialized")
    yield


app = FastAPI(
    title="FinSight — Ratio Lab",
    description="ACCT-GB.2350 bonus session demo: SEC EDGAR + LLM analysis.",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Return JSON for unhandled errors so CORS headers are still applied."""
    logger.error("Unhandled error on %s %s: %s", request.method, request.url, exc)
    logger.error(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
    )


app.include_router(tickers.router)
app.include_router(statements.router)


@app.get("/")
async def root():
    return {"app": "FinSight — Ratio Lab", "docs": "/docs"}


@app.get("/health")
async def health():
    return {"status": "ok"}
