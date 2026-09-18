"""DOCX 문단·표와 텍스트 PDF를 규정 청커 입력으로 추출한다."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docx.table import Table


def read_docx_markdown(path: Path) -> str:
    """문단과 단순 표를 원래 순서대로 검색 가능한 텍스트로 만든다."""
    from docx import Document
    from docx.table import Table

    document = Document(path)
    if document.inline_shapes:
        raise ValueError(f"DOCX 이미지의 글자를 아직 추출할 수 없습니다: {path}")

    blocks: list[str] = []
    for item in document.iter_inner_content():
        if isinstance(item, Table):
            blocks.append(_table_text(item))
            continue
        text = item.text.strip()
        if not text:
            continue
        style = item.style.name or ""
        properties = item._p.pPr
        if style.startswith(("List Number", "List Bullet")) or (
            properties is not None and properties.numPr is not None
        ):
            raise ValueError(f"DOCX 자동 번호·목록을 아직 보존할 수 없습니다: {path}")
        blocks.append(text)
    return "\n\n".join(blocks) + "\n"


def read_text_pdf(path: Path) -> str:
    """텍스트 레이어가 있는 PDF의 페이지 본문을 순서대로 읽는다."""
    from pypdf import PdfReader

    document = PdfReader(path)
    if document.is_encrypted:
        raise ValueError(f"암호화 PDF는 지원하지 않습니다: {path}")
    pages = [(page.extract_text() or "").strip() for page in document.pages]
    if not any(pages):
        raise ValueError(f"PDF에서 텍스트를 찾지 못했습니다. 스캔 문서는 OCR이 필요합니다: {path}")
    return "\n\n".join(page for page in pages if page) + "\n"


def _table_text(table: Table) -> str:
    rows = list(table.rows)
    if not rows:
        return ""
    headers = _row_text(rows[0])
    if not all(headers):
        raise ValueError("DOCX 표의 헤더 셀이 비어 있습니다")

    result = [f"[표 열] {', '.join(headers)}"]
    for number, row in enumerate(rows[1:], start=1):
        cells = _row_text(row)
        if len(cells) != len(headers):
            raise ValueError("DOCX 표의 열 수가 행마다 다릅니다")
        pairs = [f"{header}: {value}" for header, value in zip(headers, cells, strict=True)]
        result.append(f"[표 행 {number}] {'; '.join(pairs)}")
    return "\n".join(result)


def _row_text(row) -> list[str]:
    cells = row.cells
    if any(cell.grid_span != 1 or cell._tc.tcPr.vMerge is not None for cell in cells):
        raise ValueError("DOCX 병합 표를 아직 보존할 수 없습니다")
    if any(cell.tables for cell in cells):
        raise ValueError("DOCX 중첩 표를 아직 보존할 수 없습니다")
    return [" ".join(cell.text.split()) for cell in cells]
