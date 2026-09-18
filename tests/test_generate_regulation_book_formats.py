import importlib
import re

import pytest

from app.chunking import chunk_text
from app.document_reader import read_document
from scripts.generate_hwp_corpus import make_regulation_book


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value)


def test_two_policy_book_roundtrips_as_docx_and_pdf(tmp_path):
    generator = importlib.import_module("scripts.generate_regulation_book_formats")
    book = make_regulation_book(2)
    expected = {
        chunk["id"]: _compact(chunk["text"])
        for chunk in chunk_text(book.markdown)
        if chunk["type"] == "child"
    }

    result = generator.generate_formats(2, tmp_path)

    assert result["policies"] == 2
    assert result["parent_chunks"] == 16
    assert result["child_chunks"] == 48
    assert result["qa_matches"] == 2
    assert result["pdf_pages"] >= 1
    assert {path.suffix for path in tmp_path.glob("synthetic-regulations-2.*")} == {
        ".docx",
        ".pdf",
    }
    for suffix in (".docx", ".pdf"):
        chunks = chunk_text(read_document(tmp_path / f"synthetic-regulations-2{suffix}"))
        assert len({chunk["id"] for chunk in chunks}) == len(chunks)
        actual = {
            chunk["id"]: _compact(chunk["text"]) for chunk in chunks if chunk["type"] == "child"
        }
        assert actual == expected


def test_generator_rejects_count_outside_policy_grid(tmp_path):
    generator = importlib.import_module("scripts.generate_regulation_book_formats")

    with pytest.raises(ValueError, match="between"):
        generator.generate_formats(0, tmp_path)

    assert list(tmp_path.iterdir()) == []
