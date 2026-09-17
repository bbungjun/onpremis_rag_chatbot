from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest


def server_module():
    try:
        return importlib.import_module("app.server")
    except ModuleNotFoundError as exc:
        pytest.fail(f"app.server should exist: {exc}")


def make_settings():
    return SimpleNamespace(
        ollama_base_url="http://ollama.test",
        embedding_model="bge-m3",
        qdrant_url="http://qdrant.test",
        qdrant_collection="chunks",
        llm_model="qwen3:4b-instruct",
        temperature=0.2,
        num_ctx=4096,
        num_predict=512,
        retrieval_top_k=5,
    )


def test_server_exposes_only_supported_answer_routes_and_health_fields():
    server = server_module()
    answer_routes = {
        route.path for route in server.app.routes if route.path.startswith("/api/ask/")
    }

    assert answer_routes == {"/api/ask/qwen", "/api/ask/gemini"}
    assert set(server.HealthResponse.model_fields) == {"api", "ollama", "qdrant", "gemini"}


def test_ask_qwen_uses_latest_rag_signature(monkeypatch):
    server = server_module()
    settings = make_settings()
    captured = {}

    monkeypatch.setattr(server.Settings, "from_env", lambda: settings)

    def fake_answer_question(question, top_k, **kwargs):
        captured["question"] = question
        captured["top_k"] = top_k
        captured["metadata_filter"] = kwargs["metadata_filter"]
        captured["settings"] = kwargs["settings"]
        return {
            "answer": "연차 신청은 최소 3영업일 전까지 해야 합니다.",
            "sources": [{"source_path": "datasets/docs/regulations.md", "chunk_id": "jo-39"}],
        }

    monkeypatch.setattr(server, "answer_question", fake_answer_question)

    response = server.ask_qwen(
        server.AskRequest(
            question="연차 신청은 며칠 전까지 해야 하나요?",
            top_k=3,
            metadata_filter={"jo": "제39조"},
            department="hr",
            source_path="datasets/docs/regulations.md",
        )
    )

    assert response.answer == "연차 신청은 최소 3영업일 전까지 해야 합니다."
    assert captured["question"] == "연차 신청은 며칠 전까지 해야 하나요?"
    assert captured["top_k"] == 3
    assert captured["metadata_filter"] == {
        "jo": "제39조",
        "department": "hr",
        "source_path": "datasets/docs/regulations.md",
    }
    assert captured["settings"] is settings


def test_ask_qwen_defaults_top_k_from_settings(monkeypatch):
    server = server_module()
    settings = make_settings()
    captured = {}

    monkeypatch.setattr(server.Settings, "from_env", lambda: settings)

    def fake_answer_question(question, top_k, **kwargs):
        captured["top_k"] = top_k
        return {"answer": "답변", "sources": []}

    monkeypatch.setattr(server, "answer_question", fake_answer_question)

    server.ask_qwen(server.AskRequest(question="경비 처리 시 어떤 증빙이 필요한가요?"))

    assert captured["top_k"] == settings.retrieval_top_k


def test_ask_qwen_uses_requested_supported_ollama_model(monkeypatch):
    server = server_module()
    settings = make_settings()
    captured = {}

    monkeypatch.setattr(server.Settings, "from_env", lambda: settings)

    def fake_answer_question(question, top_k, **kwargs):
        captured["settings"] = kwargs["settings"]
        return {"answer": "EXAONE 답변", "sources": []}

    monkeypatch.setattr(server, "answer_question", fake_answer_question)

    response = server.ask_qwen(
        server.AskRequest(question="연차규정이 어떻게 되나요?", llm_model="exaone3.5:7.8b")
    )

    assert response.answer == "EXAONE 답변"
    assert captured["settings"].llm_model == "exaone3.5:7.8b"
    assert captured["settings"] is not settings
    assert settings.llm_model == "qwen3:4b-instruct"


def test_ask_qwen_rejects_unsupported_ollama_model(monkeypatch):
    server = server_module()

    monkeypatch.setattr(server.Settings, "from_env", make_settings)

    def fail_if_called(*args, **kwargs):
        pytest.fail("not called")

    monkeypatch.setattr(server, "answer_question", fail_if_called)

    with pytest.raises(Exception) as exc_info:
        server.ask_qwen(
            server.AskRequest(question="연차규정이 어떻게 되나요?", llm_model="bad-model")
        )

    assert getattr(exc_info.value, "status_code", None) == 400
    assert "Unsupported Ollama model" in str(getattr(exc_info.value, "detail", ""))


