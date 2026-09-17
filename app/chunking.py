"""구조 기반 청킹 — 편/장/절/조/항 체계 + Parent-Child.

검색 단위는 '항'(child), LLM에 전달하는 단위는 '조 전체'(parent)이다.
각 청크에는 편/장/절/조 경로를 메타데이터로 저장한다.

입력 구조 패턴:
  편 : '# 제N편 ...'
  장 : '## 제N장 ...'
  절 : '### 제N절 ...'
  조 : '**제N조 (제목)**'
  항 : '① [라벨] 본문 ...'  (원문자 ①~⑳로 시작)
  호 : '1. ...'             (항 본문 내부에 포함, 별도 청크로 쪼개지 않음)
"""

from __future__ import annotations

import re
from typing import Any

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_CIRCLED_INDEX = {ch: i + 1 for i, ch in enumerate(CIRCLED)}

RE_PYEON = re.compile(r"^#\s+(제\d+편.*)$")
RE_JANG = re.compile(r"^##\s+(제\d+장.*)$")
RE_JEOL = re.compile(r"^###\s+(제\d+절.*)$")
RE_JO = re.compile(r"^\*\*\s*(제(\d+)조)\s*(?:\(([^)]*)\))?\s*\*\*\s*$")
RE_HANG = re.compile(rf"^([{CIRCLED}])\s*(.*)$")
RE_HANG_LABEL = re.compile(r"^\[([^\]]*)\]\s*")


# ---------------------------------------------------------------------------
# 표 처리
# ---------------------------------------------------------------------------
def _is_table_line(line: str) -> bool:
    return line.lstrip().startswith("|")


def annotate_tables(text: str) -> str:
    """본문 중 마크다운 표 블록 위에 컬럼명 요약 한 줄을 덧붙인다.

    표는 행/열 구조라 그대로 임베딩하면 의미가 흐려지기 쉬우므로,
    헤더 셀을 추출해 '[표 요약: 컬럼 — a, b, c]'를 표 바로 위에 삽입한다.
    """
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        if _is_table_line(lines[i]):
            start = i
            while i < n and _is_table_line(lines[i]):
                i += 1
            block = lines[start:i]
            header_cells = [
                cell.strip() for cell in block[0].strip().strip("|").split("|") if cell.strip()
            ]
            if header_cells:
                out.append(f"[표 요약: 컬럼 — {', '.join(header_cells)}]")
            out.extend(block)
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 파싱
# ---------------------------------------------------------------------------
def _split_hang(jo_body_lines: list[str]) -> list[dict[str, Any]]:
    """조 본문 라인들을 항 단위로 분리한다."""
    hangs: list[dict[str, Any]] = []
    cur_no: int | None = None
    cur_label = ""
    buf: list[str] = []

    def flush() -> None:
        if cur_no is None and not any(line.strip() for line in buf):
            return
        body = "\n".join(buf).strip()
        hangs.append(
            {"hang_no": cur_no if cur_no is not None else 0, "label": cur_label, "text": body}
        )

    for line in jo_body_lines:
        match = RE_HANG.match(line)
        if match:
            if cur_no is not None or buf:
                flush()
            cur_no = _CIRCLED_INDEX[match.group(1)]
            rest = match.group(2)
            label_match = RE_HANG_LABEL.match(rest)
            if label_match:
                cur_label = label_match.group(1).strip()
                rest = RE_HANG_LABEL.sub("", rest)
            else:
                cur_label = ""
            buf = [rest] if rest.strip() else []
        else:
            buf.append(line)
    if cur_no is not None or buf:
        flush()
    return hangs


