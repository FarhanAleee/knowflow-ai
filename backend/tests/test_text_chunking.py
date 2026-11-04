from pathlib import Path

import fitz
from docx import Document
import pytest

from app.services.document_ingestion import DocumentExtraction, extract_document
from app.services.text_chunking import chunk_document


def create_pdf(path: Path, page_texts: list[str]) -> Path:
    pdf = fitz.open()
    for text in page_texts:
        page = pdf.new_page()
        page.insert_text((72, 72), text)
    pdf.save(path)
    pdf.close()
    return path


def create_docx(path: Path, paragraphs: list[str]) -> Path:
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    document.save(path)
    return path


def test_chunks_pdf_with_page_metadata_and_page_boundaries(tmp_path):
    pdf_path = create_pdf(tmp_path / "guide.pdf", ["A" * 40, "B" * 40])
    extracted = extract_document(pdf_path)

    chunks = chunk_document(extracted, chunk_size=20, overlap=5)

    assert len(chunks) > 2
    assert {chunk.source_format for chunk in chunks} == {"PDF"}
    assert {chunk.source_filename for chunk in chunks} == {"guide.pdf"}
    assert all(chunk.page_number in {1, 2} for chunk in chunks)
    assert all(chunk.section_number is None for chunk in chunks)
    assert all(len(chunk.text) <= 20 for chunk in chunks)
    assert all(chunk.character_count == len(chunk.text) for chunk in chunks)
    assert all(
        chunk.page_number == (1 if "A" in chunk.text else 2)
        for chunk in chunks
    )


def test_chunks_docx_and_preserves_section_references(tmp_path):
    docx_path = create_docx(tmp_path / "notes.docx", ["alpha " * 12, "beta " * 12])
    extracted = extract_document(docx_path)

    chunks = chunk_document(extracted, chunk_size=24, overlap=6)

    assert chunks
    assert {chunk.source_format for chunk in chunks} == {"DOCX"}
    assert {chunk.source_filename for chunk in chunks} == {"notes.docx"}
    assert {chunk.page_number for chunk in chunks} == {None}
    assert {chunk.section_number for chunk in chunks} == {1, 2}
    assert all(chunk.section_type == "paragraph" for chunk in chunks)
    assert all(len(chunk.text) <= 24 for chunk in chunks)


def test_chunks_txt_with_section_metadata_and_unicode(tmp_path):
    txt_path = tmp_path / "unicode.txt"
    text = "こんにちは 🌿 " * 20
    txt_path.write_text(text, encoding="utf-8")
    extracted = extract_document(txt_path)

    chunks = chunk_document(extracted, chunk_size=18, overlap=4)

    assert len(chunks) > 1
    rebuilt = chunks[0].text + "".join(chunk.text[4:] for chunk in chunks[1:])
    assert rebuilt == text
    assert {chunk.source_format for chunk in chunks} == {"TXT"}
    assert {chunk.page_number for chunk in chunks} == {None}
    assert {chunk.section_number for chunk in chunks} == {1}
    assert all(chunk.section_type == "text" for chunk in chunks)
    assert all(chunk.character_count == len(chunk.text) for chunk in chunks)


def test_chunk_ids_are_deterministic_and_metadata_is_complete(tmp_path):
    txt_path = tmp_path / "stable.txt"
    txt_path.write_text("A sufficiently long paragraph " * 8, encoding="utf-8")
    extracted = extract_document(txt_path)

    first = chunk_document(extracted, chunk_size=30, overlap=5)
    second = chunk_document(extracted, chunk_size=30, overlap=5)

    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert len({chunk.chunk_id for chunk in first}) == len(first)
    assert [chunk.chunk_index for chunk in first] == list(range(1, len(first) + 1))


def test_consecutive_chunks_overlap_by_configured_characters(tmp_path):
    path = tmp_path / "long.txt"
    path.write_text("x" * 100, encoding="utf-8")

    chunks = chunk_document(extract_document(path), chunk_size=20, overlap=5)

    assert all(
        previous.text[-5:] == current.text[:5]
        for previous, current in zip(chunks, chunks[1:])
    )


@pytest.mark.parametrize(
    ("chunk_size", "overlap"),
    [(0, 0), (-1, 0), (10, -1), (10, 10), (10, 11)],
)
def test_rejects_invalid_chunk_configuration(tmp_path, chunk_size, overlap):
    path = tmp_path / "valid.txt"
    path.write_text("text", encoding="utf-8")

    with pytest.raises(ValueError):
        chunk_document(extract_document(path), chunk_size=chunk_size, overlap=overlap)


def test_empty_documents_pages_and_sections_produce_no_chunks(tmp_path):
    empty_txt = tmp_path / "empty.txt"
    empty_txt.write_text("", encoding="utf-8")

    empty_document = extract_document(empty_txt)
    assert chunk_document(empty_document) == []

    structured_empty = DocumentExtraction(
        filename="empty.pdf",
        content="",
        character_count=0,
        total_pages=2,
        pages=[],
        sections=[],
        status="empty",
    )
    assert chunk_document(structured_empty) == []


def test_very_short_text_produces_single_chunk(tmp_path):
    path = tmp_path / "short.txt"
    path.write_text("Short text.", encoding="utf-8")

    chunks = chunk_document(extract_document(path), chunk_size=800, overlap=150)

    assert len(chunks) == 1
    assert chunks[0].text == "Short text."
    assert chunks[0].chunk_index == 1
