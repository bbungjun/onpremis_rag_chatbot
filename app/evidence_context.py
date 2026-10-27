"""Choose and pack retrieved evidence without fetching or generating new text."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import lru_cache

from app.sparse import tokenize

ARTICLE = re.compile(r"제\s*(\d+)\s*조(?:의\s*(\d+))?")
LAW_PREFIX = re.compile(r"(?:[가-힣]+법|시행령|시행규칙)\s*$")
SECTION = re.compile(r"(?m)^(?=[①②③④⑤⑥⑦⑧⑨⑩])")
STOP_WORDS = frozenset(
    "어떻게 무엇 어떤 얼마 언제 누구 경우 기준 규정 회사 사원 업무 관련 적용 대상 "
    "내용 사항 방법 필요 확인 알려 주다 하다 되다 있다 없다 받다 따르다 사용 대한 통해".split()
)


@dataclass(frozen=True)
class EvidenceSource:
    chunk_id: str
    source_path: str
    title: str
    jo: str
    path: str
    score: float
    text: str
    document_id: str = ""


@lru_cache(maxsize=256)
def _terms(text: str) -> frozenset[str]:
    return frozenset(t for t in tokenize(text) if len(t) >= 2 and t not in STOP_WORDS)


def _article(text: str) -> str:
    match = ARTICLE.search(text)
    return "" if match is None else f"{match[1]}:{match[2] or ''}"


def _references(text: str) -> set[str]:
    return {
        f"{m[1]}:{m[2] or ''}"
        for m in ARTICLE.finditer(text)
        if not LAW_PREFIX.search(text[max(0, m.start() - 30) : m.start()])
    }


def _document(source: EvidenceSource) -> str:
    return source.document_id or source.source_path


def rank_sources(question: str, sources: list[EvidenceSource]) -> list[EvidenceSource]:
    """Keep the retrieval anchor; rank the rest by text and scoped references."""
    if len(sources) < 2:
        return sources
    query = _terms(question)
    if not query:
        return sources
    support: dict[tuple[str, str], float] = {}
    for rank, seed in enumerate(sources[:3]):
        for article in _references(seed.text):
            if article == _article(seed.jo):
                continue
            key = (_document(seed), article)
            support[key] = support.get(key, 0.0) + 1 / (rank + 1)

    def relevance(pair):
        index, source = pair
        title_terms = _terms(source.text.split("\n", 1)[0])
        body_matches = len(query & _terms(source.text))
        title_matches = len(query & title_terms)
        reference = support.get((_document(source), _article(source.jo)), 0.0)
        # A reference alone cannot promote an otherwise unrelated sanctions article.
        score = 2 * title_matches + 0.2 * body_matches + 6 / (index + 1)
        if body_matches:
            score += 2 * reference
        return (-score, index)

    remainder = sorted(enumerate(sources[1:], 1), key=relevance)
    return [sources[0], *(source for _, source in remainder)]


def compact_text(text: str, question: str) -> str:
    """Extract whole policy sections, retaining scope and exceptions together."""
    parts = SECTION.split(text)
    if len(parts) == 1:
        return text
    retained = [parts[0].rstrip()]
    requested = {
        "①": ("정의", "뜻", "의미", "목적"),
        "⑤": ("위반", "제재", "징계", "처벌", "불이익", "조치"),
        "⑥": ("서식", "양식", "신청서", "담당", "주관", "문의"),
    }
    known_labels = {
        "①": {"정의 및 목적"},
        "⑤": {"위반 시 조치"},
        "⑥": {"주관 부서 및 관련 서식", "관련 서식"},
    }
    for section in parts[1:]:
        marker = section[0]
        label = re.match(r"^[①②③④⑤⑥⑦⑧⑨⑩]\s*\[([^\]]+)\]", section)
        recognized = label is not None and label[1] in known_labels.get(marker, set())
        if (
            marker in "②③④"
            or marker not in "①⑤⑥"
            or not recognized
            or any(term in question for term in requested.get(marker, ()))
        ):
            retained.append(section.rstrip())
    # Unstructured facts preceding the first section remain verbatim as well.
    return "\n\n".join(retained)


def select_evidence(
    question: str,
    candidates: list[EvidenceSource],
    top_k: int,
    max_prompt_chars: int | None,
    render: Callable[[list[EvidenceSource]], str],
) -> tuple[list[EvidenceSource], str]:
    ordered = rank_sources(question, candidates)[:top_k]
    return pack_sources(question, ordered, max_prompt_chars, render)


def pack_sources(
    question: str,
    ordered: list[EvidenceSource],
    max_prompt_chars: int | None,
    render: Callable[[list[EvidenceSource]], str],
) -> tuple[list[EvidenceSource], str]:
    """Pack an already ordered list; separated for the compaction ablation."""
    if not ordered:
        return [], ""
    full_prompt = render(ordered)
    if max_prompt_chars is None or len(full_prompt) <= max_prompt_chars:
        return ordered, full_prompt
    if len(render([])) >= max_prompt_chars:
        return [], ""

    compact = [replace(s, text=compact_text(s.text, question)) for s in ordered]
    selected: list[EvidenceSource] = []
    for source in compact:
        if len(render([*selected, source])) <= max_prompt_chars:
            selected.append(source)
        elif not selected:
            # The anchor cannot be safely represented: do not answer a different
            # question from a weaker unrelated source or truncate away its exception.
            return [], ""
    if not selected:
        return [], ""
    return selected, render(selected)
