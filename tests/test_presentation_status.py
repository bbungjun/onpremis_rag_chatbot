from types import SimpleNamespace

from app.presentation_status import get_presentation_status


def settings():
    return SimpleNamespace(
        ollama_base_url="http://203.0.113.10:11434",
        llm_model="qwen3:4b-instruct",
    )


def test_get_presentation_status_reports_local_model_and_ec2_endpoint(monkeypatch):
    import app.presentation_status as status_module

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": [{"name": "qwen3:4b-instruct"}, {"name": "bge-m3"}]}

    monkeypatch.setattr(status_module.httpx, "get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(status_module, "has_bedrock_credentials", lambda: False)

    result = get_presentation_status(
        settings(),
        {
            "BEDROCK_REGION": "ap-northeast-2",
            "BEDROCK_MODEL_ID": "",
            "BEDROCK_MODEL_LABEL": "AWS Bedrock",
        },
    )

    assert result["local"] == {
        "label": "Ollama + Qwen",
        "model": "qwen3:4b-instruct",
        "endpoint": "http://203.0.113.10:11434",
        "integration_status": "ok",
        "integration_message": "EC2 Ollama 엔드포인트 연결됨",
    }


def test_get_presentation_status_reports_missing_bedrock_model(monkeypatch):
    import app.presentation_status as status_module

    monkeypatch.setattr(
        status_module.httpx,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    monkeypatch.setattr(status_module, "has_bedrock_credentials", lambda: True)

    result = get_presentation_status(
        settings(),
        {
            "BEDROCK_REGION": "ap-northeast-2",
            "BEDROCK_MODEL_ID": "",
            "BEDROCK_MODEL_LABEL": "AWS Bedrock",
        },
    )

    assert result["api"]["model"] == "미설정"
    assert result["api"]["integration_status"] == "pending"
    assert result["api"]["integration_message"] == "Bedrock 모델 미설정"


def test_get_presentation_status_reports_bedrock_credentials_detected(monkeypatch):
    import app.presentation_status as status_module

    monkeypatch.setattr(
        status_module.httpx,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    monkeypatch.setattr(status_module, "has_bedrock_credentials", lambda: True)

    result = get_presentation_status(
        settings(),
        {
            "BEDROCK_REGION": "ap-northeast-2",
            "BEDROCK_MODEL_ID": "anthropic.claude-3-5-sonnet-20240620-v1:0",
            "BEDROCK_MODEL_LABEL": "AWS Bedrock",
        },
    )

    assert result["api"]["model"] == "anthropic.claude-3-5-sonnet-20240620-v1:0"
    assert result["api"]["integration_status"] == "ok"
    assert result["api"]["integration_message"] == "AWS credentials detected"
