"""Bedrock 생성 경로.

검색·parent 확장·프롬프트 조립·fallback 은 rag_pipeline 과 완전히 동일하다.
이 모듈이 하는 일은 생성기(LLMClient)를 Bedrock 구현체로 바꿔 끼우는 것뿐이다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.bedrock_client import chat_bedrock
from app.config import Settings
from app.llm import BedrockLLM
from app.rag_pipeline import answer_question

__all__ = ["answer_question_with_bedrock"]


def answer_question_with_bedrock(
    question: str,
    top_k: int,
    *,
    metadata_filter: dict[str, str] | None = None,
    region: str,
    model_id: str,
    max_output_tokens: int,
    settings: Settings,
    progress: Callable[[str], None] | None = None,
    timing: Callable[[str, float], None] | None = None,
) -> dict[str, Any]:
    """Qwen 경로와 같은 검색을 쓰고 생성만 Bedrock 으로 한다."""
    if max_output_tokens <= 0:
        raise ValueError("max_output_tokens must be greater than 0")

    return answer_question(
        question,
        top_k,
        metadata_filter=metadata_filter,
        settings=settings,
        progress=progress,
        timing=timing,
        llm=BedrockLLM(
            region=region,
            model_id=model_id,
            temperature=settings.temperature,
            max_output_tokens=max_output_tokens,
            # chat_bedrock 은 이 시점의 모듈 전역에서 조회된다.
            chat=chat_bedrock,
        ),
    )
