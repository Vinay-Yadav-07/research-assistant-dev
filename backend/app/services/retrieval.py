"""S2 Retrieval Service (SRS §8.2, FR-08): hybrid search, Reciprocal Rank Fusion, reranking.

Dense (exact cosine, D-059) and full-text candidates from one workspace are fused with RRF;
the best fused candidates are reranked with the cross-encoder, whose scores are in [0, 1].
"""

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.errors import NotFoundError
from app.providers.embedding import EmbeddingProvider
from app.providers.reranker import RerankerProvider
from app.repositories.chunks import ChunkHit, ChunkRecord
from app.services.guardrails import check_question


class ChunkStore(Protocol):
    """Search the service needs; `ChunkRepository` implements it."""

    async def workspace_owned(self, user_id: UUID, workspace_id: UUID) -> bool: ...

    async def dense_search(
        self,
        user_id: UUID,
        workspace_id: UUID,
        query_vector: Sequence[float],
        *,
        embedding_model: str,
        limit: int,
        document_ids: Sequence[UUID] | None = None,
    ) -> list[ChunkHit]: ...

    async def lexical_search(
        self,
        user_id: UUID,
        workspace_id: UUID,
        query: str,
        *,
        limit: int,
        document_ids: Sequence[UUID] | None = None,
    ) -> list[ChunkHit]: ...

    async def load(
        self, user_id: UUID, workspace_id: UUID, chunk_ids: Sequence[UUID]
    ) -> list[ChunkRecord]: ...

    async def match_documents(
        self, user_id: UUID, workspace_id: UUID, refs: Sequence[str]
    ) -> list[UUID]: ...


class RetrievedChunk(BaseModel):
    """One evidence candidate with provenance and its score at every stage."""

    chunk_id: UUID
    document_id: UUID
    document_title: str | None
    chunk_index: int
    page_start: int
    page_end: int
    section: str | None
    text: str
    # 1-based rank in each search; None if that search did not return the chunk.
    dense_rank: int | None
    lexical_rank: int | None
    rrf_score: float
    # Cross-encoder relevance in [0, 1]; None if the chunk was not among the reranked candidates.
    rerank_score: float | None


class RetrievalTimings(BaseModel):
    """Milliseconds per stage."""

    embed_ms: float
    dense_ms: float
    lexical_ms: float
    rerank_ms: float
    total_ms: float


class RetrievalResult(BaseModel):
    """The evidence set for one query, best first."""

    query: str
    evidence: list[RetrievedChunk]


class RetrievalDebug(RetrievalResult):
    """The evidence plus every fused candidate (RRF order) and timings."""

    candidates: list[RetrievedChunk]
    dense_hits: int = Field(description="Chunks returned by the dense search")
    lexical_hits: int = Field(description="Chunks returned by the full-text search")
    embedding_model: str
    reranker_model: str
    timings: RetrievalTimings


@dataclass(frozen=True)
class RetrievalOptions:
    """Top-k values and limits (SRS §8.2: all configurable)."""

    dense_top_k: int
    lexical_top_k: int
    rrf_k: int
    rerank_candidates: int
    top_k: int
    max_query_chars: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "RetrievalOptions":
        """Read the options from the application settings."""
        return cls(
            dense_top_k=settings.dense_top_k,
            lexical_top_k=settings.lexical_top_k,
            rrf_k=settings.rrf_k,
            rerank_candidates=settings.rerank_candidates,
            top_k=settings.retrieval_top_k,
            max_query_chars=settings.max_query_chars,
        )


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[UUID]], *, k: int
) -> list[tuple[UUID, float]]:
    """Fuse rankings by summing 1 / (k + rank); best first, ties broken by id for stability."""
    scores: dict[UUID, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], str(pair[0])))


