"""Paired local evidence experiment; no service index is read or modified."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import subprocess
import sys
import types
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

import httpx
from qdrant_client import QdrantClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import rag_pipeline, vector_store
from app.chunking import chunk_text
from app.embeddings import embed_text
from app.evidence_context import pack_sources, rank_sources
from app.question_interpreter import interpret_question
from app.qwen_client import _system_content
from app.sparse import text_to_sparse

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "1359a0a"
BUDGET = 3891


def read_rows(path):
    return [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s.strip()]


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append(path, value):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def baseline_module():
    code = subprocess.check_output(
        ["git", "show", f"{BASELINE}:app/rag_pipeline.py"], cwd=ROOT
    ).decode("utf-8")
    module = types.ModuleType("evidence_baseline")
    sys.modules[module.__name__] = module
    exec(compile(code, "frozen_baseline.py", "exec"), module.__dict__)
    return module


def compose(arm, case, hits, baseline):
    question = interpret_question(case["question"])

    def render(selected):
        return rag_pipeline._build_user_prompt(question, selected)

    if arm == "baseline":
        return baseline._build_context(question, hits, 5, max_prompt_chars=BUDGET)
    if arm == "combined":
        return rag_pipeline._build_context(question, hits, 5, max_prompt_chars=BUDGET)
    parents = rag_pipeline._expand_to_parents(hits, len(hits))
    if arm == "selection_only":
        selected = rank_sources(case["question"], parents)[:5]
        while len(selected) > 1 and len(render(selected)) > BUDGET:
            selected = selected[:-1]
        return selected, render(selected)
    return pack_sources(case["question"], parents[:5], BUDGET, render)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args(argv)
    if not args.output.resolve().is_relative_to(ROOT / "reports/retrieval-eval"):
        parser.error("output must be inside reports/retrieval-eval")
    if args.ollama_url not in {"http://localhost:11434", "http://127.0.0.1:11434"}:
        parser.error("experiment only supports host loopback Ollama")
    args.output.mkdir(parents=True, exist_ok=False)
    files = {
        "development": ROOT / "datasets/eval/connection_diagnostic.jsonl",
        "validation": ROOT / "datasets/eval/connection_validation.jsonl",
        "legacy_regression": ROOT / "datasets/eval/qa_holdout.jsonl",
    }
    groups = {group: read_rows(path) for group, path in files.items()}
    chunks = chunk_text((ROOT / "datasets/docs/regulations.md").read_text(encoding="utf-8"))
    parents = {c["id"]: c["text"] for c in chunks if c["type"] == "parent"}
    children = [c for c in chunks if c["type"] == "child"]
    for cases in groups.values():
        for case in cases:
            for fact in case.get("context_facts", []):
                if not any(fact in parents[k] for k in case["gold_jo"]):
                    raise ValueError(f"unsupported label {case['id']}: {fact}")
    tags = httpx.get(args.ollama_url + "/api/tags", timeout=10).json()["models"]
    embedding = next(m for m in tags if m["name"] == "bge-m3:latest")
    generator = next(m for m in tags if m["name"] == "qwen3:4b-instruct")
    metadata = {
        "started_at": datetime.now(UTC).isoformat(),
        "baseline": BASELINE,
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "datasets": {k: digest(v) for k, v in files.items()},
        "sources": {
            p: digest(ROOT / p)
            for p in [
                "app/evidence_context.py",
                "app/rag_pipeline.py",
                "app/question_interpreter.py",
                "app/chunking.py",
                "app/vector_store.py",
                "app/sparse.py",
                "scripts/evaluate_evidence_context.py",
            ]
        },
        "document_sha256": digest(ROOT / "datasets/docs/regulations.md"),
        "backend": "Qdrant Local :memory:",
        "embedding": embedding,
        "generator": generator if args.generate else None,
        "judge": "not used",
        "qdrant_client": importlib.metadata.version("qdrant-client"),
        "ollama": httpx.get(args.ollama_url + "/api/version", timeout=10).json(),
        "top_k": 5,
        "candidate_limit": 20,
        "prompt_char_budget": BUDGET,
        "generation_options": {"temperature": 0, "seed": 42, "num_ctx": 4096, "num_predict": 512},
        "sample_counts": {k: len(v) for k, v in groups.items()},
    }
    write_json(args.output / "run.json", metadata)
    write_json(args.output / "frozen_cases.json", groups)
    cache_path = ROOT / "reports/retrieval-eval/bge-m3-synthetic-cache.json"
    key = metadata["document_sha256"] + embedding["digest"]
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    if cache.get("key") == key:
        vectors = cache["vectors"]
    else:
        vectors = []
        for start in range(0, len(children), 16):
            response = httpx.post(
                args.ollama_url + "/api/embed",
                timeout=120,
                json={
                    "model": "bge-m3",
                    "input": [c["text"] for c in children[start : start + 16]],
                    "truncate": False,
                },
            )
            response.raise_for_status()
            vectors.extend(response.json()["embeddings"])
            print("embedded", len(vectors), "/", len(children), flush=True)
        write_json(cache_path, {"key": key, "vectors": vectors})
    client = QdrantClient(":memory:")
    baseline = baseline_module()
    summary = defaultdict(lambda: defaultdict(int))
    generation = []
    with patch.object(vector_store, "QdrantClient", return_value=client):
        vector_store.ensure_collection("audit", "evidence", len(vectors[0]))
        points = []
        for child, vector in zip(children, vectors, strict=True):
            points.append(
                {
                    "id": str(uuid5(NAMESPACE_URL, child["id"])),
                    "dense": vector,
                    "sparse": text_to_sparse(child["text"]),
                    "payload": {
                        **child["metadata"],
                        "chunk_id": child["id"],
                        "parent_id": child["parent_id"],
                        "text": child["text"],
                        "parent_text": parents[child["parent_id"]],
                        "document_id": "doc:regulations",
                        "source_path": "datasets/docs/regulations.md",
                        "title": "regulations.md",
                        "type": "child",
                    },
                }
            )
        vector_store.upsert_chunk_vectors("audit", "evidence", points)
        for group, cases in groups.items():
            for case in cases:
                question = interpret_question(case["question"]).retrieval_question
                dense = embed_text(args.ollama_url, "bge-m3", question)
                hits = vector_store.search_chunks(
                    "audit", "evidence", dense, text_to_sparse(question), 20
                )
                append(
                    args.output / "retrieval.jsonl", {"group": group, "case": case, "hits": hits}
                )
                pair = {}
                for arm in ("baseline", "selection_only", "compaction_only", "combined"):
                    started = perf_counter()
                    selected, prompt = compose(arm, case, hits, baseline)
                    elapsed = (perf_counter() - started) * 1000
                    source_ids = [s.chunk_id for s in selected]
                    gold_present = bool(case["gold_jo"]) and set(case["gold_jo"]) <= set(source_ids)
                    facts_present = bool(case.get("context_facts")) and all(
                        f in prompt for f in case.get("context_facts", [])
                    )
                    row = {
                        "group": group,
                        "id": case["id"],
                        "kind": case.get("kind", "control"),
                        "arm": arm,
                        "gold_all": gold_present,
                        "facts_all": facts_present,
                        "source_ids": source_ids,
                        "prompt_chars": len(prompt),
                        "over_budget": len(prompt) > BUDGET,
                        "assembly_ms": elapsed,
                    }
                    append(args.output / "results.jsonl", row)
                    append(
                        args.output / "prompts.jsonl",
                        {**row, "question": case["question"], "prompt": prompt},
                    )
                    key = f"{group}/{row['kind']}/{arm}"
                    summary[key]["n"] += 1
                    for metric in ("gold_all", "facts_all", "over_budget"):
                        summary[key][metric] += row[metric]
                    pair[arm] = {**row, "question": case["question"], "prompt": prompt}
                if group == "validation":
                    generation.append(pair)
                print(
                    group,
                    case["id"],
                    pair["baseline"]["gold_all"],
                    "->",
                    pair["combined"]["gold_all"],
                    flush=True,
                )
    client.close()
    write_json(args.output / "summary.json", summary)
    if args.generate:
        for index, pair in enumerate(generation):
            order = ("baseline", "combined") if index % 2 == 0 else ("combined", "baseline")
            for arm in order:
                row = pair[arm]
                started = perf_counter()
                if not row["prompt"]:
                    payload = {
                        "message": {"content": rag_pipeline.FALLBACK_ANSWER},
                        "done_reason": "no_context",
                    }
                else:
                    response = httpx.post(
                        args.ollama_url + "/api/chat",
                        timeout=180,
                        json={
                            "model": "qwen3:4b-instruct",
                            "stream": False,
                            "messages": [
                                {
                                    "role": "system",
                                    "content": _system_content(baseline.SYSTEM_PROMPT),
                                },
                                {"role": "user", "content": row["prompt"]},
                            ],
                            "options": metadata["generation_options"],
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
                answer = payload["message"]["content"]
                append(
                    args.output / "answers.jsonl",
                    {
                        k: v
                        for k, v in {
                            **row,
                            "answer": answer,
                            "elapsed_ms": (perf_counter() - started) * 1000,
                            "done_reason": payload.get("done_reason"),
                            "eval_count": payload.get("eval_count"),
                            "prompt_eval_count": payload.get("prompt_eval_count"),
                        }.items()
                        if k != "prompt"
                    },
                )
                print("generated", row["id"], arm, flush=True)
    metadata["finished_at"] = datetime.now(UTC).isoformat()
    write_json(args.output / "run.json", metadata)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
