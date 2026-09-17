from __future__ import annotations

import json
import mimetypes
import os
from collections.abc import Callable, Iterable
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any
from wsgiref.simple_server import WSGIServer, make_server

from app.config import Settings
from app.presentation_cases import DEFAULT_CASES_PATH, load_demo_cases
from app.presentation_compare import compare_question
from app.presentation_status import get_presentation_status

StartResponse = Callable[[str, list[tuple[str, str]]], None]
WsgiApp = Callable[[dict[str, Any], StartResponse], Iterable[bytes]]


class ThreadingWsgiServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def make_app(
    *,
    frontend_dir: Path = Path("presentation"),
    cases_path: Path = DEFAULT_CASES_PATH,
    settings_factory: Callable[[], Settings] = Settings.from_env,
    cases_loader: Callable[[Path], dict[str, Any]] = load_demo_cases,
    compare: Callable[..., dict[str, Any]] = compare_question,
    status_provider: Callable[[Settings, dict[str, str]], dict[str, Any]] = get_presentation_status,
    env: dict[str, str] | None = None,
) -> WsgiApp:
    active_env = env if env is not None else os.environ

    def app(environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/")
        try:
            if method == "GET" and path == "/":
                return _file_response(frontend_dir / "index.html", start_response)
            if method == "GET" and path.startswith("/static/"):
                return _file_response(frontend_dir / path.lstrip("/"), start_response)
            if method == "GET" and path == "/api/cases":
                return _json_response(start_response, 200, cases_loader(cases_path))
            if method == "GET" and path == "/api/status":
                return _json_response(
                    start_response,
                    200,
                    status_provider(settings_factory(), active_env),
                )
            if method == "POST" and path == "/api/compare":
                payload = _read_json(environ)
                question = _require_text(payload, "question")
                filters = payload.get("filters", {})
                if not isinstance(filters, dict):
                    raise ValueError("filters must be an object")
                local_model = _optional_text(payload, "local_model")
                result = compare(
                    question,
                    filters,
                    settings=settings_factory(),
                    gemini_project=(
                        active_env.get("GOOGLE_CLOUD_PROJECT")
                        or active_env.get("GCP_PROJECT_ID")
                        or ""
                    ),
                    gemini_location=_env_text(active_env, "GOOGLE_CLOUD_LOCATION", "us-central1"),
                    gemini_model=_env_text(active_env, "GEMINI_MODEL", "gemini-2.5-flash"),
                    local_model=local_model,
                )
                return _json_response(start_response, 200, result)
            return _json_response(start_response, 404, {"error": "not found"})
        except Exception as exc:
            return _json_response(start_response, 500, {"error": str(exc)})

    return app


def serve(host: str, port: int, app: WsgiApp | None = None) -> None:
    active_app = app or make_app()
    with make_server(host, port, active_app, server_class=ThreadingWsgiServer) as server:
        print(f"Presentation frontend: http://{host}:{port}", flush=True)
        server.serve_forever()


def _file_response(path: Path, start_response: StartResponse) -> Iterable[bytes]:
    if not path.exists() or not path.is_file():
        return _json_response(start_response, 404, {"error": "not found"})
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body = path.read_bytes()
    content_type_header = (
        f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type
    )
    start_response(
        "200 OK",
        [
            ("Content-Type", content_type_header),
            ("Content-Length", str(len(body))),
        ],
    )
    return [body]


def _json_response(
    start_response: StartResponse,
    status_code: int,
    payload: dict[str, Any],
) -> Iterable[bytes]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    status_text = "OK" if status_code == 200 else "Error"
    start_response(
        f"{status_code} {status_text}",
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ],
    )
    return [body]


def _read_json(environ: dict[str, Any]) -> dict[str, Any]:
    length = int(environ.get("CONTENT_LENGTH") or "0")
    body = environ["wsgi.input"].read(length)
    payload = json.loads(body.decode("utf-8") or "{}")
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    return payload


def _require_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    normalized = value.strip()
    return normalized or None


def _env_text(env: dict[str, str], key: str, default: str) -> str:
    return env.get(key, default).strip() or default
