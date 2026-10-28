from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from docx import Document as load_docx
from docx.document import Document as DocumentObject
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph
import fitz
from lxml.etree import XMLSyntaxError
from zipfile import BadZipFile


PageStatus = Literal["extracted", "no_text", "error"]
SectionStatus = Literal["extracted", "no_text", "error"]
DocumentStatus = Literal["success", "empty", "partial", "error"]


@dataclass(frozen=True)
class PageExtraction:
    page_number: int
    text: str
    character_count: int
    status: PageStatus
    error: str | None = None


@dataclass(frozen=True)
class SectionExtraction:
    section_number: int
    section_type: Literal["paragraph", "table", "text"]
    text: str
    character_count: int
    status: SectionStatus
    page_number: None = None
    error: str | None = None


@dataclass(frozen=True)
class DocumentExtraction:
    filename: str
    content: str
    character_count: int
    total_pages: int | None
    pages: list[PageExtraction]
    sections: list[SectionExtraction]
    status: DocumentStatus
    error: str | None = None


def extract_pdf(pdf_path: str | Path) -> DocumentExtraction:
    """Extract text from each page of a PDF without performing OCR."""
    path = Path(pdf_path)

    try:
        document = fitz.open(str(path))
    except (fitz.FileDataError, OSError, ValueError, RuntimeError):
        return DocumentExtraction(
            filename=path.name,
            content="",
            character_count=0,
            total_pages=0,
            pages=[],
            sections=[],
            status="error",
            error="Unable to open PDF file.",
        )

    with document:
        try:
            total_pages = document.page_count
        except (fitz.FileDataError, RuntimeError, ValueError):
            return DocumentExtraction(
                filename=path.name,
                content="",
                character_count=0,
                total_pages=0,
                pages=[],
                sections=[],
                status="error",
                error="Unable to read PDF pages.",
            )

        if total_pages == 0:
            return DocumentExtraction(
                filename=path.name,
                content="",
                character_count=0,
                total_pages=0,
                pages=[],
                sections=[],
                status="empty",
                error="PDF contains no pages.",
            )

        pages: list[PageExtraction] = []
        for index in range(total_pages):
            page_number = index + 1
            try:
                text = document.load_page(index).get_text("text")
            except (fitz.FileDataError, RuntimeError, ValueError):
                pages.append(
                    PageExtraction(
                        page_number=page_number,
                        text="",
                        character_count=0,
                        status="error",
                        error="Unable to extract text from page.",
                    )
                )
                continue

            has_text = bool(text.strip())
            pages.append(
                PageExtraction(
                    page_number=page_number,
                    text=text,
                    character_count=len(text),
                    status="extracted" if has_text else "no_text",
                )
            )

    has_page_errors = any(page.status == "error" for page in pages)
    content = "\n".join(page.text for page in pages)
    return DocumentExtraction(
        filename=path.name,
        content=content,
        character_count=len(content),
        total_pages=total_pages,
        pages=pages,
        sections=[],
        status="partial" if has_page_errors else "success",
    )


def _extract_docx(path: Path) -> DocumentExtraction:
    try:
        document: DocumentObject = load_docx(str(path))
    except (BadZipFile, KeyError, OSError, PackageNotFoundError, ValueError, XMLSyntaxError):
        return DocumentExtraction(
            filename=path.name,
            content="",
            character_count=0,
            total_pages=None,
            pages=[],
            sections=[],
            status="error",
            error="Unable to read DOCX file.",
        )

    sections: list[SectionExtraction] = []
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            section_type: Literal["paragraph", "table"] = "paragraph"
            text = Paragraph(child, document).text
        elif isinstance(child, CT_Tbl):
            section_type = "table"
            table = Table(child, document)
            text = "\n".join(" | ".join(cell.text for cell in row.cells) for row in table.rows)
        else:
            continue

        sections.append(
            SectionExtraction(
                section_number=len(sections) + 1,
                section_type=section_type,
                text=text,
                character_count=len(text),
                status="extracted" if text.strip() else "no_text",
            )
        )

    content = "\n".join(section.text for section in sections)
    return DocumentExtraction(
        filename=path.name,
        content=content,
        character_count=len(content),
        total_pages=None,
        pages=[],
        sections=sections,
        status="success" if content.strip() else "empty",
    )


def _extract_txt(path: Path) -> DocumentExtraction:
    try:
        content = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return DocumentExtraction(
            filename=path.name,
            content="",
            character_count=0,
            total_pages=None,
            pages=[],
            sections=[],
            status="error",
            error="Unable to read text file as UTF-8.",
        )

    sections = (
        [
            SectionExtraction(
                section_number=1,
                section_type="text",
                text=content,
                character_count=len(content),
                status="extracted" if content.strip() else "no_text",
            )
        ]
        if content
        else []
    )
    return DocumentExtraction(
        filename=path.name,
        content=content,
        character_count=len(content),
        total_pages=None,
        pages=[],
        sections=sections,
        status="success" if content.strip() else "empty",
    )


def extract_document(file_path: str | Path) -> DocumentExtraction:
    """Extract a supported PDF, DOCX, or UTF-8 TXT file by its extension."""
    path = Path(file_path)
    extension = path.suffix.lower()

    if extension == ".pdf":
        return extract_pdf(path)
    if extension == ".docx":
        return _extract_docx(path)
    if extension == ".txt":
        return _extract_txt(path)

    return DocumentExtraction(
        filename=path.name,
        content="",
        character_count=0,
        total_pages=None,
        pages=[],
        sections=[],
        status="error",
        error=f"Unsupported file extension: {extension or '(none)'}.",
    )
