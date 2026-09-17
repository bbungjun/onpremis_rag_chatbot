from types import SimpleNamespace

from app.presentation_status import get_presentation_status


def settings():
    return SimpleNamespace(
        ollama_base_url="http://203.0.113.10:11434",
        llm_model="qwen3:4b-instruct",
    )


def test_presentation_status_reports_local_model_and_gemini_configuration(monkeypatch):
    import app.presentation_status as status_module

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": [{"name": "qwen3:4b-instruct"}, {"name": "bge-m3"}]}

    monkeypatch.setattr(status_module.httpx, "get", lambda *args, **kwargs: FakeResponse())

    result = get_presentation_status(
        settings(),
        {
            "GOOGLE_CLOUD_PROJECT": "demo-project",
            "GOOGLE_CLOUD_LOCATION": "us-central1",
            "GEMINI_MODEL": "gemini-2.5-flash",
        },
    )

    assert result["local"]["integration_status"] == "ok"
    assert result["api"] == {
        "label": "Vertex Gemini",
        "model": "gemini-2.5-flash",
        "location": "us-central1",
        "integration_status": "ok",
        "integration_message": "Gemini project configured; connection checked on request",
    }


def test_presentation_status_reports_missing_gemini_project(monkeypatch):
    import app.presentation_status as status_module

    monkeypatch.setattr(
        status_module.httpx,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    result = get_presentation_status(settings(), {})

    assert result["local"]["integration_status"] == "error"
    assert result["api"]["integration_status"] == "pending"
    assert result["api"]["integration_message"] == "Gemini project 미설정"
