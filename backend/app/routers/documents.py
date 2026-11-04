import codecs
from functools import lru_cache
import logging
import os
import re
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from xml.etree import ElementTree

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from dotenv import load_dotenv
from starlette.concurrency import run_in_threadpool

from app.services.retrieval_pipeline import IndexingResult, RetrievalPipeline


router = APIRouter(prefix="/api/documents", tags=["documents"])
logger = logging.getLogger(__name__)

DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024
MAX_DOCX_DOCUMENT_XML_BYTES = 50 * 1024 * 1024
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_INVALID_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


@dataclass(frozen=True)
class UploadSettings:
    directory: Path
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES

    def __post_init__(self) -> None:
        if self.max_upload_bytes <= 0:
            raise ValueError("max_upload_bytes must be positive.")


class DocumentUploadResponse(BaseModel):
    document_id: str
    filename: str
    file_type: str
    file_size: int
    indexing_status: str
    chunks_indexed: int
    message: str


def get_upload_settings() -> UploadSettings:
    load_dotenv(_BACKEND_ROOT / ".env", override=False)
    configured_directory = os.getenv("KNOWFLOW_UPLOAD_DIRECTORY")
    if configured_directory:
        directory = Path(configured_directory).expanduser()
        if not directory.is_absolute():
            directory = _BACKEND_ROOT / directory
    else:
        directory = _BACKEND_ROOT / "data" / "uploads"

    configured_limit = os.getenv("KNOWFLOW_MAX_UPLOAD_BYTES")
    try:
        max_upload_bytes = (
            int(configured_limit)
            if configured_limit is not None
            else DEFAULT_MAX_UPLOAD_BYTES
        )
    except ValueError as error:
        raise RuntimeError("KNOWFLOW_MAX_UPLOAD_BYTES must be an integer.") from error

    return UploadSettings(directory=directory.resolve(), max_upload_bytes=max_upload_bytes)


@lru_cache(maxsize=1)
def get_retrieval_pipeline() -> RetrievalPipeline:
    """Create the pipeline only when a request needs it; model loading stays lazy."""
    return RetrievalPipeline()


def _safe_filename(upload_filename: str | None) -> tuple[str, str]:
    if not upload_filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A filename is required.",
        )

    basename = upload_filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    extension = Path(basename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported file extension. Upload a PDF, DOCX, or TXT file.",
        )

    safe_name = _INVALID_FILENAME_CHARACTERS.sub("_", basename).strip(" .")
    if not safe_name or safe_name in {".", ".."}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is invalid.",
        )
    stem = Path(safe_name).stem
    if stem.upper() in _WINDOWS_RESERVED_NAMES:
        safe_name = f"upload_{safe_name}"
    return safe_name, extension


async def _save_upload(
    upload: UploadFile,
    destination: Path,
    max_upload_bytes: int,
) -> int:
    total_bytes = 0
    try:
        with destination.open("xb") as output:
            while True:
                bytes_remaining_including_overflow = max_upload_bytes + 1 - total_bytes
                chunk = await upload.read(
                    min(READ_CHUNK_BYTES, bytes_remaining_including_overflow)
                )
                if not chunk:
                    break
                if total_bytes + len(chunk) > max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail="Upload exceeds the configured maximum file size.",
                    )
                output.write(chunk)
                total_bytes += len(chunk)
    except HTTPException:
        raise
    except OSError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to store uploaded document.",
        ) from error

    if total_bytes == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )
    return total_bytes


def _validate_file_content(path: Path, extension: str) -> None:
    if extension == ".pdf":
        with path.open("rb") as source:
            header = source.read(1024)
        if b"%PDF-" not in header:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="File content does not match the PDF extension.",
            )
        return

    if extension == ".docx":
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
                if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                    raise HTTPException(
                        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                        detail="File content does not match the DOCX format.",
                    )
                if archive.getinfo("word/document.xml").file_size > MAX_DOCX_DOCUMENT_XML_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="DOCX document content exceeds the processing limit.",
                    )
                ElementTree.fromstring(archive.read("word/document.xml"))
        except (OSError, zipfile.BadZipFile, KeyError, ElementTree.ParseError) as error:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="File is not a valid DOCX document.",
            ) from error
        return

    decoder = codecs.getincrementaldecoder("utf-8-sig")("strict")
    try:
        with path.open("rb") as source:
            while chunk := source.read(READ_CHUNK_BYTES):
                decoder.decode(chunk)
        decoder.decode(b"", final=True)
    except (OSError, UnicodeDecodeError) as error:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="TXT uploads must contain valid UTF-8 text.",
        ) from error


def _cleanup_failed_index(
    storage_directory: Path,
    pipeline: RetrievalPipeline,
    document_id: str,
) -> bool:
    cleanup_succeeded = True
    vector_store = getattr(pipeline, "vector_store", None)
    if vector_store is not None:
        try:
            stored_chunks = vector_store.get_chunks(document_id=document_id)
            if stored_chunks:
                vector_store.delete([chunk.chunk_id for chunk in stored_chunks])
                if vector_store.get_chunks(document_id=document_id):
                    raise RuntimeError("Vector cleanup did not remove all document records.")
        except Exception:
            logger.error("Could not clean vector records after failed document indexing.")
            cleanup_succeeded = False

    try:
        shutil.rmtree(storage_directory)
    except FileNotFoundError:
        pass
    except OSError:
        logger.error("Could not clean stored file after failed document indexing.")
        cleanup_succeeded = False
    return cleanup_succeeded


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    file: Annotated[UploadFile, File(...)],
    settings: Annotated[UploadSettings, Depends(get_upload_settings)],
    pipeline: Annotated[RetrievalPipeline, Depends(get_retrieval_pipeline)],
) -> DocumentUploadResponse:
    filename, extension = _safe_filename(file.filename)
    document_id = str(uuid.uuid4())
    document_directory = settings.directory / document_id
    destination = document_directory / filename

    try:
        document_directory.mkdir(parents=True, exist_ok=False)
        file_size = await _save_upload(file, destination, settings.max_upload_bytes)
        _validate_file_content(destination, extension)
    except HTTPException:
        if document_directory.exists():
            shutil.rmtree(document_directory, ignore_errors=True)
        raise
    except OSError as error:
        if document_directory.exists():
            shutil.rmtree(document_directory, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to prepare uploaded document.",
        ) from error

    try:
        indexing_result: IndexingResult = await run_in_threadpool(
            pipeline.index_document,
            destination,
            document_id,
        )
    except Exception as error:
        cleanup_succeeded = _cleanup_failed_index(
            document_directory,
            pipeline,
            document_id,
        )
        message = (
            "Document indexing failed."
            if cleanup_succeeded
            else "Document indexing failed and cleanup was incomplete."
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=message,
        ) from None

    if indexing_result.status != "success" or indexing_result.chunks_indexed <= 0:
        cleanup_succeeded = _cleanup_failed_index(
            document_directory,
            pipeline,
            document_id,
        )
        if not cleanup_succeeded:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Document indexing failed and cleanup was incomplete.",
            )
        message = (
            (
                "No searchable text was found. Scanned or image-only PDFs are not OCR processed."
                if extension == ".pdf"
                else "Document contains no searchable text."
            )
            if indexing_result.status == "empty"
            else "Document could not be indexed."
        )
        raise HTTPException(
            status_code=422,
            detail=message,
        )

    return DocumentUploadResponse(
        document_id=document_id,
        filename=filename,
        file_type=extension.lstrip("."),
        file_size=file_size,
        indexing_status="success",
        chunks_indexed=indexing_result.chunks_indexed,
        message="Document uploaded and indexed successfully.",
    )
