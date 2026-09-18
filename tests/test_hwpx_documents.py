import os
import shutil
from pathlib import Path

import pytest

from app.chunking import chunk_text
from app.document_reader import read_document
from scripts.ingest_md import discover_source_files


def test_discovery_includes_hwpx_case_insensitively(tmp_path):
    (tmp_path / "regulations.HWPX").write_bytes(b"fixture")

    assert [path.name for path in discover_source_files(tmp_path)] == ["regulations.HWPX"]


def test_real_hwpx_keeps_rich_content_in_its_article():
    cli = os.environ.get("HWP_CLI_PATH") or shutil.which("hwp")
    if not cli:
        pytest.skip("HWP CLI is unavailable on this host")
    source = Path(__file__).parent / "fixtures" / "mixed_rich_policy.hwpx"
    seen = []

    text = read_document(
        source,
        hwp_cli=cli,
        ocr_image=lambda path: seen.append(path.name) or "출장비 5영업일 이내 정산",
    )
    chunks = chunk_text(text)
    children = {chunk["parent_id"]: chunk["text"] for chunk in chunks if chunk["type"] == "child"}

    assert seen == ["image1.png"]
    assert sum(chunk["type"] == "parent" for chunk in chunks) == 4
    assert "구분: 교통비" in children["jo-1"]
    assert "1. 팀장" in children["jo-2"]
    assert "2영업일 이내" in children["jo-3"]
    assert "2영업일 이내" not in children["jo-4"]
    assert "출장비 5영업일 이내 정산" in children["jo-4"]
    assert "그림 1. 출장비 정산 안내" in children["jo-4"]