class RetrievalService:
    """Workspace-scoped hybrid retrieval with reranking."""

    def __init__(
        self,
        store: ChunkStore,
        *,
        embedder: EmbeddingProvider,
        reranker: RerankerProvider,
        options: RetrievalOptions,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._reranker = reranker
        self._options = options

    async def retrieve(
        self,
        user_id: UUID,
        workspace_id: UUID,
        query: str,
        *,
        top_k: int | None = None,
        document_ids: Sequence[UUID] | None = None,
        extra_terms: Sequence[str] = (),
    ) -> RetrievalResult:
        """The top evidence for `query` from one of the user's workspaces.

        `document_ids` limits the search to those documents (named papers, SRS §7.4).
        `extra_terms` (A1's search keywords) are added to the full-text query only: dense search
        and the reranker see the query as asked.
        """
        debug = await self.debug(
            user_id,
            workspace_id,
            query,
            top_k=top_k,
            document_ids=document_ids,
            extra_terms=extra_terms,
        )
        return RetrievalResult(query=debug.query, evidence=debug.evidence)

    async def retrieve_dense(
        self, user_id: UUID, workspace_id: UUID, query: str, *, top_k: int | None = None
    ) -> RetrievalResult:
        """The nearest chunks by embedding only, best first (the C2 baseline, SRS §17.2).

        No full-text search, fusion, or reranking: `rrf_score` is 0 and `rerank_score` None.
        """
        query = self._check_query(query)
        if not await self._store.workspace_owned(user_id, workspace_id):
            raise NotFoundError("Workspace not found.")
        vector = await self._embedder.embed_query(query)
        hits = await self._store.dense_search(
            user_id,
            workspace_id,
            vector,
            embedding_model=self._embedder.model_name,
            limit=top_k or self._options.top_k,
        )
        ids = [hit.chunk_id for hit in hits]
        records = {
            record.chunk_id: record for record in await self._store.load(user_id, workspace_id, ids)
        }
        rank = {chunk_id: position for position, chunk_id in enumerate(ids, start=1)}
        evidence = [
            _retrieved(records[chunk_id], rank, {}, 0.0) for chunk_id in ids if chunk_id in records
        ]
        return RetrievalResult(query=query, evidence=evidence)

    async def resolve_papers(
        self, user_id: UUID, workspace_id: UUID, refs: Sequence[str]
    ) -> list[UUID]:
        """The workspace documents that the paper references name (may be empty)."""
        if not refs:
            return []
        return await self._store.match_documents(user_id, workspace_id, refs)

    async def debug(
        self,
        user_id: UUID,
        workspace_id: UUID,
        query: str,
        *,
        top_k: int | None = None,
        document_ids: Sequence[UUID] | None = None,
        extra_terms: Sequence[str] = (),
    ) -> RetrievalDebug:
        """Like `retrieve`, with every stage's candidates, scores, and timings."""
        query = self._check_query(query)
        lexical_text = " ".join([query, *(term.strip() for term in extra_terms if term.strip())])
        if not await self._store.workspace_owned(user_id, workspace_id):
            raise NotFoundError("Workspace not found.")
        options = self._options
        started = time.perf_counter()

        vector = await self._embedder.embed_query(query)
        embedded = time.perf_counter()
        dense = await self._store.dense_search(
            user_id,
            workspace_id,
            vector,
            embedding_model=self._embedder.model_name,
            limit=options.dense_top_k,
            document_ids=document_ids,
        )
        dense_done = time.perf_counter()
        lexical = await self._store.lexical_search(
            user_id,
            workspace_id,
            lexical_text,
            limit=options.lexical_top_k,
            document_ids=document_ids,
        )
        lexical_done = time.perf_counter()

        dense_ids = [hit.chunk_id for hit in dense]
        lexical_ids = [hit.chunk_id for hit in lexical]
        fused = reciprocal_rank_fusion([dense_ids, lexical_ids], k=options.rrf_k)
        records = {
            record.chunk_id: record
            for record in await self._store.load(user_id, workspace_id, [i for i, _ in fused])
        }
        dense_rank = {chunk_id: rank for rank, chunk_id in enumerate(dense_ids, start=1)}
        lexical_rank = {chunk_id: rank for rank, chunk_id in enumerate(lexical_ids, start=1)}
        candidates = [
            _retrieved(records[chunk_id], dense_rank, lexical_rank, score)
            for chunk_id, score in fused
            if chunk_id in records
        ]

        rerank_started = time.perf_counter()
        to_rerank = candidates[: options.rerank_candidates]
        if to_rerank:
            scores = await self._reranker.score(query, [chunk.text for chunk in to_rerank])
            for chunk, score in zip(to_rerank, scores, strict=True):
                chunk.rerank_score = score
        reranked = sorted(to_rerank, key=lambda chunk: -(chunk.rerank_score or 0.0))
        finished = time.perf_counter()

        return RetrievalDebug(
            query=query,
            evidence=reranked[: top_k or options.top_k],
            candidates=candidates,
            dense_hits=len(dense),
            lexical_hits=len(lexical),
            embedding_model=self._embedder.model_name,
            reranker_model=self._reranker.model_name,
            timings=RetrievalTimings(
                embed_ms=_ms(started, embedded),
                dense_ms=_ms(embedded, dense_done),
                lexical_ms=_ms(dense_done, lexical_done),
                rerank_ms=_ms(rerank_started, finished),
                total_ms=_ms(started, finished),
            ),
        )

    def _check_query(self, query: str) -> str:
        """S6 input check: a non-empty query of bounded length."""
        return check_question(query, self._options.max_query_chars)


def _retrieved(
    record: ChunkRecord,
    dense_rank: dict[UUID, int],
    lexical_rank: dict[UUID, int],
    rrf_score: float,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=record.chunk_id,
        document_id=record.document_id,
        document_title=record.document_title,
        chunk_index=record.chunk_index,
        page_start=record.page_start,
        page_end=record.page_end,
        section=record.section,
        text=record.text,
        dense_rank=dense_rank.get(record.chunk_id),
        lexical_rank=lexical_rank.get(record.chunk_id),
        rrf_score=rrf_score,
        rerank_score=None,
    )


def _ms(start: float, end: float) -> float:
    return round((end - start) * 1000, 1)
