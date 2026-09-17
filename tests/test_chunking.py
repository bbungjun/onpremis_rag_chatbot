import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.chunking import annotate_tables, chunk_text, parse_document, records_to_chunks

SAMPLE = """# 제1편 총칙

## 제1장 일반

### 제1절 통칙

**제1조 (연차 및 재택근무 원칙)**

① [정의 및 목적]
본 규정의 목적은 연차 신청, 재택근무 승인, 개인정보 및 보안 준수 기준을 정하는 것이다.
1. 연차 신청 기준
2. 재택근무 승인 절차

② [적용 대상]
모든 임직원에게 적용된다.
출장비 정산과 경비 처리 증빙, 온보딩 보안 교육에도 적용된다.

---

**제2조 (용어)**

① [정의]
출장비, 경비 처리, 개인정보, VPN 보안 용어를 정의한다.
"""


def test_empty_input_returns_no_chunks():
    assert chunk_text("") == []


def test_whitespace_only_input_returns_no_chunks():
    assert chunk_text(" \n\t  ") == []


def test_parse_structure_extracts_pyeon_jang_jeol_jo_hangs():
    records = parse_document(SAMPLE)

    assert len(records) == 2
    first = records[0]
    assert first["pyeon"] == "제1편 총칙"
    assert first["jang"] == "제1장 일반"
    assert first["jeol"] == "제1절 통칙"
    assert first["jo"] == "제1조"
    assert first["jo_no"] == 1
    assert first["jo_title"] == "연차 및 재택근무 원칙"
    assert len(first["hangs"]) == 2
    assert first["hangs"][0]["hang_no"] == 1
    assert first["hangs"][0]["label"] == "정의 및 목적"
    assert "연차 신청 기준" in first["hangs"][0]["text"]


def test_records_to_chunks_builds_parent_per_jo_and_child_per_hang():
    records = parse_document(SAMPLE)
    chunks = records_to_chunks(records, table_summary=True)

    parents = [c for c in chunks if c["type"] == "parent"]
    children = [c for c in chunks if c["type"] == "child"]

    assert len(parents) == 2
    assert len(children) == 3

    first_child = children[0]
    assert first_child["parent_id"] == "jo-1"
    assert first_child["metadata"]["path"] == "제1편 총칙 > 제1장 일반 > 제1절 통칙 > 제1조"

    first_parent = parents[0]
    assert "제1조 (연차 및 재택근무 원칙)" in first_parent["text"]
    assert "모든 임직원에게 적용된다." in first_parent["text"]


def test_chunk_text_is_parse_and_convert_combined():
    assert chunk_text(SAMPLE) == records_to_chunks(parse_document(SAMPLE), table_summary=True)


def test_chunk_ids_are_unique_and_stable():
    chunks = chunk_text(SAMPLE)
    ids = [c["id"] for c in chunks]
    assert len(ids) == len(set(ids))
    assert "jo-1" in ids
    assert "jo-1-hang-1" in ids
    assert "jo-1-hang-2" in ids
    assert "jo-2-hang-1" in ids


def test_repeated_article_numbers_in_one_book_keep_distinct_parent_ids():
    book = """# 제1편 인사
## 제1장 휴가
**제1조 (연차)**
① 연차는 3영업일 전에 신청한다.
# 제2편 재무
## 제1장 출장
**제1조 (출장비)**
① 출장비는 5영업일 이내에 정산한다.
"""

    chunks = chunk_text(book)
    parents = [chunk for chunk in chunks if chunk["type"] == "parent"]
    children = [chunk for chunk in chunks if chunk["type"] == "child"]

    assert len(parents) == len(children) == 2
    assert len({chunk["id"] for chunk in chunks}) == 4
    assert parents[0]["id"] != parents[1]["id"]
    assert children[0]["parent_id"] == parents[0]["id"]
    assert children[1]["parent_id"] == parents[1]["id"]


def test_table_summary_prepends_column_header_line():
    text = "앞 문장\n| 구분 | 금액 |\n| --- | --- |\n| 부서장 | 100만원 |\n뒤 문장"

    out = annotate_tables(text)

    assert "[표 요약: 컬럼 — 구분, 금액]" in out
    assert "부서장" in out


def test_records_to_chunks_applies_table_summary_to_children_when_enabled():
    text_with_table = SAMPLE.replace(
        "모든 임직원에게 적용된다.",
        "모든 임직원에게 적용된다.\n| 구분 | 한도 |\n| --- | --- |\n| 부서장 | 100만원 |",
    )
    records = parse_document(text_with_table)

    chunks = records_to_chunks(records, table_summary=True)
    children = [c for c in chunks if c["type"] == "child"]

    assert any("[표 요약: 컬럼 — 구분, 한도]" in c["text"] for c in children)


def test_records_to_chunks_skips_table_summary_when_disabled():
    text_with_table = SAMPLE.replace(
        "모든 임직원에게 적용된다.",
        "모든 임직원에게 적용된다.\n| 구분 | 한도 |\n| --- | --- |\n| 부서장 | 100만원 |",
    )
    records = parse_document(text_with_table)

    chunks = records_to_chunks(records, table_summary=False)
    children = [c for c in chunks if c["type"] == "child"]

    assert not any("[표 요약" in c["text"] for c in children)


@pytest.mark.parametrize("text", ["", "   \n\t"])
def test_parse_document_handles_no_jo_gracefully(text):
    assert parse_document(text) == []
