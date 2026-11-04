from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.main import app
from app.routers.documents import (
    UploadSettings,
    get_retrieval_pipeline,
    get_upload_settings,
)
from app.services.document_ingestion import extract_document
from app.services.retrieval_pipeline import IndexingResult
from app.services.text_chunking import chunk_document


class FakeVectorStore:
    def __init__(self):
        self.records = {}
        self.deleted_ids = []

    def get_chunks(self, document_id=None):
        return [
            SimpleNamespace(chunk_id=chunk_id)
            for chunk_id, record_document_id in self.records.items()
            if record_document_id == document_id
        ]

    def delete(self, ids):
        removed = 0
        for chunk_id in ids:
            if chunk_id in self.records:
                del self.records[chunk_id]
                self.deleted_ids.append(chunk_id)
                removed += 1
        return removed


class FakePipeline:
    def __init__(self):
        self.vector_store = FakeVectorStore()
        self.indexed = []
        self.fail_with_exception = False
        self.fail_with_result = False

    def index_document(self, file_path, document_id=None):
        file_path = Path(file_path)
        document = extract_document(file_path)
        self.indexed.append(
            {
                "path": file_path,
                "document_id": document_id,
                "filename": document.filename,
                "status": document.status,
            }
        )

        if document.status == "error":
            return IndexingResult(
                filename=document.filename,
                document_id=document_id,
                status="error",
                chunks_indexed=0,
                total_chunks=0,
                diagnostics="extraction failed",
            )

        if self.fail_with_exception:
            self.vector_store.records["partial-vector"] = document_id
            raise RuntimeError("internal indexing detail")

        chunks = chunk_document(document)
        if self.fail_with_result:
            return IndexingResult(
                filename=document.filename,
                document_id=document_id,
                status="error",
                chunks_indexed=0,
                total_chunks=len(chunks),
                diagnostics="controlled indexing error",
            )
        if not chunks:
            return IndexingResult(
                filename=document.filename,
                document_id=document_id,
                status="empty",
                chunks_indexed=0,
                total_chunks=0,
                diagnostics="no searchable content",
            )

        for chunk in chunks:
            self.vector_store.records[chunk.chunk_id] = document_id
        return IndexingResult(
            filename=document.filename,
            document_id=document_id,
            status="success",
            chunks_indexed=len(chunks),
            total_chunks=len(chunks),
            diagnostics="indexed",
        )


@pytest.fixture
def api_setup(tmp_path):
    pipeline = FakePipeline()
    settings = UploadSettings(
        directory=tmp_path / "uploads",
        max_upload_bytes=10 * 1024 * 1024,
    )
    app.dependency_overrides[get_retrieval_pipeline] = lambda: pipeline
    app.dependency_overrides[get_upload_settings] = lambda: settings
    with TestClient(app) as client:
        yield client, pipeline, settings
    app.dependency_overrides.clear()


def create_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "A PDF policy contains searchable company information.")
    content = document.tobytes()
    document.close()
    return content


def create_docx() -> bytes:
    document = Document()
    document.add_paragraph("A DOCX policy contains searchable company information.")
    import io

    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def create_image_only_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page()
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10), False)
    pixmap.clear_with(255)
    page.insert_image(page.rect, stream=pixmap.tobytes("png"))
    content = document.tobytes()
    document.close()
    return content


