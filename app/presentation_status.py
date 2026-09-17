from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings


def get_presentation_status(settings: Settings, env: dict[str, str]) -> dict[str, Any]:
    return {
        "local": _local_status(settings),
        "api": _api_status(env),
    }


def _local_status(settings: Settings) -> dict[str, Any]:
    base = {
        "label": "Ollama + Qwen",
        "model": settings.llm_model,
        "endpoint": settings.ollama_base_url,
    }
    try:
        response = httpx.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags", timeout=5)
        response.raise_for_status()
        models = response.json().get("models", [])
        model_names = {
            model.get("name")
            for model in models
            if isinstance(model, dict) and isinstance(model.get("name"), str)
        }
        if settings.llm_model in model_names:
            return {
                **base,
                "integration_status": "ok",
                "integration_message": "EC2 Ollama 엔드포인트 연결됨",
            }
        return {
            **base,
            "integration_status": "error",
            "integration_message": f"Model {settings.llm_model} not found on Ollama endpoint",
        }
    except Exception as exc:
        return {
            **base,
            "integration_status": "error",
            "integration_message": f"EC2 Ollama endpoint check failed: {exc}",
        }


def _api_status(env: dict[str, str]) -> dict[str, Any]:
    project = (env.get("GOOGLE_CLOUD_PROJECT") or env.get("GCP_PROJECT_ID") or "").strip()
    model = env.get("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    location = env.get("GOOGLE_CLOUD_LOCATION", "us-central1").strip() or "us-central1"
    base = {
        "label": "Vertex Gemini",
        "model": model,
        "location": location,
    }
    if not project:
        return {
            **base,
            "integration_status": "pending",
            "integration_message": "Gemini project 미설정",
        }
    return {
        **base,
        "integration_status": "ok",
        "integration_message": "Gemini project configured; connection checked on request",
    }
