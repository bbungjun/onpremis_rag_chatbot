from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import is_dataclass, replace
from time import perf_counter
from types import SimpleNamespace
from typing import Any

from app.config import Settings
from app.gemini_pipeline import answer_question_with_gemini
from app.rag_pipeline import answer_question

AnswerFn = Callable[..., dict[str, Any]]
LOCAL_MODEL_OPTIONS = ("qwen3:4b-instruct", "exaone3.5:7.8b")


def compare_question(
    question: str,
    filters: dict[str, str | None],
    *,
    settings: Settings,
    gemini_project: str,
    gemini_location: str,
    gemini_model: str,
    local_model: str | None = None,
    local_answer: AnswerFn = answer_question,
    gemini_answer: AnswerFn = answer_question_with_gemini,
) -> dict[str, Any]:
    top_k = _int_from_env("PRESENTATION_TOP_K", settings.retrieval_top_k)
    thinking_budget = _int_from_env("GEMINI_THINKING_BUDGET", 0)
    selected_local_model = _select_local_model(settings, local_model)
    local_settings = _settings_with_llm_model(settings, selected_local_model)
    normalized_filters = {
        "doc_type": filters.get("doc_type"),
        "department": filters.get("department"),
        "category": filters.get("category"),
        "security_level": filters.get("security_level"),
        "source_path": filters.get("source_path"),
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        local_future = executor.submit(
            _run_local,
            local_answer,
            question,
            normalized_filters,
            top_k,
            local_settings,
            selected_local_model,
        )
        api_future = (
            executor.submit(
                _run_gemini,
                gemini_answer,
                question,
                normalized_filters,
                top_k,
                settings,
                gemini_project,
                gemini_location,
                gemini_model,
                settings.num_predict,
                thinking_budget,
            )
            if gemini_project.strip()
            else None
        )

    local = local_future.result()
    api = (
        api_future.result()
        if api_future is not None
        else _pending_panel("Vertex Gemini", "미설정", "Gemini project 미설정")
    )
    return {
        "question": question,
        "filters": normalized_filters,
        "local": local,
        "api": api,
        "shared_sources": _merge_sources(local.get("sources", []), api.get("sources", [])),
    }


def _run_local(
    local_answer: AnswerFn,
    question: str,
    filters: dict[str, str | None],
    top_k: int,
    settings: Settings,
    model: str,
) -> dict[str, Any]:
    started = perf_counter()
    try:
        result = local_answer(
            question,
            top_k,
            metadata_filter=_metadata_filter(filters),
            settings=settings,
        )
        return _ok_panel(
            "Ollama Local",
            model,
            result,
            started,
            f"{model} 응답 성공",
        )
    except Exception as exc:
        return _error_panel("Ollama Local", model, exc, started)


def _run_gemini(
    gemini_answer: AnswerFn,
    question: str,
    filters: dict[str, str | None],
    top_k: int,
    settings: Settings,
    project: str,
    location: str,
    model: str,
    max_output_tokens: int,
    thinking_budget: int,
) -> dict[str, Any]:
    started = perf_counter()
    try:
        result = gemini_answer(
            question,
            top_k,
            metadata_filter=_metadata_filter(filters),
            project=project,
            location=location,
            model=model,
            max_output_tokens=max_output_tokens,
            thinking_budget=thinking_budget,
            settings=settings,
        )
        return _ok_panel(
            "Vertex Gemini",
            model,
            result,
            started,
            "Gemini 응답 성공",
        )
    except Exception as exc:
        return _error_panel("Vertex Gemini", model or "미설정", exc, started)


def _ok_panel(
    label: str,
    model: str,
    result: dict[str, Any],
    started: float,
    integration_message: str,
) -> dict[str, Any]:
    return {
        "label": label,
        "model": model,
        "status": "ok",
        "integration_status": "ok",
        "integration_message": integration_message,
        "answer": result["answer"],
        "sources": result["sources"],
        "generation_seconds": round(perf_counter() - started, 3),
    }


def _error_panel(label: str, model: str, exc: Exception, started: float) -> dict[str, Any]:
    return {
        "label": label,
        "model": model,
        "status": "error",
        "integration_status": "error",
        "integration_message": str(exc),
        "answer": "",
        "sources": [],
        "generation_seconds": round(perf_counter() - started, 3),
        "error": str(exc),
    }


def _pending_panel(label: str, model: str, integration_message: str) -> dict[str, Any]:
    return {
        "label": label,
        "model": model,
        "status": "pending",
        "integration_status": "pending",
        "integration_message": integration_message,
        "answer": "Gemini project가 아직 설정되지 않았습니다.",
        "sources": [],
        "generation_seconds": 0,
    }


def _merge_sources(
    local_sources: list[dict[str, Any]],
    api_sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged = {}
    for source in [*local_sources, *api_sources]:
        chunk_id = source.get("chunk_id")
        if isinstance(chunk_id, str) and chunk_id not in merged:
            merged[chunk_id] = source
    return list(merged.values())


def _select_local_model(settings: Settings, requested_model: str | None) -> str:
    if requested_model is None or not requested_model.strip():
        return settings.llm_model

    model = requested_model.strip()
    if model not in LOCAL_MODEL_OPTIONS:
        allowed = ", ".join(LOCAL_MODEL_OPTIONS)
        raise ValueError(f"unsupported local_model {model!r}; expected one of: {allowed}")
    return model


def _settings_with_llm_model(settings: Settings, model: str) -> Settings:
    if settings.llm_model == model:
        return settings

    if is_dataclass(settings):
        return replace(settings, llm_model=model)

    if hasattr(settings, "__dict__"):
        values = vars(settings).copy()
        values["llm_model"] = model
        return SimpleNamespace(**values)

    raise TypeError("settings must be a dataclass or expose __dict__ to override llm_model")


def _metadata_filter(filters: dict[str, str | None]) -> dict[str, str] | None:
    values = {key: str(value) for key, value in filters.items() if value}
    return values or None


def _int_from_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)
