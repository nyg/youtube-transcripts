"""Global settings: stored in the database, edited from the Settings dialog."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from yt_summarizer import youtube_client
from yt_summarizer.config import ConfigError, Settings, parse_settings, settings_to_raw

from ..schemas import SettingsBody

router = APIRouter(prefix="/api/settings")


def _to_body(settings: Settings) -> SettingsBody:
    return SettingsBody.model_validate(settings_to_raw(settings))


@router.get("", response_model=SettingsBody)
def get_settings(request: Request) -> SettingsBody:
    return _to_body(request.app.state.settings.current)


@router.put("", response_model=SettingsBody)
def update_settings(body: SettingsBody, request: Request) -> SettingsBody:
    state = request.app.state
    raw = body.model_dump()
    # Saving confirms each price for the model its family resolves to right now.
    raw["priced_models"] = {model.family: model.alias for model in state.catalog.models()}
    try:
        settings = parse_settings(raw)
    except ConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    state.settings.replace(settings)
    youtube_client.configure(
        request_interval=settings.youtube_request_interval,
        cookiefile=settings.cookies_file,
    )
    state.monitor.refresh()
    return _to_body(settings)
