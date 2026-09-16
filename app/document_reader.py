"""문서 형식을 구조화된 규정 Markdown으로 정규화하는 입력 어댑터."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from app.chunking import chunk_text

_HEADING = re.compile(
    r"^(#{1,3})\s+(?:\*\*)?(?:\d+(?:-\d+)*\.\s*)?"
    r"(제\d+[편장절][^*]*?)(?:\*\*)?\s*$"
)
_PLAIN_HEADING = re.compile(r"^(?:\d+(?:-\d+)*\.\s*)?(제\d+([편장절]).*)$")
_ARTICLE = re.compile(r"^(?:\*\*)?(제\d+조(?:\s*\([^)]*\))?)(?:\*\*)?\s*$")


def read_document(path: str | Path, *, hwp_cli: str | None = None) -> str:
    """Markdown 또는 HWP 5.0을 읽는다. HWP 구조가 추출되지 않으면 실패한다."""
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".md":
        return source.read_text(encoding="utf-8")
    if suffix != ".hwp":
        raise ValueError(f"Unsupported document format: {source.suffix}")

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
        raise RuntimeError(f"HWP 추출 실패: {source}") from exc

    normalized = normalize_hwp_markdown(result.stdout)
    chunks = chunk_text(normalized)
    if not any(chunk["type"] == "parent" for chunk in chunks) or not any(
        chunk["type"] == "child" for chunk in chunks
    ):
        raise ValueError(f"HWP에서 제N조/항 구조를 찾지 못했습니다: {source}")
    return normalized


def normalize_hwp_markdown(extracted: str) -> str:
    """HWP 자동 제목 번호를 제거해 기존 편/장/절/조/항 청커에 맞춘다."""
    lines: list[str] = []
    for original in extracted.splitlines():
        line = original.strip()
        heading = _HEADING.fullmatch(line)
        if heading:
            lines.append(f"{heading.group(1)} {heading.group(2).strip()}")
            continue
        plain_heading = _PLAIN_HEADING.fullmatch(line)
        if plain_heading:
            level = {"편": "#", "장": "##", "절": "###"}[plain_heading.group(2)]
            lines.append(f"{level} {plain_heading.group(1).strip()}")
            continue
        article = _ARTICLE.fullmatch(line)
        if article:
            lines.append(f"**{article.group(1).strip()}**")
            continue
        lines.append(original)
    return "\n".join(lines) + "\n"
