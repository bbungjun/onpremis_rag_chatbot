"""Prospective A/B stress generation and a conservative promotion gate (evaluation only)."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.embeddings import embed_text  # noqa: E402
from app.intent_ablation import append_record, digest, freeze_case, read_jsonl  # noqa: E402
from app.question_interpreter import interpret_question  # noqa: E402
from app.sparse import text_to_sparse  # noqa: E402
from app.vector_store import search_chunks  # noqa: E402
from scripts.compare_intent import chat, get_json, release, snapshot  # noqa: E402

DATASET = Path("datasets/eval/intent_ab_boundary.jsonl")
ROOT = Path("reports/local-judge/intent-ab-promotion")
GENERATOR_FILES = (
    DATASET,
    Path(__file__),
    Path("app/question_interpreter.py"),
    Path("app/rag_pipeline.py"),
    Path("app/intent_ablation.py"),
    Path("scripts/compare_intent.py"),
)


def require_reviews(path: Path) -> list:
    """검토 기록을 읽는다. 파일이 없거나 비어 있으면 실패한다.

    read_jsonl 은 없는 파일에 빈 리스트를 돌려주므로, 그대로 쓰면 "파일을 지웠다"와
    "검토했는데 문제가 없었다"가 구분되지 않는다. 게이트의 판정 근거가 되는 입력이므로
    조용히 비는 것을 허용하지 않는다.
    """
    if not path.exists():
        raise FileNotFoundError(f"review file is required: {path}")
    rows = read_jsonl(path)
    if not rows:
        raise ValueError(f"no review records in {path}")
    return rows


def verify_input_equal(rows: list, contexts: list) -> None:
    """검토자가 적은 input_equal 을 봉인된 프롬프트로 검산한다.

    input_equal 은 승패를 집계할지 결정하는 유일한 스위치다. 두 arm 의 프롬프트가 같은데
    다르다고 적으면, 실행 변동일 뿐인 차이가 지시문의 효과로 집계된다. 프롬프트는
    contexts.jsonl 에 해시 검증된 채로 있으므로 사람 입력을 믿지 않고 직접 비교한다.
    """
    frozen = {
        item["case"]["id"]: item["prompts"]["no_intent"] == item["prompts"]["predicted_intent"]
        for item in contexts
    }
    for row in rows:
        case_id = row["case_id"]
        if case_id not in frozen:
            raise ValueError(f"review refers to a case outside the frozen contexts: {case_id}")
        if bool(row["input_equal"]) != frozen[case_id]:
            raise ValueError(
                f"input_equal disagrees with the frozen prompts for {case_id}: "
                f"review says {row['input_equal']}, prompts say {frozen[case_id]}"
            )


def promotion_gate(history: list, boundary: list, expected: set, *, confirmation=False) -> dict:
    new_critical = []
    wins = losses = both_fail = 0
    seen = set()
    for stage, rows in (("historical", history), ("boundary", boundary)):
        local_seen = set()
        for row in rows:
            identity = (row["case_id"], row["repeat"])
            if identity in local_seen:
                raise ValueError("duplicate review")
            local_seen.add(identity)
            for arm in ("A", "B"):
                if type(row[arm]["pass"]) is not bool or not isinstance(row[arm]["critical"], list):
                    raise ValueError("invalid review contract")
                if row[arm]["pass"] and row[arm]["critical"]:
                    raise ValueError("critical errors cannot pass")
            if row["A"]["critical"] and not row["B"]["critical"]:
                new_critical.append({"stage": stage, "case_id": identity[0], "repeat": identity[1]})
            if stage == "boundary":
                seen.add(identity)
                if not row["input_equal"]:
                    wins += row["A"]["pass"] and not row["B"]["pass"]
                    losses += row["B"]["pass"] and not row["A"]["pass"]
                both_fail += not row["A"]["pass"] and not row["B"]["pass"]
    missing = sorted(expected - seen)
    extra = sorted(seen - expected)
    reasons = []
    if new_critical:
        reasons.append("new_critical_regression")
    if missing or extra:
        reasons.append("incomplete_or_unexpected_reviews")
    if not expected:
        reasons.append("empty_confirmatory_sample")
    if losses or not wins:
        reasons.append("no_consistent_changed_input_benefit")
    if not confirmation:
        reasons.append("representative_independent_confirmation_not_available")
    return {
        "decision": "hold" if reasons else "eligible",
        "reasons": reasons,
        "new_critical_failures": new_critical,
        "changed_input_wins": wins,
        "changed_input_losses": losses,
        "boundary_both_fail": both_fail,
        "missing_reviews": [list(k) for k in missing],
        "unexpected_reviews": [list(k) for k in extra],
        "expected_pairs": len(expected),
        "reviewed_pairs": len(seen),
        "production_default_changed": False,
    }


def generate_pairs(items: list, path: Path, call, *, repeats: int) -> None:
    if repeats < 1:
        raise ValueError("positive repeats required")
    existing = {}
    for r in read_jsonl(path):
        key = (r["case_id"], r["repeat"], r["arm"])
        if key in existing:
            raise ValueError("duplicate checkpoint")
        existing[key] = r
    for index, item in enumerate(items):
        for repeat in range(repeats):
            seed = int(digest(["ab-boundary-v1", item["case"]["id"], repeat])[:7], 16)
            order = ("A", "B") if (index + repeat) % 2 == 0 else ("B", "A")
            for arm in order:
                prompt = item["prompts"]["no_intent" if arm == "A" else "predicted_intent"]
                row = {
                    "case_id": item["case"]["id"],
                    "repeat": repeat,
                    "arm": arm,
                    "seed": seed,
                    "context_sha256": item["context_sha256"],
                    "prompt_sha256": digest(prompt),
                }
                key = (row["case_id"], repeat, arm)
                if key in existing:
                    if any(
                        existing[key][k] != row[k]
                        for k in ("seed", "context_sha256", "prompt_sha256")
                    ):
                        raise ValueError("checkpoint inputs changed")
                    continue
                start = perf_counter()
                try:
                    if not item["parents"]:
                        raise ValueError("no retrieved context; skip generation")
                    raw = call(item["system_prompt"], prompt, seed)
                    text = raw["message"]["content"].strip()
                    if not text:
                        raise ValueError("empty answer")
                    row.update(status="answered", answer=text, raw_response=raw)
                except Exception as exc:
                    row.update(status="generation_error", error=f"{type(exc).__name__}: {exc}")
                row["elapsed_s"] = perf_counter() - start
                append_record(path, row)
                print(f"{key}: {row['status']}", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "generate", "gate"))
    parser.add_argument("--run", required=True)
    parser.add_argument(
        "--confirmed-by",
        default=None,
        help="대표성 있는 독립 확인의 출처. 주면 승격 조건 3을 충족한 것으로 기록한다.",
    )
    args = parser.parse_args(argv)
    if not args.run or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in args.run):
        parser.error("invalid run name")
    path = ROOT / args.run
    if args.stage == "gate":
        metadata = json.loads((path / "review-metadata.json").read_text(encoding="utf-8"))
        for filename, expected_hash in metadata["artifact_sha256"].items():
            source = Path(filename)
            source.resolve().relative_to(Path("reports/local-judge").resolve())
            if hashlib.sha256(source.read_bytes()).hexdigest() != expected_hash:
                raise ValueError("reviewed artifact changed")
        # 기대 명단을 만드는 contexts.jsonl 자체가 봉인 밖에 있으면 검토자가 명단을 줄여
        # 완전성 검사를 통과시킬 수 있다. generate 단계와 같은 기준으로 검증한다.
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        contexts_path = path / "contexts.jsonl"
        if hashlib.sha256(contexts_path.read_bytes()).hexdigest() != manifest["contexts_sha256"]:
            raise ValueError("frozen context changed")
        contexts = read_jsonl(contexts_path)
        boundary = require_reviews(path / "boundary-review.jsonl")
        verify_input_equal(boundary, contexts)
        expected = {
            (x["case"]["id"], r) for x in contexts for r in range(manifest["repeats"])
        }
        result = promotion_gate(
            require_reviews(path / "historical-review.jsonl"),
            boundary,
            expected,
            confirmation=bool(args.confirmed_by),
        )
        result["confirmed_by"] = args.confirmed_by
        (path / "promotion.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    settings = Settings.from_env()
    base = settings.ollama_base_url.rstrip("/")
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in GENERATOR_FILES}
    safe_settings = {
        k: v for k, v in asdict(settings).items() if k not in ("ollama_base_url", "qdrant_url")
    }
    if args.stage == "prepare":
        path.mkdir(parents=True, exist_ok=False)
        cases = read_jsonl(DATASET)
        if len(cases) != 4 or len({r["id"] for r in cases}) != 4:
            raise ValueError("four unique preregistered cases required")
        meta = {
            "hashes": hashes,
            "settings": safe_settings,
            "repeats": 3,
            "model_catalog": get_json(base + "/api/tags"),
            "ollama_version": get_json(base + "/api/version"),
        }
        try:
            for case in cases:
                interpretation = interpret_question(case["question"])
                query = interpretation.retrieval_question

                def retrieve(_question, query=query):
                    return search_chunks(
                        settings.qdrant_url,
                        settings.qdrant_collection,
                        embed_text(base, settings.embedding_model, query),
                        text_to_sparse(query),
                        settings.retrieval_top_k * 4,
                    )

                item = freeze_case(case, interpretation.intent, settings, retrieve)
                item["retrieval_question"] = query
                append_record(path / "contexts.jsonl", item)
                print(f"prepared {case['id']}: {len(item['parents'])} parents", flush=True)
            meta["contexts_sha256"] = hashlib.sha256(
                (path / "contexts.jsonl").read_bytes()
            ).hexdigest()
            (path / "manifest.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        finally:
            release(base, settings.embedding_model)
    else:
        meta = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        if meta["hashes"] != hashes or meta["settings"] != safe_settings:
            raise ValueError("source or settings changed")
        if (
            hashlib.sha256((path / "contexts.jsonl").read_bytes()).hexdigest()
            != meta["contexts_sha256"]
        ):
            raise ValueError("frozen context changed")
        if settings.llm_model != "qwen3:4b-instruct":
            raise ValueError("preregistered Qwen model required")
        options = {k: safe_settings[k] for k in ("temperature", "num_ctx", "num_predict")}
        try:
            snapshot(path, base, "before_generation")
            generate_pairs(
                read_jsonl(path / "contexts.jsonl"),
                path / "answers.jsonl",
                chat(base, settings.llm_model, options, settings.llm_think),
                repeats=meta["repeats"],
            )
            snapshot(path, base, "after_generation")
        finally:
            release(base, settings.llm_model)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
