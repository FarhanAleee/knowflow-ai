import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from app.services.document_ingestion import DocumentExtraction


_SENTENCE_BOUNDARY = re.compile(r"[.!?](?:[\"')\]]*)\s")


@dataclass(frozen=True)
class TextChunk:
    chunk_id: str
    source_filename: str
    source_format: str
    page_number: int | None
    section_number: int | None
    section_type: str | None
    chunk_index: int
    text: str
    character_count: int


@dataclass(frozen=True)
class _TextSource:
    text: str
    page_number: int | None = None
    section_number: int | None = None
    section_type: str | None = None


def _choose_chunk_end(text: str, start: int, chunk_size: int) -> int:
    hard_end = min(start + chunk_size, len(text))
    if hard_end == len(text):
        return hard_end

    minimum_end = start + max(1, chunk_size // 2)
    window = text[minimum_end:hard_end]

    paragraph_boundaries = [
        match.end() + minimum_end
        for match in re.finditer(r"\n\s*\n", window)
    ]
    if paragraph_boundaries:
        return paragraph_boundaries[-1]

    sentence_boundaries = [
        match.end() + minimum_end for match in _SENTENCE_BOUNDARY.finditer(window)
    ]
    if sentence_boundaries:
        return sentence_boundaries[-1]

    whitespace_boundaries = [
        match.end() + minimum_end
        for match in re.finditer(r"\s+", window)
    ]
    if whitespace_boundaries:
        return whitespace_boundaries[-1]

    return hard_end


def _split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    if not text.strip():
        return []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = _choose_chunk_end(text, start, chunk_size)
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap

    return chunks


def _document_sources(document: DocumentExtraction, source_format: str) -> list[_TextSource]:
    if source_format == "PDF":
        return [
            _TextSource(text=page.text, page_number=page.page_number)
            for page in document.pages
        ]

    if document.sections:
        return [
            _TextSource(
                text=section.text,
                section_number=section.section_number,
                section_type=section.section_type,
            )
            for section in document.sections
        ]

    if document.content:
        return [_TextSource(text=document.content, section_number=1, section_type="text")]
    return []


def chunk_document(
    document: DocumentExtraction,
    chunk_size: int = 800,
    overlap: int = 150,
) -> list[TextChunk]:
    """Split extracted document text into deterministic, metadata-preserving chunks."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive.")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be nonnegative and smaller than chunk_size.")

    source_format = Path(document.filename).suffix.lstrip(".").upper()
    if source_format not in {"PDF", "DOCX", "TXT"}:
        raise ValueError(f"Unsupported document format: {source_format or '(none)'}.")

    chunks: list[TextChunk] = []
    for source in _document_sources(document, source_format):
        for text in _split_text(source.text, chunk_size, overlap):
            chunk_index = len(chunks) + 1
            identity = "\0".join(
                (
                    document.filename,
                    source_format,
                    str(source.page_number or ""),
                    str(source.section_number or ""),
                    str(chunk_index),
                    text,
                )
            )
            chunk_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            chunks.append(
                TextChunk(
                    chunk_id=chunk_id,
                    source_filename=document.filename,
                    source_format=source_format,
                    page_number=source.page_number,
                    section_number=source.section_number,
                    section_type=source.section_type,
                    chunk_index=chunk_index,
                    text=text,
                    character_count=len(text),
                )
            )

    return chunks
