from __future__ import annotations

import json
import os
from dataclasses import is_dataclass, replace
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import Settings
from app.gemini_pipeline import answer_question_with_gemini
from app.rag_pipeline import answer_question

app = FastAPI(title="llmenhance RAG API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_HEALTH_TIMEOUT_SECONDS = 5.0
_DEFAULT_GEMINI_LOCATION = "us-central1"
_DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
_DEFAULT_GEMINI_THINKING_BUDGET = 0
_SUPPORTED_OLLAMA_MODELS = ("qwen3:4b-instruct", "exaone3.5:7.8b")
_CONVENIENCE_FILTER_FIELDS = (
    "source_path",
    "document_id",
    "title",
    "pyeon",
    "jang",
    "jeol",
    "jo",
    "jo_no",
    "hang_no",
    "hang_label",
    "department",
    "doc_type",
    "category",
    "security_level",
)


class AskRequest(BaseModel):
    question: str
    llm_model: str | None = None
    gemini_project: str | None = None
    gemini_location: str | None = None
    gemini_model: str | None = None
    gemini_thinking_budget: int | None = None
    top_k: int | None = None
    metadata_filter: dict[str, Any] | None = None
    source_path: str | None = None
    document_id: str | None = None
    title: str | None = None
    pyeon: str | None = None
    jang: str | None = None
    jeol: str | None = None
    jo: str | None = None
    jo_no: str | int | None = None
    hang_no: str | int | None = None
    hang_label: str | None = None
    department: str | None = None
    doc_type: str | None = None
    category: str | None = None
    security_level: str | None = None


class AskResponse(BaseModel):
    answer: str
    sources: list[dict[str, Any]]
    elapsed_ms: int


class ServiceStatus(BaseModel):
    status: str
    detail: str = ""


class HealthResponse(BaseModel):
    api: ServiceStatus
    ollama: ServiceStatus
    qdrant: ServiceStatus
    gemini: ServiceStatus


@app.get("/health", response_model=ServiceStatus)
def health() -> ServiceStatus:
    return ServiceStatus(status="ok", detail="API server is running.")


@app.get("/health/services", response_model=HealthResponse)
def health_services() -> HealthResponse:
    settings = Settings.from_env()
    return HealthResponse(
        api=ServiceStatus(status="ok", detail="API server is running."),
        ollama=_check_ollama(settings.ollama_base_url, settings.llm_model),
        qdrant=_check_qdrant(settings.qdrant_url),
        gemini=_check_gemini(),
    )


@app.post("/api/ask/qwen", response_model=AskResponse)
def ask_qwen(req: AskRequest) -> AskResponse:
    settings = _settings_for_requested_ollama_model(Settings.from_env(), req.llm_model)
    started = perf_counter()
    try:
        result = answer_question(
            req.question,
            _resolve_top_k(req, settings),
            metadata_filter=_build_metadata_filter(req),
            settings=settings,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return _ask_response(result, started)


@app.post("/api/ask/gemini", response_model=AskResponse)
def ask_gemini(req: AskRequest) -> AskResponse:
    if not _env_bool("ENABLE_GEMINI_ENDPOINT", True):
        raise HTTPException(status_code=503, detail="Gemini endpoint is disabled.")

    settings = Settings.from_env()
    project = _first_text(req.gemini_project, _gemini_project())
    if not project:
        raise HTTPException(
            status_code=503,
            detail="GOOGLE_CLOUD_PROJECT or GCP_PROJECT_ID is required for Gemini.",
        )

    started = perf_counter()
    try:
        result = answer_question_with_gemini(
            req.question,
            _resolve_top_k(req, settings),
            metadata_filter=_build_metadata_filter(req),
            project=project,
            location=_first_text(
                req.gemini_location, os.getenv("GOOGLE_CLOUD_LOCATION"), _DEFAULT_GEMINI_LOCATION
            ),
            model=_first_text(req.gemini_model, os.getenv("GEMINI_MODEL"), _DEFAULT_GEMINI_MODEL),
            max_output_tokens=settings.num_predict,
            thinking_budget=(
                req.gemini_thinking_budget
                if req.gemini_thinking_budget is not None
                else _gemini_thinking_budget()
            ),
            settings=settings,
            progress=None,
            timing=None,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return _ask_response(result, started)


def _ask_response(result: dict[str, Any], started: float) -> AskResponse:
    return AskResponse(
        answer=str(result["answer"]),
        sources=list(result.get("sources") or []),
        elapsed_ms=int((perf_counter() - started) * 1000),
    )


def _resolve_top_k(req: AskRequest, settings: Settings) -> int:
    return settings.retrieval_top_k if req.top_k is None else req.top_k


def _settings_for_requested_ollama_model(
    settings: Settings, requested_model: str | None
) -> Settings:
    model = requested_model.strip() if requested_model else ""
    if not model:
        return settings

    if model not in _SUPPORTED_OLLAMA_MODELS:
        supported = ", ".join(_SUPPORTED_OLLAMA_MODELS)
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported Ollama model {model!r}. Supported models: {supported}.",
        )

    if model == settings.llm_model:
        return settings

    if is_dataclass(settings):
        return replace(settings, llm_model=model)

    values = vars(settings).copy()
    values["llm_model"] = model
    try:
        return type(settings)(**values)
    except TypeError:
        return SimpleNamespace(**values)


def _build_metadata_filter(req: AskRequest) -> dict[str, str] | None:
    metadata_filter: dict[str, str] = {}
    for key, value in (req.metadata_filter or {}).items():
        if _has_filter_value(value):
            metadata_filter[str(key)] = str(value)

    for field in _CONVENIENCE_FILTER_FIELDS:
        value = getattr(req, field)
        if _has_filter_value(value):
            metadata_filter[field] = str(value)

    return metadata_filter or None


def _has_filter_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def _check_ollama(base_url: str, model: str) -> ServiceStatus:
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=_HEALTH_TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.ConnectError:
        return ServiceStatus(status="error", detail=f"Could not connect to {base_url}.")
    except httpx.TimeoutException:
        return ServiceStatus(status="error", detail=f"Timed out connecting to {base_url}.")
    except Exception as exc:
        return ServiceStatus(status="error", detail=str(exc))

    available_models = [
        item.get("name", "") for item in response.json().get("models", []) if isinstance(item, dict)
    ]
    if model in available_models:
        return ServiceStatus(status="ok", detail=f"Model {model!r} is available.")
    if available_models:
        return ServiceStatus(
            status="warning",
            detail=f"Connected, but model {model!r} was not listed.",
        )
    return ServiceStatus(status="warning", detail="Connected, but no models were listed.")


def _check_qdrant(qdrant_url: str) -> ServiceStatus:
    try:
        response = httpx.get(qdrant_url, timeout=_HEALTH_TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.ConnectError:
        return ServiceStatus(status="error", detail=f"Could not connect to {qdrant_url}.")
    except httpx.TimeoutException:
        return ServiceStatus(status="error", detail=f"Timed out connecting to {qdrant_url}.")
    except Exception as exc:
        return ServiceStatus(status="error", detail=str(exc))
    return ServiceStatus(status="ok", detail=f"Connected to {qdrant_url}.")


def _check_gemini() -> ServiceStatus:
    project = _gemini_project()
    model = os.getenv("GEMINI_MODEL", _DEFAULT_GEMINI_MODEL)
    if not project:
        return ServiceStatus(
            status="error",
            detail="GOOGLE_CLOUD_PROJECT or GCP_PROJECT_ID is not configured.",
        )

    credential_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    credential_status = _credential_file_status(credential_path)
    if credential_status is not None:
        return credential_status

    return ServiceStatus(status="ok", detail=f"Project {project!r}, model {model!r}.")


def _credential_file_status(credential_path: str) -> ServiceStatus | None:
    if not credential_path:
        return ServiceStatus(
            status="warning",
            detail="GOOGLE_APPLICATION_CREDENTIALS is not configured.",
        )

    path = Path(credential_path)
    if not path.is_file():
        return ServiceStatus(
            status="warning",
            detail=f"Credential file is not available at {credential_path}.",
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return ServiceStatus(status="warning", detail=f"Credential file is not valid JSON: {exc}")

    credential_type = data.get("type")
    if credential_type == "service_account":
        required_fields = ("project_id", "client_email", "private_key")
        if any(not data.get(field) for field in required_fields):
            return ServiceStatus(
                status="warning",
                detail="Service account credential file is missing required fields.",
            )
        return None
    if credential_type == "authorized_user":
        required_fields = ("client_id", "client_secret", "refresh_token")
        if any(not data.get(field) for field in required_fields):
            return ServiceStatus(
                status="warning",
                detail="Authorized user credential file is missing required fields.",
            )
        return None
    if credential_type == "external_account":
        return None

    if credential_type:
        return ServiceStatus(
            status="warning",
            detail=f"Credential file type {credential_type!r} is not supported.",
        )
    return ServiceStatus(
        status="warning",
        detail="Credential file is present but does not include a credential type.",
    )


def _gemini_project() -> str:
    return os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT_ID", "")


def _gemini_thinking_budget() -> int:
    raw_value = os.getenv("GEMINI_THINKING_BUDGET", str(_DEFAULT_GEMINI_THINKING_BUDGET))
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"GEMINI_THINKING_BUDGET must be an integer, got {raw_value!r}") from exc


def _first_text(*values: str | None) -> str:
    for value in values:
        if value is not None and value.strip():
            return value.strip()
    return ""


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}
