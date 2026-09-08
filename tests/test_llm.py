import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def llm_module():
    try:
        return importlib.import_module("app.llm")
    except ModuleNotFoundError as exc:
        pytest.fail(f"app.llm should exist: {exc}")


def make_settings():
    from types import SimpleNamespace

    return SimpleNamespace(
        ollama_base_url="http://ollama.test",
        embedding_model="bge-m3",
        qdrant_url="http://qdrant.test",
        qdrant_collection="chunks",
        llm_model="qwen3.6:latest",
        temperature=0.2,
        num_ctx=4096,
        num_predict=512,
        llm_think="auto",
    )


# ---------------------------------------------------------------------------
# 인터페이스 계약
# ---------------------------------------------------------------------------
def test_llm_client_is_abstract():
    """LLMClient 는 직접 인스턴스화할 수 없다."""
    module = llm_module()
    with pytest.raises(TypeError):
        module.LLMClient()


def test_subclass_without_generate_cannot_be_instantiated():
    """generate 를 구현하지 않은 서브클래스는 인스턴스화되지 않는다."""
    module = llm_module()

    class Incomplete(module.LLMClient):
        @property
        def model_name(self) -> str:
            return "incomplete"

    with pytest.raises(TypeError):
        Incomplete()


def test_subclass_implementing_contract_is_usable():
    """generate 와 model_name 을 구현하면 LLMClient 로 쓸 수 있다."""
    module = llm_module()

    class Fake(module.LLMClient):
        label = "Fake"

        @property
        def model_name(self) -> str:
            return "fake-model"

        def generate(self, system_prompt: str, user_prompt: str) -> str:
            return f"{system_prompt}|{user_prompt}"

    client = Fake()
    assert isinstance(client, module.LLMClient)
    assert client.label == "Fake"
    assert client.model_name == "fake-model"
    assert client.generate("SYS", "USER") == "SYS|USER"


# ---------------------------------------------------------------------------
# 구현체 — 주입된 chat 함수에 설정을 그대로 전달한다
# ---------------------------------------------------------------------------
def test_ollama_llm_passes_settings_through_to_chat():
    module = llm_module()
    captured = {}

    def fake_chat(
        base_url,
        model,
        system_prompt,
        user_prompt,
        temperature,
        num_ctx,
        num_predict,
        think="auto",
    ):
        captured.update(
            base_url=base_url,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            num_ctx=num_ctx,
            num_predict=num_predict,
            think=think,
        )
        return "  answer  "

    client = module.OllamaLLM.from_settings(make_settings(), chat=fake_chat)

    assert client.label == "Qwen"
    assert client.model_name == "qwen3.6:latest"
    assert client.generate("SYS", "USER") == "  answer  "
    assert captured == {
        "base_url": "http://ollama.test",
        "model": "qwen3.6:latest",
        "system_prompt": "SYS",
        "user_prompt": "USER",
        "temperature": 0.2,
        "num_ctx": 4096,
        "num_predict": 512,
        "think": "auto",
    }


def test_gemini_llm_passes_arguments_in_client_order():
    module = llm_module()
    captured = {}

    def fake_chat(
        project,
        location,
        model,
        system_prompt,
        user_prompt,
        temperature,
        max_output_tokens,
        thinking_budget,
    ):
        captured.update(
            project=project,
            location=location,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            thinking_budget=thinking_budget,
        )
        return "gemini answer"

    client = module.GeminiLLM(
        project="proj",
        location="us-central1",
        model="gemini-2.5-flash",
        temperature=0.2,
        max_output_tokens=512,
        thinking_budget=0,
        chat=fake_chat,
    )

    assert client.label == "Gemini"
    assert client.model_name == "gemini-2.5-flash"
    assert client.generate("SYS", "USER") == "gemini answer"
    assert captured == {
        "project": "proj",
        "location": "us-central1",
        "model": "gemini-2.5-flash",
        "system_prompt": "SYS",
        "user_prompt": "USER",
        "temperature": 0.2,
        "max_output_tokens": 512,
        "thinking_budget": 0,
    }


def test_bedrock_llm_passes_arguments_in_client_order():
    module = llm_module()
    captured = {}

    def fake_chat(region, model_id, system_prompt, user_prompt, temperature, max_output_tokens):
        captured.update(
            region=region,
            model_id=model_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        return "bedrock answer"

    client = module.BedrockLLM(
        region="ap-northeast-2",
        model_id="bedrock-model",
        temperature=0.2,
        max_output_tokens=256,
        chat=fake_chat,
    )

    assert client.label == "Bedrock"
    assert client.model_name == "bedrock-model"
    assert client.generate("SYS", "USER") == "bedrock answer"
    assert captured == {
        "region": "ap-northeast-2",
        "model_id": "bedrock-model",
        "system_prompt": "SYS",
        "user_prompt": "USER",
        "temperature": 0.2,
        "max_output_tokens": 256,
    }


def test_every_builtin_client_satisfies_the_interface():
    """구현체 3종은 모두 LLMClient 로 취급될 수 있어야 한다."""
    module = llm_module()
    clients = (
        module.OllamaLLM.from_settings(make_settings(), chat=lambda *args: ""),
        module.GeminiLLM(
            project="p",
            location="l",
            model="m",
            temperature=0.1,
            max_output_tokens=1,
            thinking_budget=None,
            chat=lambda *args: "",
        ),
        module.BedrockLLM(
            region="r",
            model_id="m",
            temperature=0.1,
            max_output_tokens=1,
            chat=lambda *args: "",
        ),
    )
    for client in clients:
        assert isinstance(client, module.LLMClient)
        assert isinstance(client.label, str) and client.label
        assert isinstance(client.model_name, str) and client.model_name
