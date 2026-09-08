"""Freeze retrieval, then run sequential Qwen and separate EXAONE intent ablations."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.embeddings import embed_text  # noqa: E402
from app.intent_ablation import (  # noqa: E402
    JUDGE_SYSTEM,
    append_record,
    digest,
    freeze_case,
    paired_summary,
    read_jsonl,
    run_generation,
    run_judging,
)
from app.local_judge import validate_judge_model  # noqa: E402
from app.qwen_client import PROMPT_INJECTION_GUARD, resolve_think  # noqa: E402
from app.rag_pipeline import SYSTEM_PROMPT, _search_top_k_for_parent_expansion  # noqa: E402
from app.sparse import text_to_sparse  # noqa: E402
from app.vector_store import search_chunks  # noqa: E402
from scripts.eval_intent import load_cases, load_gold_labels  # noqa: E402

ROOT = Path("reports/local-judge/intent-ablation")
INPUTS = (
    "datasets/eval/qa_set.jsonl",
    "datasets/eval/intent_robustness.jsonl",
    "datasets/eval/intent_gold.jsonl",
    "datasets/docs/regulations.md",
    "app/question_interpreter.py",
    "app/rag_pipeline.py",
    "app/qwen_client.py",
    "app/intent_ablation.py",
    "scripts/compare_intent.py",
)


def run_path(name: str) -> Path:
    if not name or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in name):
        raise ValueError("run name must contain lowercase letters, digits, hyphens, underscores")
    path = ROOT / name
    path.resolve().relative_to(ROOT.resolve())
    return path


def hashes() -> dict:
    return {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in INPUTS}


def get_json(url: str) -> dict:
    response = httpx.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def release(base: str, model: str) -> None:
    response = httpx.post(
        base.rstrip("/") + "/api/generate", json={"model": model, "keep_alive": 0}, timeout=60
    )
    response.raise_for_status()


def chat(base: str, model: str, options: dict, think: str):
    def call(system: str, user: str, seed: int) -> dict:
        request = {
            "model": model,
            "stream": False,
            "keep_alive": "15m",
            "messages": [
                {"role": "system", "content": system + "\n\n" + PROMPT_INJECTION_GUARD},
                {"role": "user", "content": user},
            ],
            "options": {**options, "seed": seed},
        }
        thinking = resolve_think(model, think)
        if thinking is not None:
            request["think"] = thinking
        response = httpx.post(base.rstrip("/") + "/api/chat", json=request, timeout=180)
        response.raise_for_status()
        result = response.json()
        if not result.get("done"):
            raise ValueError("Ollama did not complete response")
        return result

    return call


def snapshot(path: Path, base: str, stage: str) -> None:
    append_record(
        path / "runtime.jsonl",
        {
            "at": datetime.datetime.now(datetime.UTC).isoformat(),
            "stage": stage,
            "ollama_ps": get_json(base.rstrip("/") + "/api/ps"),
        },
    )


def prepare(path: Path, settings: Settings, repeats: int) -> None:
    path.mkdir(parents=True, exist_ok=False)
    cases = load_cases(INPUTS[0]) + load_cases(INPUTS[1])
    gold = load_gold_labels(INPUTS[2])
    ids = [c["id"] for c in cases]
    if len(set(ids)) != len(ids) or set(ids) != set(gold):
        raise ValueError("dataset IDs and gold IDs must match exactly")
    if repeats < 1 or settings.retrieval_top_k < 1:
        raise ValueError("repeats and top_k must be positive")
    base = settings.ollama_base_url.rstrip("/")
    safe_settings = {
        k: v for k, v in asdict(settings).items() if k not in ("ollama_base_url", "qdrant_url")
    }
    manifest = {
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "input_sha256": hashes(),
        "settings": safe_settings,
        "repeats": repeats,
        "case_count": len(cases),
        "label_review": "AI authored; independent human review pending",
        "system_sha256": digest(SYSTEM_PROMPT),
        "guard_sha256": digest(PROMPT_INJECTION_GUARD),
        "ollama_version": get_json(base + "/api/version"),
        "model_catalog": get_json(base + "/api/tags"),
        "qdrant_collection": get_json(
            settings.qdrant_url.rstrip("/") + "/collections/" + settings.qdrant_collection
        ),
    }
    (path / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    def retrieve(question):
        dense = embed_text(base, settings.embedding_model, question)
        sparse = text_to_sparse(question)
        return search_chunks(
            settings.qdrant_url,
            settings.qdrant_collection,
            dense,
            sparse,
            _search_top_k_for_parent_expansion(settings.retrieval_top_k),
        )

    snapshot(path, base, "before_retrieval")
    try:
        for case in cases:
            item = freeze_case(case, gold[case["id"]], settings, retrieve)
            append_record(path / "contexts.jsonl", item)
            print(f"freeze {case['id']}: {len(item['parents'])} parents", flush=True)
        manifest["contexts_sha256"] = hashlib.sha256(
            (path / "contexts.jsonl").read_bytes()
        ).hexdigest()
        (path / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    finally:
        snapshot(path, base, "after_retrieval")
        release(base, settings.embedding_model)


def verified_inputs(path: Path, settings: Settings) -> tuple[dict, list]:
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    if manifest["input_sha256"] != hashes():
        raise ValueError("source or dataset changed; use a new run")
    actual = hashlib.sha256((path / "contexts.jsonl").read_bytes()).hexdigest()
    if manifest.get("contexts_sha256") != actual:
        raise ValueError("contexts incomplete or modified")
    current = {
        k: v for k, v in asdict(settings).items() if k not in ("ollama_base_url", "qdrant_url")
    }
    if manifest["settings"] != current:
        raise ValueError("settings changed; use original settings or a new run")
    contexts = read_jsonl(path / "contexts.jsonl")
    if len(contexts) != manifest["case_count"]:
        raise ValueError("incomplete context preparation")
    return manifest, contexts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "generate", "judge", "summary"))
    parser.add_argument("--run", required=True)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--ids", help="Comma-separated pilot case IDs; omit to finish all")
    args = parser.parse_args(argv)
    path = run_path(args.run)
    settings = Settings.from_env()
    if args.stage == "prepare":
        prepare(path, settings, args.repeats)
        return 0
    manifest, frozen = verified_inputs(path, settings)
    base = settings.ollama_base_url
    if args.stage == "generate":
        if not settings.llm_model.startswith("qwen"):
            raise ValueError("this experiment requires the configured Qwen answer model")
        ids = set(args.ids.split(",")) if args.ids else None
        if ids and not ids.issubset({x["case"]["id"] for x in frozen}):
            raise ValueError("unknown pilot IDs")
        call = chat(
            base,
            settings.llm_model,
            {
                "temperature": settings.temperature,
                "num_ctx": settings.num_ctx,
                "num_predict": settings.num_predict,
            },
            settings.llm_think,
        )
        try:
            snapshot(path, base, "before_generation")
            run_generation(
                frozen, path / "answers.jsonl", call, repeats=manifest["repeats"], ids=ids
            )
            snapshot(path, base, "after_generation")
        finally:
            release(base, settings.llm_model)
    elif args.stage == "judge":
        model = validate_judge_model("exaone3.5:7.8b")
        config = {
            "model": model,
            "temperature": 0.0,
            "num_ctx": 4096,
            "num_predict": 768,
            "system_sha256": digest(JUDGE_SYSTEM),
            "seed": 42,
        }
        config_path = path / "judge_config.json"
        if config_path.exists() and json.loads(config_path.read_text()) != config:
            raise ValueError("judge settings changed")
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        call = chat(
            base, model, {k: config[k] for k in ("temperature", "num_ctx", "num_predict")}, "auto"
        )
        try:
            snapshot(path, base, "before_judge")
            run_judging(frozen, path / "answers.jsonl", path / "judgments.jsonl", call)
            snapshot(path, base, "after_judge")
        finally:
            release(base, model)
    summary = paired_summary(
        read_jsonl(path / "answers.jsonl"), read_jsonl(path / "judgments.jsonl")
    )
    summary["expected_answers"] = len(frozen) * manifest["repeats"] * 3
    (path / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
