from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Protocol

from app.retrieval_search import SearchHit

DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
DEFAULT_RERANKER_REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"


class RerankerBackend(Protocol):
    def score(
        self,
        pairs: Sequence[tuple[str, str]],
        *,
        batch_size: int,
        max_length: int,
    ) -> Sequence[float]: ...


@dataclass(frozen=True, slots=True)
class RerankerConfig:
    model_id: str = DEFAULT_RERANKER_MODEL
    revision: str = DEFAULT_RERANKER_REVISION
    device: str = "cpu"
    precision: str = "fp32"
    batch_size: int = 8
    max_length: int = 1024

    def __post_init__(self) -> None:
        if self.batch_size <= 0:
            raise ValueError("batch_size must be greater than 0")
        if self.max_length <= 0:
            raise ValueError("max_length must be greater than 0")
        if self.precision not in {"fp32", "fp16"}:
            raise ValueError("precision must be fp32 or fp16")


@dataclass(frozen=True, slots=True)
class RerankResult:
    hits: tuple[SearchHit, ...]
    elapsed_ms: float


def rerank_hits(
    query: str,
    hits: Sequence[SearchHit],
    *,
    backend: RerankerBackend,
    config: RerankerConfig,
) -> RerankResult:
    if not query.strip():
        raise ValueError("reranker query must not be empty")

    pairs = tuple((query, _child_text(hit)) for hit in hits)
    started = perf_counter()
    scores = tuple(
        float(score)
        for score in backend.score(
            pairs,
            batch_size=config.batch_size,
            max_length=config.max_length,
        )
    )
    elapsed_ms = (perf_counter() - started) * 1000
    if len(scores) != len(hits):
        raise ValueError("reranker returned a different number of scores than inputs")

    rescored = tuple(
        SearchHit(id=hit.id, score=score, payload=hit.payload)
        for hit, score in zip(hits, scores, strict=True)
    )
    return RerankResult(
        hits=tuple(
            sorted(
                rescored,
                key=lambda hit: hit.score,
                reverse=True,
            )
        ),
        elapsed_ms=elapsed_ms,
    )


def _child_text(hit: SearchHit) -> str:
    text = hit.payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("reranker requires non-empty child payload text")
    return text


class TransformersRerankerBackend:
    def __init__(self, config: RerankerConfig) -> None:
        self.config = config
        self._tokenizer = None
        self._model = None
        self.cold_start_ms: float | None = None

    def score(
        self,
        pairs: Sequence[tuple[str, str]],
        *,
        batch_size: int,
        max_length: int,
    ) -> Sequence[float]:
        self._load()
        if self._tokenizer is None or self._model is None:
            raise RuntimeError("reranker backend did not load")

        scores: list[float] = []
        for start in range(0, len(pairs), batch_size):
            batch = pairs[start : start + batch_size]
            scores.extend(self._score_batch(batch, max_length=max_length))
        return scores

    def _load(self) -> None:
        if self._model is not None:
            return
        started = perf_counter()
        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "reranker dependencies are missing; install requirements-reranker.txt"
            ) from exc

        self._tokenizer = AutoTokenizer.from_pretrained(
            self.config.model_id,
            revision=self.config.revision,
        )
        model = AutoModelForSequenceClassification.from_pretrained(
            self.config.model_id,
            revision=self.config.revision,
        ).to(self.config.device)
        if self.config.precision == "fp16":
            model = model.half()
        self._model = model.eval()
        self.cold_start_ms = (perf_counter() - started) * 1000

    def _score_batch(self, pairs: Sequence[tuple[str, str]], *, max_length: int) -> list[float]:
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError(
                "reranker dependencies are missing; install requirements-reranker.txt"
            ) from exc
        if self._tokenizer is None or self._model is None:
            raise RuntimeError("reranker backend did not load")

        queries = [pair[0] for pair in pairs]
        passages = [pair[1] for pair in pairs]
        encoded = self._tokenizer(
            queries,
            passages,
            padding=True,
            truncation=True,
            max_length=max_length,
            return_tensors="pt",
        )
        encoded = {name: tensor.to(self.config.device) for name, tensor in encoded.items()}
        with torch.no_grad():
            logits = self._model(**encoded).logits.view(-1).float().cpu().tolist()
        return [float(score) for score in logits]
