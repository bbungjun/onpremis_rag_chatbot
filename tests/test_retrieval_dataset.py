import json
import re
from pathlib import Path

from app.chunking import chunk_text


def load_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_holdout_contains_fifty_new_natural_policy_questions_with_valid_gold():
    # Given
    holdout = load_rows(Path("datasets/eval/qa_holdout.jsonl"))
    development = load_rows(Path("datasets/eval/qa_set.jsonl"))
    parent_ids = {
        chunk["id"]
        for chunk in chunk_text(Path("datasets/docs/regulations.md").read_text(encoding="utf-8"))
        if chunk["type"] == "parent"
    }

    # Then
    assert len(holdout) == 50
    assert len({row["id"] for row in holdout}) == 50
    assert len({row["question"] for row in holdout}) == 50
    assert {row["question"] for row in holdout}.isdisjoint({row["question"] for row in development})
    assert all(not re.search(r"제\s*\d+\s*조", row["question"]) for row in holdout)
    assert all(row["type"] == "일상어" for row in holdout)
    assert all(row["gold_jo"] and set(row["gold_jo"]) <= parent_ids for row in holdout)
    assert all(row["answer"].strip() for row in holdout)
