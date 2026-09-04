from __future__ import annotations

import datetime
import hashlib
import importlib.metadata
import subprocess
from collections.abc import Sequence
from pathlib import Path

import httpx

from app.config import Settings
from app.reranker import RerankerConfig
from app.retrieval_search import FusionWeights


def collect_run_metadata(
    *,
    run_id: str,
    split: str,
    dataset_path: Path,
    document_path: Path,
    case_count: int,
    methods: Sequence[str],
    top_k: int,
    candidate_limit: int,
    rerank_candidate_limit: int,
    weights: FusionWeights,
    reranker_config: RerankerConfig | None,
    reranker_cold_start_ms: float | None,
    latency_repetitions: int,
    seed: int,
    settings: Settings,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "started_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "split": split,
        "dataset_path": dataset_path.as_posix(),
        "dataset_sha256": _sha256(dataset_path),
        "document_sha256": _sha256(document_path),
        "case_count": case_count,
        "methods": list(methods),
        "top_k": top_k,
        "candidate_limit": candidate_limit,
        "rerank_candidate_limit": rerank_candidate_limit,
        "embedding_model": settings.embedding_model,
        "reranker_model": reranker_config.model_id if reranker_config else None,
        "reranker_revision": reranker_config.revision if reranker_config else None,
        "reranker_cold_start_ms": reranker_cold_start_ms,
        "qdrant_client_version": importlib.metadata.version("qdrant-client"),
        "qdrant_server_version": _qdrant_server_version(settings.qdrant_url),
        "fusion_weights": {"dense": weights.dense, "sparse": weights.sparse},
        "device": reranker_config.device if reranker_config else None,
        "precision": reranker_config.precision if reranker_config else None,
        "batch_size": reranker_config.batch_size if reranker_config else None,
        "latency_repetitions": latency_repetitions,
        "seed": seed,
        "git_commit": _git_commit(),
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _qdrant_server_version(url: str) -> str:
    response = httpx.get(url.rstrip("/"), timeout=5)
    response.raise_for_status()
    value = response.json().get("version")
    return str(value or "unknown")


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "unavailable"
    return result.stdout.strip() or "unavailable"
