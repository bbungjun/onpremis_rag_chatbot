import json
from pathlib import Path

import pytest

from app.chunking import chunk_text
from app.rag_pipeline import _build_context


@pytest.mark.parametrize(
    "case_id,facts",
    [
        ("m01", ["신용카드 매출전표", "5영업일", "8만 원"]),
        ("m03", ["최소 7일", "8만 원", "부임 여비"]),
        ("m07", ["현장 생산직", "1년간", "대표이사의 승인"]),
        ("m05", ["보호 조치 의무", "법무 검토", "3,000만원을 초과"]),
    ],
)
def test_previous_missing_connections_reach_prompt_with_required_facts(case_id, facts):
    fixtures = json.loads(
        Path("datasets/eval/connection_regression_hits.json").read_text(encoding="utf-8")
    )
    row = next(r for r in fixtures["cases"] if r["id"] == case_id)
    chunks = chunk_text(Path("datasets/docs/regulations.md").read_text(encoding="utf-8"))
    parents = {c["id"]: c["text"] for c in chunks if c["type"] == "parent"}
    children = {c["id"]: c for c in chunks if c["type"] == "child"}
    hits = []
    for hit in row["hits"]:
        child = children[hit["child_id"]]
        hits.append(
            {
                "score": hit["score"],
                "payload": {
                    **child["metadata"],
                    "chunk_id": child["id"],
                    "parent_id": child["parent_id"],
                    "parent_text": parents[child["parent_id"]],
                    "text": child["text"],
                    "document_id": "doc:regulations",
                    "source_path": "datasets/docs/regulations.md",
                    "title": "regulations.md",
                },
            }
        )
    selected, prompt = _build_context(row["question"], hits, 5, max_prompt_chars=3891)
    assert set(row["gold_jo"]) <= {p.chunk_id for p in selected}
    assert all(fact in prompt for fact in facts)
    assert len(prompt) <= 3891
