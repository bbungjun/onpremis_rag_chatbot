import json
import re
from pathlib import Path

import pytest

from app.adversarial_eval import CANARY, LABEL_EXPECTATIONS, load_adversarial_cases
from app.chunking import chunk_text

DEV = Path("datasets/eval/qa_adversarial_dev.jsonl")
HOLDOUT = Path("datasets/eval/qa_adversarial_holdout.jsonl")
INJECTED_DOC = Path("datasets/eval/adversarial_docs/injected_regulations.md")
REGULATIONS = Path("datasets/docs/regulations.md")


def parent_ids(*docs: Path) -> set[str]:
    ids: set[str] = set()
    for doc in docs:
        ids |= {
            chunk["id"]
            for chunk in chunk_text(doc.read_text(encoding="utf-8"))
            if chunk["type"] == "parent"
        }
    return ids


@pytest.mark.parametrize("path", [DEV, HOLDOUT])
def test_split_has_forty_cases_with_five_per_label(path):
    cases = load_adversarial_cases(path)

    assert len(cases) == 40
    assert len({case.id for case in cases}) == 40
    assert len({case.question for case in cases}) == 40
    counts = {
        label: sum(1 for case in cases if case.label == label) for label in LABEL_EXPECTATIONS
    }
    assert counts == dict.fromkeys(LABEL_EXPECTATIONS, 5)


def test_dev_and_holdout_questions_are_disjoint():
    dev = {case.question for case in load_adversarial_cases(DEV)}
    holdout = {case.question for case in load_adversarial_cases(HOLDOUT)}

    assert dev.isdisjoint(holdout)


@pytest.mark.parametrize("path", [DEV, HOLDOUT])
def test_gold_sources_match_label_and_exist_in_corpus(path):
    corpus_ids = parent_ids(REGULATIONS, INJECTED_DOC)
    injected_ids = parent_ids(INJECTED_DOC)

    for case in load_adversarial_cases(path):
        if case.label in {"unanswerable_out", "unanswerable_near", "false_premise"}:
            assert case.gold_jo == (), case.id
        else:
            assert case.gold_jo, case.id
            assert set(case.gold_jo) <= corpus_ids, case.id
        if case.label == "inject_context":
            assert set(case.gold_jo) <= injected_ids, case.id
        else:
            assert set(case.gold_jo).isdisjoint(injected_ids), case.id


@pytest.mark.parametrize("path", [DEV, HOLDOUT])
def test_attack_questions_carry_canary_or_fake_article_and_others_do_not(path):
    for case in load_adversarial_cases(path):
        mentions_canary = CANARY in case.question
        mentions_fake_article = "제999조" in case.question
        if case.label == "inject_user":
            assert mentions_canary, case.id
        elif case.label == "inject_source":
            assert mentions_fake_article, case.id
        else:
            assert not mentions_canary and not mentions_fake_article, case.id
        if case.label not in {"false_premise", "inject_source"}:
            assert not re.search(r"제\s*\d+\s*조", case.question), case.id


def test_injected_document_has_unique_articles_and_canary_in_each():
    chunks = chunk_text(INJECTED_DOC.read_text(encoding="utf-8"))
    parents = {chunk["id"]: chunk["text"] for chunk in chunks if chunk["type"] == "parent"}

    assert set(parents) == {"jo-901", "jo-902", "jo-903"}
    assert set(parents).isdisjoint(parent_ids(REGULATIONS))
    assert all(CANARY in text for text in parents.values())
    assert "제999조" in parents["jo-901"]


def test_loader_rejects_expectation_that_does_not_match_label(tmp_path):
    row = {
        "id": "x1",
        "label": "answerable",
        "expected": "refuse",
        "question": "q",
        "gold_jo": ["jo-1"],
        "note": "n",
    }
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="does not match label"):
        load_adversarial_cases(path)
