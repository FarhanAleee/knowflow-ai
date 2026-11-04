from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import chat as chat_router
from app.routers.chat import (
    ChatSettings,
    get_chat_settings,
    get_gemini_service,
    get_rag_service,
)
from app.routers.documents import get_retrieval_pipeline
from app.services.llm_service import (
    GenerationResult,
    MissingAPIKeyError,
    ServiceUnavailableError,
    TokenUsage,
)
from app.services.rag_service import RAGResponse, SourceCitation
from app.services.vector_store import SearchResult


class FakeRAGService:
    def __init__(self, response=None, error=None):
        self.response = response or RAGResponse(
            question="What is the policy?",
            answer="Annual training is required. [S1]",
            status="success",
            model_name="gemini-test",
            token_usage=TokenUsage(10, 5, 15),
            retrieval_count=1,
            sources=[
                SourceCitation(
                    source_id="S1",
                    filename="handbook.pdf",
                    source_format="PDF",
                    page_number=4,
                    section_number=None,
                    section_type=None,
                    chunk_id="chunk-123",
                    text_snippet="Annual training is required.",
                    similarity_score=0.93,
                )
            ],
        )
        self.error = error
        self.calls = []

    def ask(self, question, top_k=3, document_id=None):
        self.calls.append(
            {"question": question, "top_k": top_k, "document_id": document_id}
        )
        if self.error is not None:
            raise self.error
        return self.response


class FakePipeline:
    def __init__(self):
        self.document_ids = []

    def retrieve(
        self,
        query,
        top_k=3,
        source_filename=None,
        source_format=None,
        document_id=None,
    ):
        self.document_ids.append(document_id)
        return [
            SearchResult(
                chunk_id="actual-chunk",
                text="Annual training is required.",
                metadata={
                    "source_filename": "handbook.pdf",
                    "source_format": "PDF",
                    "page_number": 4,
                },
                distance=0.07,
                similarity=0.93,
            )
        ]


class FakeGeminiService:
    model_name = "gemini-test"

    def generate(self, prompt, system_instruction=None):
        return GenerationResult(
            text="Annual training is required. [S1]",
            model_name=self.model_name,
            usage=TokenUsage(10, 5, 15),
            status="success",
        )


@pytest.fixture
def api_client():
    app.dependency_overrides[get_chat_settings] = lambda: ChatSettings(max_top_k=5)
    rag_service = FakeRAGService()
    app.dependency_overrides[get_rag_service] = lambda: rag_service
    with TestClient(app) as client:
        yield client, rag_service
    app.dependency_overrides.clear()
    get_gemini_service.cache_clear()


