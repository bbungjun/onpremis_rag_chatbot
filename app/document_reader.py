"""문서 형식을 구조화된 규정 Markdown으로 정규화하는 입력 어댑터."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from app.chunking import CIRCLED, chunk_text
from app.hwp_formatting import normalize_rich_markdown
from app.office_reader import read_docx_markdown, read_text_pdf

_HEADING = re.compile(
    r"^(#{1,3})\s+(?:\*\*)?(?:\d+(?:-\d+)*\.\s*)?"
    r"(제\d+[편장절][^*]*?)(?:\*\*)?\s*$"
)
_PLAIN_HEADING = re.compile(r"^(?:\d+(?:-\d+)*\.\s*)?(제\d+([편장절]).*)$")
_ARTICLE_NAME = r"제\d+조(?:의\d+)?"
_ARTICLE_LABEL = rf"({_ARTICLE_NAME}(?:\s*\([^)]*\))?)"
_ARTICLE = re.compile(rf"^(?:\*\*)?{_ARTICLE_LABEL}(?:\*\*)?\s*$")
_ARTICLE_INLINE = re.compile(rf"^\*\*{_ARTICLE_LABEL}\*\*\s+(.+)$")
_ARTICLE_PLAIN_INLINE = re.compile(rf"^{_ARTICLE_LABEL}\s+(?=[{CIRCLED}])(.+)$")
_ARTICLE_START = re.compile(rf"^\s*(?:\*\*)?{_ARTICLE_NAME}(?:\s*\([^)]*\))?(?:\*\*)?(?=\s|:|$)")
_ARTICLE_BOLD_MARKER = re.compile(rf"(?<!\S)\*\*{_ARTICLE_NAME}(?:\s*\([^)]*\))?\*\*(?=\s|:|$)")
_HANG_SPLIT = re.compile(rf"(?<!\S)(?=[{CIRCLED}]\s)")
_IMAGE_REFERENCE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def read_document(
    path: str | Path,
    *,
    hwp_cli: str | None = None,
    ocr_image: Callable[[Path], str] | None = None,
) -> str:
    """규정 문서를 구조화 Markdown으로 읽는다. 조·항이 없으면 실패한다."""
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".md":
        return source.read_text(encoding="utf-8")
    if suffix == ".docx":
        raw = read_docx_markdown(source)
        extracted = normalize_rich_markdown(raw)
    elif suffix == ".pdf":
        raw = read_text_pdf(source)
        extracted = normalize_rich_markdown(raw)
    elif suffix in {".hwp", ".hwpx"}:
        raw, extracted = _read_hangul(source, hwp_cli, ocr_image)
    else:
        raise ValueError(f"Unsupported document format: {source.suffix}")

    normalized = normalize_hwp_markdown(extracted)
    chunks = chunk_text(normalized)
    parent_count = sum(chunk["type"] == "parent" for chunk in chunks)
    if not parent_count or not any(chunk["type"] == "child" for chunk in chunks):
        raise ValueError(f"문서에서 제N조/항 구조를 찾지 못했습니다: {source}")
    heading_count = sum(_article_candidates(line) for line in raw.splitlines())
    if heading_count != parent_count:
        raise ValueError(
            f"문서 조 제목 수 {heading_count}개와 파싱된 조 {parent_count}개가 다릅니다: {source}"
        )
    return normalized


def _read_hangul(
    source: Path,
    hwp_cli: str | None,
    ocr_image: Callable[[Path], str] | None,
) -> tuple[str, str]:
    command = hwp_cli or os.environ.get("HWP_CLI_PATH", "hwp")
    try:
        result = subprocess.run(
            [command, "cat", str(source), "--format", "markdown"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=120,
            shell=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("HWP CLI를 찾을 수 없습니다. HWP_CLI_PATH를 설정하세요.") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"한글 문서 추출 실패: {source}") from exc

    raw = result.stdout
    if _IMAGE_REFERENCE.search(raw):
        with tempfile.TemporaryDirectory(prefix="hwp-media-") as directory:
            output = Path(directory) / "document.md"
            try:
                subprocess.run(
                    [
                        command,
                        "convert",
                        str(source.resolve()),
                        "-o",
                        str(output),
                        "--media-dir",
                        "media",
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=True,
                    timeout=120,
                    shell=False,
                )
            except (
                FileNotFoundError,
                subprocess.CalledProcessError,
                subprocess.TimeoutExpired,
            ) as exc:
                raise RuntimeError(f"한글 문서 이미지 추출 실패: {source}") from exc
            extracted = normalize_rich_markdown(
                output.read_text(encoding="utf-8"),
                media_root=Path(directory),
                ocr_image=ocr_image,
            )
    else:
        extracted = normalize_rich_markdown(raw)
    return raw, extracted


def normalize_hwp_markdown(extracted: str) -> str:
    """HWP/HWPX 자동 제목 번호를 제거해 기존 편/장/절/조/항 청커에 맞춘다."""
    lines: list[str] = []
    for original in extracted.splitlines():
        for segment in _split_article_segments(original):
            lines.extend(_normalize_segment(segment))
    return "\n".join(lines) + "\n"


def _normalize_segment(original: str) -> list[str]:
    """한 문단 조각에서 편/장/절/조/항 경계를 복원한다."""
    line = original.strip()
    heading = _HEADING.fullmatch(line)
    if heading:
        return [f"{heading.group(1)} {heading.group(2).strip()}"]
    plain_heading = _PLAIN_HEADING.fullmatch(line)
    if plain_heading:
        level = {"편": "#", "장": "##", "절": "###"}[plain_heading.group(2)]
        return [f"{level} {plain_heading.group(1).strip()}"]
    article = _ARTICLE.fullmatch(line)
    if article:
        return [f"**{article.group(1).strip()}**"]
    inline = _ARTICLE_INLINE.fullmatch(line) or _ARTICLE_PLAIN_INLINE.fullmatch(line)
    if inline:
        return [f"**{inline.group(1).strip()}**", *_split_hangs(inline.group(2))]
    if re.match(rf"^[{CIRCLED}]\s", line):
        return _split_hangs(line)
    return [original]


def _split_article_segments(line: str) -> list[str]:
    matches = list(_ARTICLE_BOLD_MARKER.finditer(line))
    if not matches or (len(matches) == 1 and matches[0].start() == 0):
        return [line]
    segments: list[str] = []
    if matches[0].start():
        segments.append(line[: matches[0].start()].strip())
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
        segments.append(line[match.start() : end].strip())
    return segments


def _article_candidates(line: str) -> int:
    bold_count = len(_ARTICLE_BOLD_MARKER.findall(line))
    return bold_count or int(bool(_ARTICLE_START.match(line.strip())))


def _split_hangs(line: str) -> list[str]:
    return [part.strip() for part in _HANG_SPLIT.split(line) if part.strip()]
