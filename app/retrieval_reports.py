from __future__ import annotations

import json
import os
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from statistics import fmean

from app.retrieval_evaluation import EvaluationRecord
from app.retrieval_metrics import paired_bootstrap


def create_run_directory(root: Path, run_id: str) -> Path:
    if (
        not run_id.strip()
        or run_id != run_id.strip()
        or run_id in {".", ".."}
        or "/" in run_id
        or "\\" in run_id
        or Path(run_id).is_absolute()
    ):
        raise ValueError("run_id must be a single safe directory name")
    output = root / run_id
    output.mkdir(parents=True, exist_ok=False)
    (output / "results.jsonl").touch()
    return output


def write_run_metadata(path: Path, metadata: Mapping[str, object]) -> None:
    forbidden = {"question", "questions", "credential", "credentials", "api_key"}
    if forbidden.intersection(metadata):
        raise ValueError("run metadata contains forbidden raw or secret fields")
    path.write_text(
        json.dumps(dict(metadata), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def append_result(path: Path, record: EvaluationRecord) -> None:
    payload = _record_payload(record)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def render_summary(
    records: Sequence[EvaluationRecord],
    *,
    baseline: str = "dense",
    seed: int = 20260831,
    samples: int = 10_000,
) -> str:
    grouped: dict[str, list[EvaluationRecord]] = defaultdict(list)
    for record in records:
        grouped[record.method].append(record)

    lines = [
        "# Retrieval evaluation summary",
        "",
        "| 방식 | Recall@1 | Recall@3 | Recall@5 | MRR@5 | nDCG@5 "
        "| 평균 검색(ms) | P50 검색(ms) | P95 검색(ms) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for method, method_records in grouped.items():
        successful = [record for record in method_records if record.metrics is not None]
        errors = len(method_records) - len(successful)
        if successful:
            values = [_search_ms(record) for record in successful]
            row = (
                f"| {method} | {_mean_metric(successful, 'recall_at_1'):.4f} | "
                f"{_mean_metric(successful, 'recall_at_3'):.4f} | "
                f"{_mean_metric(successful, 'recall_at_5'):.4f} | "
                f"{_mean_metric(successful, 'reciprocal_rank_at_5'):.4f} | "
                f"{_mean_metric(successful, 'ndcg_at_5'):.4f} | "
                f"{fmean(values):.2f} | {_percentile(values, 0.50):.2f} | "
                f"{_percentile(values, 0.95):.2f} |"
            )
        else:
            row = f"| {method} | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |"
        lines.append(row)
        if errors:
            lines.append(f"\n- {method}: 오류 {errors}건 (성공 평균에서 제외)")

    lines.extend(["", "## Candidate recall upper bound", ""])
    for method, method_records in grouped.items():
        values = [
            record.candidate_recall
            for record in method_records
            if record.candidate_recall is not None
        ]
        if values:
            lines.append(f"- {method}: {fmean(values):.4f}")

    lines.extend(["", "## Paired Recall@5 differences", ""])
    baseline_by_case = _successful_by_case(grouped.get(baseline, []))
    for method, method_records in grouped.items():
        if method == baseline:
            continue
        compared = _successful_by_case(method_records)
        shared = sorted(baseline_by_case.keys() & compared.keys())
        if not shared:
            lines.append(f"- {method} vs {baseline}: 비교 가능한 paired case 없음")
            continue
        before = [_metric(baseline_by_case[case_id], "recall_at_5") for case_id in shared]
        after = [_metric(compared[case_id], "recall_at_5") for case_id in shared]
        interval = paired_bootstrap(before, after, samples=samples, seed=seed)
        wins = sum(new > old for old, new in zip(before, after, strict=True))
        losses = sum(new < old for old, new in zip(before, after, strict=True))
        ties = len(shared) - wins - losses
        lines.append(
            f"- {method} vs {baseline}: {interval.mean_difference:+.4f}, "
            f"95% CI [{interval.lower:+.4f}, {interval.upper:+.4f}], "
            f"승/패/동률 {wins}/{losses}/{ties} (n={len(shared)})"
        )
    return "\n".join(lines) + "\n"


def _record_payload(record: EvaluationRecord) -> dict[str, object]:
    payload = asdict(record)
    metrics = payload.pop("metrics")
    if isinstance(metrics, dict):
        payload.update(metrics)
    return payload


def _successful_by_case(records: Sequence[EvaluationRecord]) -> dict[str, EvaluationRecord]:
    return {record.case_id: record for record in records if record.metrics is not None}


def _metric(record: EvaluationRecord, name: str) -> float:
    if record.metrics is None:
        raise ValueError("record has no metrics")
    return float(getattr(record.metrics, name))


def _mean_metric(records: Sequence[EvaluationRecord], name: str) -> float:
    return fmean(_metric(record, name) for record in records)


def _search_ms(record: EvaluationRecord) -> float:
    return record.timing_ms.get("qdrant_search", 0.0) + record.timing_ms.get("reranker", 0.0)


def _percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(values)
    index = min(round((len(ordered) - 1) * quantile), len(ordered) - 1)
    return ordered[index]
