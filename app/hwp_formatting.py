"""HWP Markdown 추출에서 표·각주·이미지 내용을 검색 가능한 텍스트로 보존한다."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

_FOOTNOTE_DEFINITION = re.compile(r"^\[\^([^\]]+)\]:\s*(.*)$")
_FOOTNOTE_REFERENCE = re.compile(r"\[\^([^\]]+)\]")
_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]*)\)")
_CAPTION = re.compile(r"^(?:그림|사진|도식|Figure|Fig\.)\s*\d+[.:]?\s*.+$", re.I)
_PIPE_SEPARATOR = re.compile(r":?-{3,}:?")


@dataclass(frozen=True)
class _Cell:
    text: str
    col_span: int = 1
    row_span: int = 1


@dataclass(frozen=True)
class _Span:
    first: int
    last: int
    text: str
    remaining: int


class _HTMLTable(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[_Cell]] = []
        self._row: list[_Cell] | None = None
        self._cell_parts: list[str] | None = None
        self._col_span = 1
        self._row_span = 1
        self._table_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._table_depth += 1
            if self._table_depth > 1:
                raise ValueError("중첩 표는 구조를 확인할 수 없습니다")
        elif tag == "tr":
            self._row = []
        elif tag in {"td", "th"}:
            values = dict(attrs)
            self._col_span = max(1, int(values.get("colspan") or 1))
            self._row_span = max(1, int(values.get("rowspan") or 1))
            self._cell_parts = []
        elif tag == "br" and self._cell_parts is not None:
            self._cell_parts.append(" / ")

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell_parts is not None and self._row is not None:
            text = " ".join("".join(self._cell_parts).split())
            self._row.append(_Cell(text, self._col_span, self._row_span))
            self._cell_parts = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
        elif tag == "table":
            self._table_depth -= 1


def normalize_rich_markdown(
    markdown: str,
    *,
    media_root: Path | None = None,
    ocr_image: Callable[[Path], str] | None = None,
) -> str:
    """추출된 서식을 조·항 청커가 이해할 수 있는 명시적 텍스트로 바꾼다."""
    lines, footnotes = _collect_footnotes(markdown.splitlines())
    rendered: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("|"):
            block, index = _collect_block(lines, index, lambda value: value.strip().startswith("|"))
            rendered.extend(_pipe_table(block))
            continue
        if stripped.lower().startswith("<table"):
            block, index = _collect_html_table(lines, index)
            rendered.extend(_html_table(block))
            continue
        images = list(_IMAGE.finditer(stripped))
        if images:
            caption, next_index = _adjacent_caption(lines, index + 1)
            cursor = 0
            for number, image in enumerate(images):
                prefix = stripped[cursor : image.start()].strip()
                if prefix:
                    rendered.append(prefix)
                image_caption = caption if number == len(images) - 1 else ""
                rendered.extend(
                    _image_text(
                        image.group(1), image.group(2), image_caption, media_root, ocr_image
                    )
                )
                cursor = image.end()
            suffix = stripped[cursor:].strip()
            if suffix:
                rendered.append(suffix)
            index = next_index
            continue
        rendered.append(line)
        index += 1

    used_notes: set[str] = set()

    def replace_note(match: re.Match[str]) -> str:
        note_id = match.group(1)
        if note_id not in footnotes:
            raise ValueError(f"각주 {note_id}의 정의를 찾지 못했습니다")
        used_notes.add(note_id)
        return f"[각주 {note_id}: {footnotes[note_id]}]"

    normalized = [_FOOTNOTE_REFERENCE.sub(replace_note, line) for line in rendered]
    unused = set(footnotes) - used_notes
    if unused:
        raise ValueError(f"참조 위치를 찾지 못한 각주: {', '.join(sorted(unused))}")
    return "\n".join(normalized) + "\n"


def _collect_footnotes(lines: list[str]) -> tuple[list[str], dict[str, str]]:
    body: list[str] = []
    definitions: dict[str, str] = {}
    current: str | None = None
    for line in lines:
        match = _FOOTNOTE_DEFINITION.fullmatch(line.strip())
        if match:
            current = match.group(1)
            if current in definitions:
                raise ValueError(f"각주 {current}가 중복 정의됐습니다")
            definitions[current] = match.group(2).strip()
        elif current is not None and (line.startswith("    ") or line.startswith("\t")):
            definitions[current] += " " + line.strip()
        else:
            current = None
            body.append(line)
    return body, definitions


def _collect_block(
    lines: list[str], start: int, matches: Callable[[str], bool]
) -> tuple[list[str], int]:
    end = start
    while end < len(lines) and matches(lines[end]):
        end += 1
    return lines[start:end], end


def _pipe_cells(line: str) -> list[str]:
    return [_plain_text(cell) for cell in line.strip().strip("|").split("|")]


def _pipe_table(block: list[str]) -> list[str]:
    headers = _pipe_cells(block[0])
    if len(block) > 1 and all(
        _PIPE_SEPARATOR.fullmatch(cell.strip()) for cell in _pipe_cells(block[1])
    ):
        rows = block[2:]
    else:
        rows = block[1:]
    result = [f"[표 열] {', '.join(headers)}"]
    for number, row in enumerate(rows, start=1):
        cells = _pipe_cells(row)
        pairs = [
            f"{headers[index] if index < len(headers) else f'열{index + 1}'}: {cell}"
            for index, cell in enumerate(cells)
        ]
        result.append(f"[표 행 {number}] {'; '.join(pairs)}")
    return result


def _plain_text(value: str) -> str:
    return re.sub(r"\*\*|__|<[^>]+>", "", value).strip()


def _collect_html_table(lines: list[str], start: int) -> tuple[list[str], int]:
    end = start
    while end < len(lines):
        end += 1
        if "</table>" in lines[end - 1].lower():
            return lines[start:end], end
    raise ValueError("닫히지 않은 HTML 표")


def _html_table(block: list[str]) -> list[str]:
    parser = _HTMLTable()
    parser.feed("\n".join(block))
    if not parser.rows:
        raise ValueError("HTML 표의 행을 찾지 못했습니다")
    result: list[str] = []
    active_spans: list[_Span] = []
    for number, row in enumerate(parser.rows, start=1):
        occupied = {column for span in active_spans for column in range(span.first, span.last + 1)}
        column = 1
        cells = [
            (span.first, f"{_column_label(span.first, span.last)}: {span.text}")
            for span in active_spans
        ]
        new_spans: list[_Span] = []
        for cell in row:
            while column in occupied:
                column += 1
            last_column = column + cell.col_span - 1
            label = _column_label(column, last_column)
            cells.append((column, f"{label}: {cell.text}"))
            if cell.row_span > 1:
                new_spans.append(_Span(column, last_column, cell.text, cell.row_span - 1))
            column = last_column + 1
        result.append(f"[표 행 {number}] {'; '.join(value for _, value in sorted(cells))}")
        active_spans = [
            _Span(span.first, span.last, span.text, span.remaining - 1)
            for span in active_spans
            if span.remaining > 1
        ] + new_spans
    return result


def _column_label(first: int, last: int) -> str:
    return f"열{first}" if first == last else f"열{first}-{last}"


def _adjacent_caption(lines: list[str], start: int) -> tuple[str, int]:
    candidate = start
    while candidate < len(lines) and not lines[candidate].strip():
        candidate += 1
    if candidate < len(lines):
        caption = _plain_text(lines[candidate])
        if _CAPTION.fullmatch(caption):
            return caption, candidate + 1
    return "", start


def _image_text(
    alt: str,
    target: str,
    caption: str,
    media_root: Path | None,
    ocr_image: Callable[[Path], str] | None,
) -> list[str]:
    if not target or media_root is None:
        raise ValueError("이미지 원본을 추출하지 못했습니다")
    root = media_root.resolve()
    image = (root / target).resolve()
    if not image.is_relative_to(root) or not image.is_file():
        raise ValueError(f"이미지 경로를 확인할 수 없습니다: {target}")
    recognized = (ocr_image or _tesseract_ocr)(image).strip()
    description = alt.strip() if alt.strip().lower() not in {"image", "그림"} else ""
    if not recognized and not caption and not description:
        raise ValueError(f"이미지 글자와 캡션을 읽지 못했습니다: {target}")
    result: list[str] = []
    if description:
        result.append(f"[이미지 설명] {description}")
    if recognized:
        result.append("[이미지 글자]")
        result.extend(recognized.splitlines())
    if caption:
        result.append(f"[이미지 캡션] {caption}")
    return result


def _tesseract_ocr(path: Path) -> str:
    command = os.environ.get("TESSERACT_CLI_PATH", "tesseract")
    try:
        result = subprocess.run(
            [command, str(path), "stdout", "-l", "kor+eng", "--psm", "6"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=60,
            shell=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("로컬 OCR 실행 파일을 찾지 못했습니다") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"이미지 OCR 실패: {path.name}") from exc
    return result.stdout
