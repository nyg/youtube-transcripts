from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.main import mount_frontend


def _app_with_api() -> FastAPI:
    app = FastAPI()
    router = APIRouter()
    router.add_api_route("/api/ping", lambda: {"ok": True})
    app.include_router(router)
    return app


def test_the_built_frontend_is_served_next_to_the_api(tmp_path):
    (tmp_path / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index.js").write_text("console.log(1)", encoding="utf-8")
    app = _app_with_api()

    mount_frontend(app, tmp_path)
    client = TestClient(app)

    assert client.get("/").text == "<html>app</html>"
    assert client.get("/assets/index.js").text == "console.log(1)"
    assert client.get("/api/ping").json() == {"ok": True}


def test_nothing_is_mounted_without_a_build(tmp_path):
    app = _app_with_api()

    mount_frontend(app, tmp_path / "missing")

    assert TestClient(app).get("/").status_code == 404