@pytest.mark.parametrize(
    ("filename", "content", "file_type"),
    [
        ("policy.pdf", create_pdf(), "pdf"),
        ("policy.docx", create_docx(), "docx"),
        ("policy.txt", b"A TXT policy contains searchable company information.", "txt"),
    ],
    ids=["pdf", "docx", "txt"],
)
def test_uploads_and_indexes_supported_documents(api_setup, filename, content, file_type):
    client, pipeline, settings = api_setup

    response = client.post(
        "/api/documents/upload",
        files={"file": (filename, content)},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == filename
    assert body["file_type"] == file_type
    assert body["file_size"] == len(content)
    assert body["indexing_status"] == "success"
    assert body["chunks_indexed"] > 0
    assert body["document_id"] == pipeline.indexed[-1]["document_id"]
    assert pipeline.indexed[-1]["filename"] == filename
    stored_path = pipeline.indexed[-1]["path"]
    assert stored_path.parent == settings.directory / body["document_id"]
    assert stored_path.read_bytes() == content
    assert pipeline.vector_store.records


def test_unsupported_extension_is_rejected(api_setup):
    client, pipeline, _ = api_setup

    response = client.post(
        "/api/documents/upload",
        files={"file": ("notes.csv", b"a,b\n1,2")},
    )

    assert response.status_code == 415
    assert pipeline.indexed == []


def test_empty_upload_is_rejected(api_setup):
    client, pipeline, settings = api_setup

    response = client.post(
        "/api/documents/upload",
        files={"file": ("empty.txt", b"")},
    )

    assert response.status_code == 400
    assert pipeline.indexed == []
    assert list(settings.directory.iterdir()) == []


def test_whitespace_only_document_is_not_reported_as_success(api_setup):
    client, pipeline, settings = api_setup

    response = client.post(
        "/api/documents/upload",
        files={"file": ("blank.txt", b" \n\t ")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Document contains no searchable text."
    assert pipeline.indexed[-1]["status"] == "empty"
    assert list(settings.directory.iterdir()) == []


def test_oversized_upload_is_rejected_during_bounded_read(tmp_path):
    pipeline = FakePipeline()
    settings = UploadSettings(directory=tmp_path / "uploads", max_upload_bytes=10)
    app.dependency_overrides[get_retrieval_pipeline] = lambda: pipeline
    app.dependency_overrides[get_upload_settings] = lambda: settings
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/documents/upload",
                files={"file": ("oversized.txt", b"x" * 11)},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 413
    assert pipeline.indexed == []
    assert list(settings.directory.iterdir()) == []


def test_corrupted_pdf_is_rejected_without_leaving_file(api_setup):
    client, pipeline, settings = api_setup

    response = client.post(
        "/api/documents/upload",
        files={"file": ("corrupt.pdf", b"%PDF-1.7\nnot a valid PDF")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Document could not be indexed."
    assert pipeline.indexed[-1]["status"] == "error"
    assert list(settings.directory.iterdir()) == []


def test_scanned_image_only_pdf_is_not_reported_as_success(api_setup):
    client, pipeline, settings = api_setup

    response = client.post(
        "/api/documents/upload",
        files={"file": ("scan.pdf", create_image_only_pdf())},
    )

    assert response.status_code == 422
    assert "not OCR processed" in response.json()["detail"]
    assert pipeline.indexed[-1]["status"] == "success"
    assert list(settings.directory.iterdir()) == []


def test_content_mismatch_is_rejected(api_setup):
    client, pipeline, settings = api_setup

    response = client.post(
        "/api/documents/upload",
        files={"file": ("fake.pdf", b"plain text, not a PDF")},
    )

    assert response.status_code == 415
    assert pipeline.indexed == []
    assert list(settings.directory.iterdir()) == []


def test_filename_traversal_is_sanitized_and_stays_inside_upload_directory(api_setup):
    client, pipeline, settings = api_setup

    response = client.post(
        "/api/documents/upload",
        files={"file": ("..\\..\\payload.txt", b"Safe searchable text.")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "payload.txt"
    saved_path = pipeline.indexed[-1]["path"].resolve()
    assert saved_path.parent == (settings.directory / body["document_id"]).resolve()
    assert saved_path.parent.parent == settings.directory.resolve()


def test_same_filename_uploads_get_distinct_persistent_document_ids(api_setup):
    client, pipeline, settings = api_setup
    first_content = b"First distinct document content."
    second_content = b"Second distinct document content."

    first = client.post(
        "/api/documents/upload",
        files={"file": ("same.txt", first_content)},
    )
    second = client.post(
        "/api/documents/upload",
        files={"file": ("same.txt", second_content)},
    )

    assert first.status_code == second.status_code == 201
    first_body, second_body = first.json(), second.json()
    assert first_body["document_id"] != second_body["document_id"]
    assert first_body["filename"] == second_body["filename"] == "same.txt"
    first_path = settings.directory / first_body["document_id"] / "same.txt"
    second_path = settings.directory / second_body["document_id"] / "same.txt"
    assert first_path.read_bytes() == first_content
    assert second_path.read_bytes() == second_content
    assert [item["document_id"] for item in pipeline.indexed] == [
        first_body["document_id"],
        second_body["document_id"],
    ]


def test_indexing_exception_cleans_new_file_and_partial_vectors(api_setup):
    client, pipeline, settings = api_setup
    pipeline.fail_with_exception = True

    response = client.post(
        "/api/documents/upload",
        files={"file": ("failure.txt", b"Content that triggers mocked failure.")},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Document indexing failed."
    assert list(settings.directory.iterdir()) == []
    assert pipeline.vector_store.records == {}
    assert pipeline.vector_store.deleted_ids == ["partial-vector"]


def test_unsuccessful_index_result_cleans_file_and_returns_safe_status(api_setup):
    client, pipeline, settings = api_setup
    pipeline.fail_with_result = True

    response = client.post(
        "/api/documents/upload",
        files={"file": ("failure.txt", b"Valid text but indexing fails.")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Document could not be indexed."
    assert list(settings.directory.iterdir()) == []


def test_health_endpoint_and_swagger_include_upload_route(api_setup):
    client, _, _ = api_setup

    health = client.get("/health")
    openapi = client.get("/openapi.json")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert openapi.status_code == 200
    assert "/api/documents/upload" in openapi.json()["paths"]
    assert client.get("/docs").status_code == 200


def test_upload_limit_can_be_configured_and_is_validated(monkeypatch, tmp_path):
    monkeypatch.setattr("app.routers.documents._BACKEND_ROOT", tmp_path)
    monkeypatch.setenv("KNOWFLOW_MAX_UPLOAD_BYTES", "1234")
    monkeypatch.setenv("KNOWFLOW_UPLOAD_DIRECTORY", "custom-uploads")

    settings = get_upload_settings()

    assert settings.max_upload_bytes == 1234
    assert settings.directory == (tmp_path / "custom-uploads").resolve()
