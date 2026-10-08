"""Freeze real RAG prompts, then compare local generators without repeating retrieval."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from time import perf_counter

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adversarial_eval import (
    cited_articles,
    fabricated_citations,
    is_refusal,
    load_parent_texts,
    score_record,
    summarize,
)
from app.config import Settings
from app.qwen_client import _system_content

MODELS = ("qwen3:4b-instruct", "exaone3.5:7.8b")
BASE_URL = "http://localhost:11434"
REPORT_ROOT = Path("reports/local-judge")
DOCS = [
    Path("datasets/docs/regulations.md"),
    Path("datasets/eval/adversarial_docs/injected_regulations.md"),
]


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_json(path, value):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class Capture:
    label = "Prompt capture"
    model_name = "capture-only"

    def __init__(self):
        self.messages = []

    def generate(self, system_prompt, user_prompt):
        self.messages.append((system_prompt, user_prompt))
        return "captured"


def capture_case(case, *, settings, answer):
    capture = Capture()
    started = perf_counter()
    result = answer(case["question"], settings.retrieval_top_k, settings=settings, llm=capture)
    elapsed = (perf_counter() - started) * 1000
    if len(capture.messages) != 1:
        raise ValueError(f"{case['id']}: expected exactly one generation prompt")
    system_prompt, user_prompt = capture.messages[0]
    return {
        "case": case,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "sources": result["sources"],
        "retrieval_ms": elapsed,
        "prompt_sha256": digest([_system_content(system_prompt), user_prompt]),
    }


def make_request(frozen, model, options):
    # Both selected models are non-thinking. No unsupported thinking flag is sent.
    return {
        "model": model,
        "stream": False,
        "keep_alive": "10m",
        "options": dict(options),
        "messages": [
            {"role": "system", "content": _system_content(frozen["system_prompt"])},
            {"role": "user", "content": frozen["user_prompt"]},
        ],
    }


def summarize_generation(rows):
    answered = [row for row in rows if row["status"] == "answered"]
    times = sorted(row["elapsed_ms"] for row in answered)
    return {
        "total": len(rows),
        "answered": len(answered),
        "errors": len(rows) - len(answered),
        "length_stops": sum(row.get("done_reason") == "length" for row in rows),
        "answered_mean_ms": fmean(times) if times else None,
        "answered_p95_ms": times[round((len(times) - 1) * 0.95)] if times else None,
        "p95_method": "sorted(values)[round((n-1)*0.95)]",
    }


def validate_pairs(frozen, first, second):
    if not frozen or len(first) != len(frozen) or len(second) != len(frozen):
        raise ValueError("Incomplete comparison")
    for prompt, a, b in zip(frozen, first, second, strict=True):
        sources = [source["chunk_id"] for source in prompt["sources"]]
        for row in (a, b):
            if (
                row["case"] != prompt["case"]
                or row["prompt_sha256"] != prompt["prompt_sha256"]
                or row["source_ids"] != sources
            ):
                raise ValueError("Model requests were not paired")


def validate_collection(name, expected_parents):
    from qdrant_client import QdrantClient

    client = QdrantClient(url="http://localhost:6333")
    points, offset = client.scroll(name, limit=1000, with_payload=True, with_vectors=False)
    if offset is not None:
        raise ValueError("Unexpected collection size; inspect before comparison")
    snapshot = sorted([point.payload for point in points], key=lambda p: p["chunk_id"])
    observed = {p["parent_id"]: p["parent_text"] for p in snapshot}
    if observed != expected_parents:
        raise ValueError(f"{name}: indexed parent text differs from the local evaluation corpus")
    client.close()
    return {
        "point_count": len(points),
        "parent_count": len(observed),
        "payload_sha256": digest(snapshot),
    }


def freeze(output):
    from dotenv import load_dotenv

    from app.rag_pipeline import answer_question

    load_dotenv(override=False)
    settings = replace(
        Settings.from_env(), ollama_base_url=BASE_URL, qdrant_url="http://localhost:6333"
    )
    if settings.llm_model != MODELS[0]:
        raise ValueError("Current baseline changed; review model choice before running")
    output.mkdir(parents=True, exist_ok=False)
    ordinary = Path("datasets/eval/qa_holdout.jsonl")
    adversarial = Path("datasets/eval/qa_adversarial_holdout.jsonl")
    collections = {
        "normal": (settings.qdrant_collection, load_parent_texts(DOCS[:1])),
        "adversarial": ("llmenhance_adversarial", load_parent_texts(DOCS)),
    }
    options = {
        "temperature": settings.temperature,
        "num_ctx": settings.num_ctx,
        "num_predict": settings.num_predict,
        "seed": 42,
        "repeat_penalty": 1.0,
    }
    with httpx.Client(base_url=BASE_URL, trust_env=False, timeout=30) as client:
        tags = client.get("/api/tags").json()
        version = client.get("/api/version").json()
    metadata = {
        "created_at": datetime.now(UTC).isoformat(),
        "models": MODELS,
        "options": options,
        "top_k": settings.retrieval_top_k,
        "search": "RRF + parent expansion",
        "embedding_model": settings.embedding_model,
        "tags": tags,
        "ollama": version,
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "git_status": subprocess.check_output(["git", "status", "--short"], text=True),
        "source_sha256": {
            p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path("app").glob("*.py"))
        },
        "dataset_sha256": {
            p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [ordinary, adversarial, *DOCS]
        },
        "collections": {
            key: validate_collection(name, parents) for key, (name, parents) in collections.items()
        },
        "limitations": [
            "synthetic reused evaluation sets",
            "single sequential run per model",
            "generation-only latency; retrieval frozen separately",
            "4B vs 7.8B",
        ],
    }
    write_json(output / "manifest.json", metadata)
    for suite, dataset in [("normal", ordinary), ("adversarial", adversarial)]:
        active = replace(settings, qdrant_collection=collections[suite][0])
        for case in read_rows(dataset):
            frozen = capture_case(case, settings=active, answer=answer_question)
            frozen["suite"] = suite
            append_json(output / "prompts.jsonl", frozen)
            print(f"captured {suite} {case['id']}", flush=True)
    metadata["prompts_sha256"] = hashlib.sha256((output / "prompts.jsonl").read_bytes()).hexdigest()
    write_json(output / "manifest.json", metadata)


def unload(client, model):
    response = client.post("/api/generate", json={"model": model, "keep_alive": 0})
    response.raise_for_status()


def generate(output, model):
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    if (
        hashlib.sha256((output / "prompts.jsonl").read_bytes()).hexdigest()
        != manifest["prompts_sha256"]
    ):
        raise ValueError("Frozen prompts were changed")
    rows = read_rows(output / "prompts.jsonl")
    target = output / model.replace(":", "-")
    target.mkdir(exist_ok=False)
    with httpx.Client(base_url=BASE_URL, timeout=180, trust_env=False) as client:
        warm = client.post(
            "/api/chat",
            json=make_request(
                {"system_prompt": "한국어로 짧게 답하라.", "user_prompt": "준비되었나요?"},
                model,
                {**manifest["options"], "num_predict": 32},
            ),
        )
        warm.raise_for_status()
        write_json(target / "warmup.json", warm.json())
        write_json(target / "loaded_before.json", client.get("/api/ps").json())
        try:
            for frozen in rows:
                record = {
                    "case": frozen["case"],
                    "suite": frozen["suite"],
                    "prompt_sha256": frozen["prompt_sha256"],
                    "source_ids": [s["chunk_id"] for s in frozen["sources"]],
                }
                started = perf_counter()
                try:
                    response = client.post(
                        "/api/chat", json=make_request(frozen, model, manifest["options"])
                    )
                    response.raise_for_status()
                    raw = response.json()
                    answer = raw["message"]["content"].strip()
                    record.update(
                        status="answered" if answer else "empty_answer",
                        answer=answer,
                        done_reason=raw.get("done_reason"),
                        raw=raw,
                    )
                except (httpx.HTTPError, ValueError, KeyError) as exc:
                    record.update(status="answer_error", answer_error=str(exc))
                record["elapsed_ms"] = (perf_counter() - started) * 1000
                append_json(target / "answers.jsonl", record)
                print(
                    f"{model} {frozen['suite']} {frozen['case']['id']}: "
                    f"{record['status']} {record['elapsed_ms']:.0f}ms",
                    flush=True,
                )
            write_json(target / "loaded_after.json", client.get("/api/ps").json())
        finally:
            unload(client, model)


def report(output):
    all_models = {}
    parents = load_parent_texts(DOCS)
    for model in MODELS:
        target = output / model.replace(":", "-")
        rows = read_rows(target / "answers.jsonl")
        all_models[model] = rows
        summary = {
            suite: summarize_generation([r for r in rows if r["suite"] == suite])
            for suite in ("normal", "adversarial")
        }
        attacks = [score_record(r, parents) for r in rows if r["suite"] == "adversarial"]
        summary["security"] = summarize(attacks)
        normal = [r for r in rows if r["suite"] == "normal" and r["status"] == "answered"]
        summary["normal_rule_checks"] = {
            "refusal_marker_cases": sum(is_refusal(r["answer"]) for r in normal),
            "no_article_citation_cases": sum(not cited_articles(r["answer"]) for r in normal),
            "fabricated_article_cases": sum(
                bool(fabricated_citations(r["answer"], r["source_ids"], parents)) for r in normal
            ),
        }
        write_json(target / "summary.json", summary)
        write_json(target / "security_scores.json", attacks)
    first, second = (all_models[m] for m in MODELS)
    validate_pairs(read_rows(output / "prompts.jsonl"), first, second)
    blind, mapping = [], []
    for a, b in zip(first, second, strict=True):
        if a["case"] != b["case"] or a["prompt_sha256"] != b["prompt_sha256"]:
            raise ValueError("Model requests were not paired")
        if a["suite"] != "normal":
            continue
        order = [0, 1] if secrets.randbelow(2) else [1, 0]
        blind.append(
            {
                "case": a["case"],
                "source_ids": a["source_ids"],
                "A": [a, b][order[0]].get("answer", "ERROR"),
                "B": [a, b][order[1]].get("answer", "ERROR"),
            }
        )
        mapping.append({"id": a["case"]["id"], "A": MODELS[order[0]], "B": MODELS[order[1]]})
    # Exclusive creation prevents silently changing blind labels after review has begun.
    for name, value in [("blind_review.json", blind), ("blind_mapping.json", mapping)]:
        with (output / name).open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "generate", "report"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", choices=MODELS)
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(REPORT_ROOT.resolve()):
        parser.error("output must be inside reports/local-judge")
    if args.phase == "generate" and args.model is None:
        parser.error("generate requires --model")
    if args.phase == "freeze":
        freeze(args.output)
    elif args.phase == "generate":
        generate(args.output, args.model)
    else:
        report(args.output)


if __name__ == "__main__":
    main()
