"""FastAPI application wiring config, database, Claude client, and routers.

Run from the backend/ directory:  uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from yt_summarizer.claude_client import ClaudeSummarizer, SummarizerError
from yt_summarizer.config import load_config
from yt_summarizer.database import Database

from .estimates import EstimateStore
from .jobs import JobRegistry
from .routers import channels, estimates, jobs, meta, summaries

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config(Path("config.yaml"))
    db = Database(cfg.database)
    if cfg.channel and not db.list_channels():
        db.add_channel(cfg.channel, cfg.channel)
        log.info("Seeded channel list with %r from config.yaml", cfg.channel)
    app.state.config = cfg
    app.state.db = db
    app.state.summarizer = ClaudeSummarizer(cfg.model, cfg.max_output_tokens, cfg.pricing)
    app.state.estimates = EstimateStore()
    app.state.jobs = JobRegistry()
    yield


app = FastAPI(title="YouTube Summarizer", lifespan=lifespan)


@app.exception_handler(SummarizerError)
async def summarizer_error_handler(request: Request, exc: SummarizerError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


for router_module in (meta, channels, estimates, jobs, summaries):
    app.include_router(router_module.router)