def test_ask_gemini_requires_project(monkeypatch):
    server = server_module()

    monkeypatch.setattr(server.Settings, "from_env", make_settings)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)

    with pytest.raises(Exception) as exc_info:
        server.ask_gemini(server.AskRequest(question="재택근무 승인 절차는 어떻게 되나요?"))

    assert getattr(exc_info.value, "status_code", None) == 503


def test_ask_gemini_uses_pr10_context_builder_pipeline(monkeypatch):
    server = server_module()
    settings = make_settings()
    captured = {}

    monkeypatch.setattr(server.Settings, "from_env", lambda: settings)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "project-123")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "asia-northeast3")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("GEMINI_THINKING_BUDGET", "0")

    def fake_answer_question_with_gemini(question, top_k, **kwargs):
        captured["question"] = question
        captured["top_k"] = top_k
        captured.update(kwargs)
        return {
            "answer": "문서 기준상 최소 3영업일 전 기준을 충족하지 않습니다.",
            "sources": [{"source_path": "datasets/docs/regulations.md", "chunk_id": "jo-39"}],
        }

    monkeypatch.setattr(server, "answer_question_with_gemini", fake_answer_question_with_gemini)

    response = server.ask_gemini(
        server.AskRequest(
            question="이틀 뒤에 연차신청해도될까요?",
            metadata_filter={"source_path": "datasets/docs/regulations.md"},
        )
    )

    assert response.answer == "문서 기준상 최소 3영업일 전 기준을 충족하지 않습니다."
    assert captured["question"] == "이틀 뒤에 연차신청해도될까요?"
    assert captured["top_k"] == settings.retrieval_top_k
    assert captured["metadata_filter"] == {"source_path": "datasets/docs/regulations.md"}
    assert captured["project"] == "project-123"
    assert captured["location"] == "asia-northeast3"
    assert captured["model"] == "gemini-2.5-flash"
    assert captured["max_output_tokens"] == settings.num_predict
    assert captured["thinking_budget"] == 0
    assert captured["settings"] is settings


def test_ask_gemini_allows_session_model_and_endpoint_overrides(monkeypatch):
    server = server_module()
    settings = make_settings()
    captured = {}

    monkeypatch.setattr(server.Settings, "from_env", lambda: settings)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)

    def fake_answer_question_with_gemini(question, top_k, **kwargs):
        captured.update(kwargs)
        return {"answer": "Gemini override answer", "sources": []}

    monkeypatch.setattr(server, "answer_question_with_gemini", fake_answer_question_with_gemini)

    response = server.ask_gemini(
        server.AskRequest(
            question="?곗감 ?좎껌",
            gemini_project="demo-project",
            gemini_location="asia-northeast3",
            gemini_model="gemini-2.5-pro",
            gemini_thinking_budget=0,
        )
    )

    assert response.answer == "Gemini override answer"
    assert captured["project"] == "demo-project"
    assert captured["location"] == "asia-northeast3"
    assert captured["model"] == "gemini-2.5-pro"
    assert captured["thinking_budget"] == 0
    assert captured["max_output_tokens"] == settings.num_predict


def test_check_gemini_warns_when_credential_file_is_missing(monkeypatch, tmp_path):
    server = server_module()
    missing_path = tmp_path / "missing-sa.json"

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "project-123")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(missing_path))

    status = server._check_gemini()

    assert status.status == "warning"
    assert "credential" in status.detail.lower()


def test_check_gemini_accepts_authorized_user_adc_credentials(monkeypatch, tmp_path):
    server = server_module()
    credential_path = tmp_path / "authorized-user.json"
    credential_path.write_text(
        '{"type":"authorized_user","client_id":"client","client_secret":"secret","refresh_token":"token"}',
        encoding="utf-8",
    )

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "project-123")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(credential_path))

    status = server._check_gemini()

    assert status.status == "ok"
    assert "gemini-2.5-flash" in status.detail
