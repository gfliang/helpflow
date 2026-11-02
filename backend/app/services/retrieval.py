"""Hybrid retrieval over published knowledge chunks, exposed as a LangChain retriever."""

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import KnowledgeChunk, KnowledgeDocument
from app.providers.embeddings import embedding_provider, tokenize

logger = logging.getLogger(__name__)

VECTOR_WEIGHT = 0.65
LEXICAL_WEIGHT = 0.35

MULTI_QUERY_PROMPT = PromptTemplate.from_template(
    "你是检索查询改写助手。针对下面的访客问题，生成 3 个不同角度的检索查询，"
    "每行一个，不要编号，不要解释：\n问题：{question}"
)


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: KnowledgeChunk
    document: KnowledgeDocument
    vector_score: float
    lexical_score: float

    @property
    def score(self) -> float:
        return round(VECTOR_WEIGHT * self.vector_score + LEXICAL_WEIGHT * self.lexical_score, 4)


def lexical_overlap(query: str, content: str) -> float:
    query_tokens = set(tokenize(query))
    if not query_tokens:
        return 0.0
    content_tokens = set(tokenize(content))
    return len(query_tokens & content_tokens) / len(query_tokens)


def retrieve_published_chunks(
    db: Session, workspace_id: uuid.UUID, query: str, limit: int
) -> list[RetrievedChunk]:
    """Only documents in `published` state are eligible for online answers."""
    query_embedding = embedding_provider.embed(query)
    distance = KnowledgeChunk.embedding.cosine_distance(query_embedding).label("distance")
    rows = db.execute(
        select(KnowledgeChunk, KnowledgeDocument, distance)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
        .where(
            KnowledgeChunk.workspace_id == workspace_id,
            KnowledgeDocument.status == "published",
        )
        .order_by(distance)
        .limit(max(limit * 6, settings.rag_candidate_limit))
    ).all()
    candidates = [
        RetrievedChunk(
            chunk=chunk,
            document=document,
            vector_score=max(0.0, 1 - float(result_distance)),
            lexical_score=lexical_overlap(query, chunk.content),
        )
        for chunk, document, result_distance in rows
    ]
    return sorted(candidates, key=lambda item: item.score, reverse=True)[:limit]


def _as_document(item: RetrievedChunk, rank: int) -> Document:
    return Document(
        page_content=item.chunk.content,
        metadata={
            "document_id": str(item.document.id),
            "document_title": item.document.title,
            "chunk_id": str(item.chunk.id),
            "sequence": item.chunk.sequence,
            "rank": rank,
            "score": item.score,
            "vector_score": item.vector_score,
            "lexical_score": item.lexical_score,
        },
    )


class HelpFlowRetriever(BaseRetriever):
    """Workspace-aware hybrid retriever that keeps the existing pgvector schema."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    db: Any
    workspace_id: uuid.UUID
    limit: int = 4

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        items = retrieve_published_chunks(self.db, self.workspace_id, query, self.limit)
        return [_as_document(item, rank) for rank, item in enumerate(items, start=1)]


def build_retriever(
    db: Session, workspace_id: uuid.UUID, limit: int
) -> BaseRetriever:
    base = HelpFlowRetriever(db=db, workspace_id=workspace_id, limit=limit)
    if not settings.rag_multi_query_enabled:
        return base
    try:
        from langchain.retrievers.multi_query import MultiQueryRetriever

        from app.services.rag import build_chat_model

        return MultiQueryRetriever.from_llm(
            retriever=base,
            llm=build_chat_model(temperature=0.0, streaming=False),
            prompt=MULTI_QUERY_PROMPT,
            include_original=True,
            parser_key="lines",
        )
    except Exception as error:  # noqa: BLE001 - retrieval must stay available without an LLM
        logger.warning("MultiQuery retriever disabled for this call: %s", error)
        return base


def retrieve_documents(
    db: Session, workspace_id: uuid.UUID, query: str, limit: int
) -> list[Document]:
    """Invoke the LangChain retriever, falling back to plain hybrid search on any error."""
    retriever = build_retriever(db, workspace_id, limit)
    try:
        return retriever.invoke(query)
    except Exception as error:  # noqa: BLE001 - e.g. OpenRouter rate limit or timeout
        logger.warning("LangChain retrieval failed, using hybrid search: %s", error)
        items = retrieve_published_chunks(db, workspace_id, query, limit)
        return [_as_document(item, rank) for rank, item in enumerate(items, start=1)]
