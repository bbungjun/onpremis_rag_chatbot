"""생성 모델 경계.

RAG 파이프라인은 구체적인 모델(Qwen/Gemini)을 알지 않는다.
`LLMClient` 하나만 알고, 실제 HTTP/SDK 호출은 각 구현체가 담당한다.
따라서 모델을 추가하거나 바꿔도 검색·문맥 조립 코드는 건드리지 않는다.

각 구현체는 기존 클라이언트 함수(`chat_qwen` 등)를 감싸기만 한다.
`chat` 인자로 호출 함수를 주입할 수 있어 테스트에서 실제 네트워크를 타지 않는다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from app.gemini_client import chat_gemini_vertex
from app.qwen_client import chat_qwen


class LLMClient(ABC):
    """RAG 파이프라인이 생성 모델에 대해 아는 전부.

    label: 진행 메시지와 타이밍 로그에 쓰는 짧은 표시 이름.
    """

    label: str = "LLM"

    @property
    @abstractmethod
    def model_name(self) -> str:
        """실제 모델 식별자. 모델별 분기가 필요한 곳에서 이 값을 본다."""

    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """system 지시와 user 데이터를 분리한 채 답변을 생성한다.

        반환값은 가공하지 않은 원문이다. 공백 정리는 호출자가 한다.
        """


class OllamaLLM(LLMClient):
    """호스트 Ollama 로 생성한다. MVP 의 기본 경로(온프레미스)."""

    label = "Qwen"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        temperature: float,
        num_ctx: int,
        num_predict: int,
        think: str = "auto",
        chat: Callable[..., str] | None = None,
    ) -> None:
        self._base_url = base_url
        self._model = model
        self._temperature = temperature
        self._num_ctx = num_ctx
        self._num_predict = num_predict
        self._think = think
        self._chat = chat or chat_qwen

    @classmethod
    def from_settings(cls, settings: Any, *, chat: Callable[..., str] | None = None) -> OllamaLLM:
        return cls(
            base_url=settings.ollama_base_url,
            model=settings.llm_model,
            temperature=settings.temperature,
            num_ctx=settings.num_ctx,
            num_predict=settings.num_predict,
            think=settings.llm_think,
            chat=chat,
        )

    @property
    def model_name(self) -> str:
        return self._model

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        return self._chat(
            self._base_url,
            self._model,
            system_prompt,
            user_prompt,
            self._temperature,
            self._num_ctx,
            self._num_predict,
            think=self._think,
        )


class GeminiLLM(LLMClient):
    """Vertex AI Gemini 로 생성한다. 비교·평가용 개발 보조 경로."""

    label = "Gemini"

    def __init__(
        self,
        *,
        project: str,
        location: str,
        model: str,
        temperature: float,
        max_output_tokens: int,
        thinking_budget: int | None,
        chat: Callable[..., str] | None = None,
    ) -> None:
        self._project = project
        self._location = location
        self._model = model
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._thinking_budget = thinking_budget
        self._chat = chat or chat_gemini_vertex

    @property
    def model_name(self) -> str:
        return self._model

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        return self._chat(
            self._project,
            self._location,
            self._model,
            system_prompt,
            user_prompt,
            self._temperature,
            self._max_output_tokens,
            self._thinking_budget,
        )
