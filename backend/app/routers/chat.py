import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from uuid import UUID

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool

from app.routers.documents import get_retrieval_pipeline
from app.services.llm_service import (
    GeminiLLMService,
    GeminiServiceError,
    MissingAPIKeyError,
    TokenUsage,
)
from app.services.rag_service import RAGResponse, RAGService
from app.services.retrieval_pipeline import RetrievalPipeline


router = APIRouter(prefix="/api/chat", tags=["chat"])
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MAX_TOP_K = 10
MAX_CONFIGURABLE_TOP_K = 50
MAX_QUESTION_LENGTH = 4000


class ChatSettings(BaseModel):
    max_top_k: int = Field(ge=1, le=MAX_CONFIGURABLE_TOP_K)


class ChatAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)
    top_k: int = Field(
        default=3,
        ge=1,
        le=MAX_CONFIGURABLE_TOP_K,
        strict=True,
    )
    document_id: str | None = None

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Question must not be empty or whitespace-only.")
        return normalized

    @field_validator("document_id")
    @classmethod
    def document_id_must_be_canonical_uuid4(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = UUID(value)
        except (AttributeError, ValueError) as error:
            raise ValueError("document_id must be a canonical UUIDv4.") from error
        if parsed.version != 4 or str(parsed) != value.lower():
            raise ValueError("document_id must be a canonical UUIDv4.")
        return str(parsed)


class ChatTokenUsage(BaseModel):
    prompt_tokens: int | None = None
    response_tokens: int | None = None
    total_tokens: int | None = None


class ChatSource(BaseModel):
    source_id: str
    filename: str
    page_number: int | None = None
    section_number: int | None = None
    section_type: str | None = None
    chunk_id: str
    similarity_score: float | None = None
    text_snippet: str


class ChatAskResponse(BaseModel):
    question: str
    answer: str
    status: str
    model_name: str
    retrieval_count: int
    sources: list[ChatSource]
    token_usage: ChatTokenUsage | None = None


def get_chat_settings() -> ChatSettings:
    load_dotenv(_BACKEND_ROOT / ".env", override=False)
    configured_max_top_k = os.getenv("KNOWFLOW_CHAT_MAX_TOP_K")
    try:
        max_top_k = (
            int(configured_max_top_k)
            if configured_max_top_k is not None
            else DEFAULT_MAX_TOP_K
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chat service configuration is invalid.",
        ) from error

    try:
        return ChatSettings(max_top_k=max_top_k)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chat service configuration is invalid.",
        ) from error


@lru_cache(maxsize=1)
def get_gemini_service() -> GeminiLLMService:
    """Create and reuse the configured client only when chat is first requested."""
    try:
        return GeminiLLMService()
    except MissingAPIKeyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chat generation is not configured.",
        ) from error


def get_rag_service(
    pipeline: Annotated[RetrievalPipeline, Depends(get_retrieval_pipeline)],
    gemini_service: Annotated[GeminiLLMService, Depends(get_gemini_service)],
) -> RAGService:
    return RAGService(retrieval_pipeline=pipeline, llm_service=gemini_service)


@router.post(
    "/ask",
    response_model=ChatAskResponse,
    responses={
        422: {"description": "Invalid request"},
        500: {"description": "Internal service error"},
        503: {"description": "Chat generation unavailable"},
    },
)
async def ask_question(
    request: ChatAskRequest,
    settings: Annotated[ChatSettings, Depends(get_chat_settings)],
    rag_service: Annotated[RAGService, Depends(get_rag_service)],
) -> ChatAskResponse:
    if request.top_k > settings.max_top_k:
        raise HTTPException(
            status_code=422,
            detail=f"top_k must not exceed {settings.max_top_k}.",
        )

    if request.document_id is not None:
        normalized_document_id = str(UUID(str(request.document_id)))
    else:
        normalized_document_id = None

    try:
        result: RAGResponse = await run_in_threadpool(
            rag_service.ask,
            request.question,
            request.top_k,
            normalized_document_id,
        )
    except MissingAPIKeyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chat generation is not configured.",
        ) from error
    except GeminiServiceError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chat generation is temporarily unavailable.",
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The chat request is invalid.",
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Chat request failed.",
        ) from error

    if result.status == "error":
        if result.error in {
            "The answer service is temporarily unavailable.",
            "The answer service did not return a usable response.",
        }:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Chat generation is temporarily unavailable.",
            )
        if result.error == "Unable to retrieve indexed document evidence.":
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Document retrieval failed.",
            )
        if result.error == "The answer service could not complete the request.":
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Chat request failed.",
            )
        if result.error == "Generated citations could not be verified.":
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Generated answer citations could not be verified.",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Chat request failed.",
        )

    token_usage = (
        ChatTokenUsage(
            prompt_tokens=result.token_usage.prompt_tokens,
            response_tokens=result.token_usage.response_tokens,
            total_tokens=result.token_usage.total_tokens,
        )
        if isinstance(result.token_usage, TokenUsage)
        else None
    )
    return ChatAskResponse(
        question=result.question,
        answer=result.answer,
        status=result.status,
        model_name=result.model_name,
        retrieval_count=result.retrieval_count,
        sources=[
            ChatSource(
                source_id=source.source_id,
                filename=source.filename,
                page_number=source.page_number,
                section_number=source.section_number,
                section_type=source.section_type,
                chunk_id=source.chunk_id,
                similarity_score=source.similarity_score,
                text_snippet=source.text_snippet,
            )
            for source in result.sources
        ],
        token_usage=token_usage,
    )
