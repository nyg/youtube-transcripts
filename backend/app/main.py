"""FastAPI application wiring config, database, Claude client, and routers.

Run from the backend/ directory:  uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from yt_summarizer import paths, youtube_client
from yt_summarizer.claude_client import ClaudeSummarizer, SummarizerError
from yt_summarizer.config import read_config_file
from yt_summarizer.database import Database
from yt_summarizer.models import FAMILIES, ModelCatalog, family_of

from .estimates import EstimateStore
from .jobs import JobRegistry
from .monitor import ChannelMonitor
from .routers import (
    channels,
    estimates,
    jobs,
    mentions,
    meta,
    monitor,
    prompts,
    questions,
    search,
    settings,
    summaries,
)
from .settings import SettingsStore, load_settings

_LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _configure_logging() -> None:
    """Timestamp every log line (local time, millisecond precision).

    uvicorn installs its own handlers on `uvicorn`/`uvicorn.access` before this
    module is imported, and those don't inherit the root formatter — so restamp
    them too, otherwise half the log file has no time in it.
    """
    logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT, datefmt=_LOG_DATEFMT)
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT)
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            handler.setFormatter(formatter)


_configure_logging()
log = logging.getLogger(__name__)

_STARTER_PROMPT_NAME = "summary"
_STARTER_PROMPT_TEXT = (
    "You are given the full transcript of a YouTube video. Write a concise summary "
    "of its key points in a few short paragraphs. Base the summary only on the "
    "transcript; do not invent details, and do not mention that you are working "
    "from a transcript."
)


def _bootstrap_prompts(db: Database, config_file: Path) -> None:
    """Seed the prompts table on first run.

    Prompts used to live in config.yaml. On the first start after that move, import
    any prompts still defined there (and point channels that had no prompt at the
    former active_prompt) so an existing setup keeps working. Failing that, seed a
    single generic starter prompt so a fresh install can add a channel right away.
    """
    if db.list_prompts():
        return
    try:
        raw = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        raw = {}
    legacy = raw.get("prompts") if isinstance(raw, dict) else None
    if isinstance(legacy, dict) and legacy:
        est = int(raw.get("estimated_output_tokens", 2000))
        for name, text in legacy.items():
            db.add_prompt(str(name), str(text).strip(), est)
        active = str(raw.get("active_prompt") or next(iter(legacy)))
        if active not in legacy:
            active = next(iter(legacy))
        # Channels created before per-channel prompts had a NULL prompt_name and
        # relied on active_prompt — point them at it now.
        for channel in db.list_channels():
            if not channel["prompt_name"]:
                db.update_channel(channel["id"], prompt_name=active)
        log.info("Imported %d prompt(s) from config.yaml into the database", len(legacy))
    else:
        db.add_prompt(_STARTER_PROMPT_NAME, _STARTER_PROMPT_TEXT, 2000)
        log.info(
            "Seeded a starter %r prompt — choose its model and effort in Manage prompts",
            _STARTER_PROMPT_NAME,
        )


def _adopt_model_families(db: Database) -> None:
    """Prompts used to store a model id; they now store its family."""
    for prompt in db.list_prompts():
        model = prompt["model"]
        if not model or model in FAMILIES:
            continue
        family = family_of(model)
        if family is None:
            log.warning("Prompt %r uses the unknown model %r — choose one", prompt["name"], model)
            continue
        db.update_prompt(prompt["id"], model=family)
        log.info("Prompt %r now uses the latest %s model (was %s)", prompt["name"], family, model)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config_file = paths.ensure_config()
    log.info("Loading config from %s", config_file)
    file_config = read_config_file(config_file)
    database = paths.resolve_database_path(file_config.get("database"))
    log.info("Using database at %s", database)
    db = Database(database)
    cfg = load_settings(db, file_config)
    youtube_client.configure(
        request_interval=cfg.youtube_request_interval,
        cookiefile=cfg.cookies_file,
    )
    _bootstrap_prompts(db, config_file)
    _adopt_model_families(db)
    indexed = db.backfill_chunks()
    if indexed:
        log.info("Indexed %d stored summar(ies) for search", indexed)
    app.state.settings = SettingsStore(db, cfg)
    app.state.db = db
    app.state.summarizer = ClaudeSummarizer()
    app.state.catalog = ModelCatalog(app.state.summarizer.list_models)
    app.state.estimates = EstimateStore()
    app.state.questions = EstimateStore()
    app.state.jobs = JobRegistry()
    app.state.monitor = ChannelMonitor(
        app.state.settings, db, app.state.summarizer, app.state.jobs, app.state.catalog
    )
    app.state.monitor.start()
    try:
        yield
    finally:
        app.state.monitor.stop()


app = FastAPI(title="YouTube Summarizer", lifespan=lifespan)


@app.exception_handler(SummarizerError)
async def summarizer_error_handler(request: Request, exc: SummarizerError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


for router_module in (
    meta,
    settings,
    channels,
    prompts,
    estimates,
    jobs,
    monitor,
    summaries,
    mentions,
    search,
    questions,
):
    app.include_router(router_module.router)