def parse_document(md_text: str) -> list[dict[str, Any]]:
    """구조화 MD를 조 단위 레코드 리스트로 파싱한다."""
    pyeon = jang = jeol = ""
    jo = jo_title = ""
    jo_no = 0
    body_lines: list[str] = []
    records: list[dict[str, Any]] = []

    def flush_jo() -> None:
        if not jo:
            return
        records.append(
            {
                "pyeon": pyeon,
                "jang": jang,
                "jeol": jeol,
                "jo": jo,
                "jo_no": jo_no,
                "jo_title": jo_title,
                "body_lines": list(body_lines),
                "hangs": _split_hang(body_lines),
            }
        )

    for raw in md_text.split("\n"):
        line = raw.rstrip("\n")
        pyeon_match = RE_PYEON.match(line)
        if pyeon_match:
            flush_jo()
            jo = ""
            body_lines = []
            pyeon = pyeon_match.group(1).strip()
            jang = jeol = ""
            continue
        jang_match = RE_JANG.match(line)
        if jang_match:
            flush_jo()
            jo = ""
            body_lines = []
            jang = jang_match.group(1).strip()
            jeol = ""
            continue
        jeol_match = RE_JEOL.match(line)
        if jeol_match:
            flush_jo()
            jo = ""
            body_lines = []
            jeol = jeol_match.group(1).strip()
            continue
        jo_match = RE_JO.match(line)
        if jo_match:
            flush_jo()
            jo = jo_match.group(1).strip()
            jo_no = int(jo_match.group(2))
            jo_title = (jo_match.group(3) or "").strip()
            body_lines = []
            continue
        if line.strip() == "---":
            continue
        if jo:
            body_lines.append(line)

    flush_jo()
    return records


# ---------------------------------------------------------------------------
# 청크 생성
# ---------------------------------------------------------------------------
def _path_str(rec: dict[str, Any]) -> str:
    parts = [rec["pyeon"], rec["jang"], rec["jeol"], rec["jo"]]
    return " > ".join(part for part in parts if part)


def _base_meta(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "pyeon": rec["pyeon"],
        "jang": rec["jang"],
        "jeol": rec["jeol"],
        "jo": rec["jo"],
        "jo_no": rec["jo_no"],
        "jo_title": rec["jo_title"],
        "path": _path_str(rec),
    }


def _jo_full_text(rec: dict[str, Any], table_summary: bool) -> str:
    """조 전체 텍스트(헤더 + 본문). parent의 LLM 전달용."""
    header = f"{rec['jo']} ({rec['jo_title']})" if rec["jo_title"] else rec["jo"]
    body = "\n".join(rec["body_lines"]).strip()
    text = f"{header}\n{body}".strip()
    return annotate_tables(text) if table_summary else text


def records_to_chunks(
    records: list[dict[str, Any]], *, table_summary: bool = True
) -> list[dict[str, Any]]:
    """파싱된 조 레코드를 parent(조 전체) + child(항) 청크로 변환한다."""
    chunks: list[dict[str, Any]] = []
    article_occurrences: dict[str, int] = {}
    for rec in records:
        meta = _base_meta(rec)
        base_id = f"jo-{rec['jo_no']}"
        article_occurrences[base_id] = article_occurrences.get(base_id, 0) + 1
        occurrence = article_occurrences[base_id]
        parent_id = base_id if occurrence == 1 else f"{base_id}-occ-{occurrence}"
        full_text = _jo_full_text(rec, table_summary)

        chunks.append({"id": parent_id, "type": "parent", "text": full_text, "metadata": meta})

        hang_occurrences: dict[int, int] = {}
        for hang in rec["hangs"]:
            hang_text = hang["text"]
            if not hang_text.strip():
                continue
            if table_summary:
                hang_text = annotate_tables(hang_text)
            child_meta = dict(meta)
            child_meta["hang_no"] = hang["hang_no"]
            child_meta["hang_label"] = hang["label"]
            hang_no = hang["hang_no"]
            hang_occurrences[hang_no] = hang_occurrences.get(hang_no, 0) + 1
            hang_occurrence = hang_occurrences[hang_no]
            child_id = f"{parent_id}-hang-{hang_no}"
            if hang_occurrence > 1:
                child_id = f"{child_id}-occ-{hang_occurrence}"
            chunks.append(
                {
                    "id": child_id,
                    "type": "child",
                    "parent_id": parent_id,
                    "text": hang_text,
                    "metadata": child_meta,
                }
            )
    return chunks


def chunk_text(md_text: str, *, table_summary: bool = True) -> list[dict[str, Any]]:
    """구조화 MD를 파싱해 parent/child 청크 리스트로 변환한다."""
    records = parse_document(md_text)
    return records_to_chunks(records, table_summary=table_summary)
