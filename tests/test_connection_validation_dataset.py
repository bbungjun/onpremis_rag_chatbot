import hashlib
import json
from collections import Counter
from pathlib import Path

from app.chunking import chunk_text


def test_frozen_validation_has_distinct_multi_single_and_absent_question_groups():
    path = Path("datasets/eval/connection_validation.jsonl")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "725b3c0e733b0fda18d97d57f4ac14b47f9e1aded76b1a50d74d8c8085ff0d40"
    )
    rows = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines()]
    dev = [
        json.loads(s)
        for s in Path("datasets/eval/connection_diagnostic.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert Counter(r["kind"] for r in rows) == {"multi": 12, "control": 4, "unanswerable": 4}
    assert len({r["id"] for r in rows}) == 20
    assert {r["question"] for r in rows}.isdisjoint({r["question"] for r in dev})
    parents = {
        c["id"]: c["text"]
        for c in chunk_text(Path("datasets/docs/regulations.md").read_text(encoding="utf-8"))
        if c["type"] == "parent"
    }
    for row in rows:
        assert set(row["requirements"]) == set(row["gold_jo"])
        if row["kind"] == "unanswerable":
            assert row["gold_jo"] == []
            assert row["expected_behavior"] == "document_not_confirmed"
        else:
            assert len(row["gold_jo"]) >= (2 if row["kind"] == "multi" else 1)
            assert row["context_facts"]
            assert all(any(f in parents[p] for p in row["gold_jo"]) for f in row["context_facts"])
