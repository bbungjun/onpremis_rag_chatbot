import importlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.chunking import chunk_text


def formatting():
    return importlib.import_module("app.hwp_formatting")


def _child_by_article(markdown: str, article_id: str) -> str:
    return next(
        chunk["text"]
        for chunk in chunk_text(markdown)
        if chunk["type"] == "child" and chunk["parent_id"] == article_id
    )


def test_pipe_table_preserves_header_to_cell_relationship():
    raw = """**제1조 (경비 증빙)**
① 경비는 다음 증빙을 첨부한다.
| **구분** | **필요 증빙** |
| --- | --- |
| 교통비 | 승차권 |
| 숙박비 | 영수증 |
"""

    child = _child_by_article(formatting().normalize_rich_markdown(raw), "jo-1")

    assert "구분: 교통비" in child
    assert "필요 증빙: 승차권" in child
    assert "구분: 숙박비" in child
    assert "필요 증빙: 영수증" in child


def test_merged_html_table_keeps_span_and_cell_text():
    raw = """**제1조 (경비 증빙)**
① 아래 표에 따른다.
<table>
<tr><td colspan="2"><strong>항목</strong><br/><strong>증빙</strong></td></tr>
<tr><td>교통비</td><td>영수증</td></tr>
</table>
"""

    child = _child_by_article(formatting().normalize_rich_markdown(raw), "jo-1")

    assert "열1-2" in child
    assert "항목" in child and "증빙" in child
    assert "교통비" in child and "영수증" in child
    assert "<td" not in child


def test_rowspan_value_is_repeated_on_following_row():
    raw = """**제1조 (출장 증빙)**
① 아래 표에 따른다.
<table>
<tr><td rowspan="2">출장</td><td>교통비</td></tr>
<tr><td>숙박비</td></tr>
</table>
"""

    child = _child_by_article(formatting().normalize_rich_markdown(raw), "jo-1")

    assert "[표 행 2] 열1: 출장; 열2: 숙박비" in child


def test_footnote_definition_moves_to_referencing_article():
    raw = """**제3조 (긴급 예외)**
① 긴급한 사유는 사후 보고한다.[^1]
**제4조 (안내)**
① 안내 이미지를 참고한다.
[^1]: 사후 보고는 2영업일 이내에 한다.
"""

    normalized = formatting().normalize_rich_markdown(raw)

    assert "2영업일 이내" in _child_by_article(normalized, "jo-3")
    assert "2영업일 이내" not in _child_by_article(normalized, "jo-4")


def test_automatic_numbered_list_keeps_item_order():
    raw = """**제2조 (승인 절차)**
① 승인 절차는 다음과 같다.
1. 팀장에게 신청한다.
2. 재무팀이 증빙을 확인한다.
"""

    child = _child_by_article(formatting().normalize_rich_markdown(raw), "jo-2")

    assert child.index("1. 팀장") < child.index("2. 재무팀")


def test_image_ocr_and_adjacent_caption_are_attached_to_article(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    image = media / "image1.png"
    image.write_bytes(b"fixture")
    seen = []
    raw = """**제4조 (정산 안내)**
① 안내 이미지를 참고한다.
![image](media/image1.png)
그림 1. 출장비 정산 절차
"""

    normalized = formatting().normalize_rich_markdown(
        raw,
        media_root=tmp_path,
        ocr_image=lambda path: seen.append(path) or "출장비는 5영업일 이내 정산",
    )
    child = _child_by_article(normalized, "jo-4")

    assert seen == [image]
    assert "출장비는 5영업일 이내 정산" in child
    assert "그림 1. 출장비 정산 절차" in child


def test_inline_image_keeps_surrounding_text_and_ocr(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "image1.png").write_bytes(b"fixture")
    raw = """**제1조 (정산 안내)**
① 아래 ![image](media/image1.png) 내용을 따른다.
그림 1. 정산 기한
"""

    normalized = formatting().normalize_rich_markdown(
        raw, media_root=tmp_path, ocr_image=lambda path: "5영업일 이내"
    )
    child = _child_by_article(normalized, "jo-1")

    assert "아래" in child
    assert "5영업일 이내" in child
    assert "내용을 따른다." in child
    assert "그림 1. 정산 기한" in child


def test_emphasized_image_caption_is_recognized(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "image1.png").write_bytes(b"fixture")
    raw = (
        "**제1조 (정산 안내)**\n① 안내를 따른다.\n"
        "![image](media/image1.png)\n**그림 1. 정산 절차**\n"
    )

    normalized = formatting().normalize_rich_markdown(
        raw, media_root=tmp_path, ocr_image=lambda path: "5영업일"
    )

    assert "[이미지 캡션] 그림 1. 정산 절차" in _child_by_article(normalized, "jo-1")


def test_image_without_text_or_caption_fails_instead_of_silent_indexing(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "image1.png").write_bytes(b"fixture")

    with pytest.raises(ValueError, match="이미지"):
        formatting().normalize_rich_markdown(
            "**제1조 (안내)**\n① 아래 그림을 따른다.\n![image](media/image1.png)\n",
            media_root=tmp_path,
            ocr_image=lambda path: "",
        )


def test_default_ocr_uses_local_korean_and_english_tesseract(monkeypatch, tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    image = media / "image1.png"
    image.write_bytes(b"fixture")
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, "5영업일 이내", "")

    monkeypatch.setattr(formatting().subprocess, "run", fake_run)
    monkeypatch.setenv("TESSERACT_CLI_PATH", "tesseract-test")

    normalized = formatting().normalize_rich_markdown(
        "**제1조 (정산)**\n① 아래 그림을 따른다.\n![image](media/image1.png)\n",
        media_root=tmp_path,
    )

    assert "5영업일 이내" in normalized
    assert calls[0][0] == ["tesseract-test", str(image), "stdout", "-l", "kor+eng", "--psm", "6"]
    assert calls[0][1]["shell"] is False


def test_real_hwp_rich_content_uses_extracted_image_asset():
    cli = os.environ.get("HWP_CLI_PATH") or shutil.which("hwp")
    if not cli:
        pytest.skip("HWP CLI is unavailable on this host")
    reader = importlib.import_module("app.document_reader")
    source = Path(__file__).parent / "fixtures" / "mixed_rich_policy.hwp"
    seen = []

    text = reader.read_document(
        source,
        hwp_cli=cli,
        ocr_image=lambda path: seen.append(path.name) or "출장비 5영업일 이내 정산",
    )

    assert seen == ["image1.png"]
    assert "구분: 교통비" in _child_by_article(text, "jo-1")
    assert "1. 팀장" in _child_by_article(text, "jo-2")
    assert "2영업일 이내" in _child_by_article(text, "jo-3")
    assert "2영업일 이내" not in _child_by_article(text, "jo-4")
    assert "출장비 5영업일 이내 정산" in _child_by_article(text, "jo-4")
    assert "그림 1. 출장비 정산 안내" in _child_by_article(text, "jo-4")


def test_real_hwp_merged_table_preserves_span():
    cli = os.environ.get("HWP_CLI_PATH") or shutil.which("hwp")
    if not cli:
        pytest.skip("HWP CLI is unavailable on this host")
    reader = importlib.import_module("app.document_reader")
    source = Path(__file__).parent / "fixtures" / "merged_table_policy.hwp"

    text = reader.read_document(source, hwp_cli=cli)
    child = _child_by_article(text, "jo-1")

    assert "열1-2: 항목 / 증빙" in child
    assert "열1: 교통비" in child
    assert "열2: 영수증" in child
    assert "<td" not in child