def test_successful_chat_response_includes_verified_source_and_usage(api_client):
    client, rag_service = api_client

    response = client.post(
        "/api/chat/ask",
        json={"question": "  What is the policy?  ", "top_k": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["question"] == "What is the policy?"
    assert body["answer"] == "Annual training is required. [S1]"
    assert body["status"] == "success"
    assert body["model_name"] == "gemini-test"
    assert body["retrieval_count"] == 1
    assert body["sources"][0] == {
        "source_id": "S1",
        "filename": "handbook.pdf",
        "page_number": 4,
        "section_number": None,
        "section_type": None,
        "chunk_id": "chunk-123",
        "similarity_score": 0.93,
        "text_snippet": "Annual training is required.",
    }
    assert body["token_usage"] == {
        "prompt_tokens": 10,
        "response_tokens": 5,
        "total_tokens": 15,
    }
    assert rag_service.calls == [
        {"question": "What is the policy?", "top_k": 2, "document_id": None}
    ]


def test_document_id_is_forwarded_to_shared_rag_pipeline():
    pipeline = FakePipeline()
    llm_service = FakeGeminiService()
    app.dependency_overrides[get_chat_settings] = lambda: ChatSettings(max_top_k=5)
    app.dependency_overrides[get_retrieval_pipeline] = lambda: pipeline
    app.dependency_overrides[get_gemini_service] = lambda: llm_service
    try:
        with TestClient(app) as client:
            document_id = str(uuid4())
            response = client.post(
                "/api/chat/ask",
                json={
                    "question": "What is the policy?",
                    "document_id": document_id,
                },
            )
    finally:
        app.dependency_overrides.clear()
        get_gemini_service.cache_clear()

    assert response.status_code == 200
    assert pipeline.document_ids == [document_id]


@pytest.mark.parametrize(
    "payload",
    [
        {"top_k": 3},
        {"question": ""},
        {"question": "   "},
        {"question": "x" * 4001},
        {"question": "question", "top_k": 0},
        {"question": "question", "top_k": 6},
        {"question": "question", "top_k": True},
        {"question": "question", "document_id": "not-a-uuid"},
        {"question": "question", "document_id": str(uuid4()).replace("-", "")},
    ],
)
def test_invalid_chat_requests_return_422(api_client, payload):
    client, rag_service = api_client

    response = client.post("/api/chat/ask", json=payload)

    assert response.status_code == 422
    assert rag_service.calls == []


def test_no_indexed_documents_returns_insufficient_context(api_client):
    client, _ = api_client
    response_data = RAGResponse(
        question="Question",
        answer="The indexed documents do not provide enough information.",
        status="insufficient_context",
        model_name="gemini-test",
        token_usage=None,
        retrieval_count=0,
        sources=[],
    )
    app.dependency_overrides[get_rag_service] = lambda: FakeRAGService(response_data)

    response = client.post("/api/chat/ask", json={"question": "Question"})

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_context"
    assert response.json()["sources"] == []
    assert response.json()["token_usage"] is None


def test_missing_gemini_configuration_returns_safe_503(monkeypatch):
    def fail_service_construction():
        raise MissingAPIKeyError("private configuration details")

    monkeypatch.setattr(chat_router, "GeminiLLMService", fail_service_construction)
    app.dependency_overrides[get_chat_settings] = lambda: ChatSettings(max_top_k=5)
    app.dependency_overrides[get_retrieval_pipeline] = lambda: FakePipeline()
    app.dependency_overrides.pop(get_rag_service, None)
    app.dependency_overrides.pop(get_gemini_service, None)
    get_gemini_service.cache_clear()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/chat/ask",
                json={"question": "What is the policy?"},
            )
    finally:
        app.dependency_overrides.clear()
        get_gemini_service.cache_clear()

    assert response.status_code == 503
    assert response.json()["detail"] == "Chat generation is not configured."
    assert "private configuration details" not in response.text


@pytest.mark.parametrize(
    "rag_error",
    [
        RAGResponse(
            question="Question",
            answer="I couldn't generate a grounded answer right now. Please try again later.",
            status="error",
            model_name="gemini-test",
            token_usage=None,
            retrieval_count=1,
            sources=[],
            error="The answer service is temporarily unavailable.",
        ),
        RAGResponse(
            question="Question",
            answer="I couldn't generate a grounded answer right now. Please try again later.",
            status="error",
            model_name="gemini-test",
            token_usage=None,
            retrieval_count=1,
            sources=[],
            error="The answer service did not return a usable response.",
        ),
    ],
)
def test_gemini_unavailable_response_maps_to_safe_503(api_client, rag_error):
    client, _ = api_client
    app.dependency_overrides[get_rag_service] = lambda: FakeRAGService(rag_error)

    response = client.post("/api/chat/ask", json={"question": "Question"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Chat generation is temporarily unavailable."


def test_gemini_503_exception_maps_to_safe_503():
    rag_service = FakeRAGService(error=ServiceUnavailableError("sensitive provider details"))
    app.dependency_overrides[get_chat_settings] = lambda: ChatSettings(max_top_k=5)
    app.dependency_overrides[get_rag_service] = lambda: rag_service
    try:
        with TestClient(app) as client:
            response = client.post("/api/chat/ask", json={"question": "Question"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["detail"] == "Chat generation is temporarily unavailable."
    assert "sensitive provider details" not in response.text


def test_unexpected_error_is_sanitized_as_500():
    rag_service = FakeRAGService(error=RuntimeError("private path and stack trace"))
    app.dependency_overrides[get_chat_settings] = lambda: ChatSettings(max_top_k=5)
    app.dependency_overrides[get_rag_service] = lambda: rag_service
    try:
        with TestClient(app) as client:
            response = client.post("/api/chat/ask", json={"question": "Question"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500
    assert response.json()["detail"] == "Chat request failed."
    assert "private path" not in response.text


def test_health_and_swagger_register_chat_endpoint(api_client):
    client, _ = api_client

    health = client.get("/health")
    openapi = client.get("/openapi.json")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert openapi.status_code == 200
    assert "/api/chat/ask" in openapi.json()["paths"]
    assert client.get("/docs").status_code == 200


def test_configured_max_top_k_is_loaded(monkeypatch, tmp_path):
    monkeypatch.setattr(chat_router, "_BACKEND_ROOT", tmp_path)
    monkeypatch.setenv("KNOWFLOW_CHAT_MAX_TOP_K", "7")

    assert chat_router.get_chat_settings().max_top_k == 7

