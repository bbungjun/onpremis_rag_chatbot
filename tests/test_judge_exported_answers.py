import json

from scripts.evaluate_local_judge import answer_from_export


def test_answer_from_export_returns_answer_and_sources_by_question(tmp_path):
    # Given
    path = tmp_path / "answers.jsonl"
    path.write_text(
        json.dumps(
            {
                "status": "answered",
                "case": {"id": "h1", "question": "질문"},
                "answer": "답변",
                "source_ids": ["jo-1"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    # When
    answer = answer_from_export(path)

    # Then
    assert answer("질문", top_k=5) == {
        "answer": "답변",
        "sources": [{"chunk_id": "jo-1"}],
    }
