"""Chunk search for S2 (SRS §8.2). Workspace isolation is enforced here, in SQL (FR-08).

Every query takes `user_id` and `workspace_id` as required arguments and only sees chunks of
`ready` documents that the user owns and that are linked to that user's workspace.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeVarTuple
from uuid import UUID

from sqlalchemy import ColumnElement, Select, Text, and_, cast, func, literal, or_, select
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document
from app.models.workspace import Workspace, WorkspaceDocument

TS_CONFIG = "english"
# Same pattern in Python (`paper_words`) and in SQL (`regexp_replace`), so both sides agree.
_NOT_WORD = re.compile("[^a-z0-9]+")
Ts = TypeVarTuple("Ts")


@dataclass(frozen=True)
class ChunkHit:
    """One search result: a chunk id and its score (distance for dense, rank for lexical)."""

    chunk_id: UUID
    score: float


@dataclass(frozen=True)
class ChunkRecord:
    """A chunk with the provenance needed to cite it."""

    chunk_id: UUID
    document_id: UUID
    document_title: str | None
    chunk_index: int
    page_start: int
    page_end: int
    section: str | None
    text: str


def _in_workspace(
    statement: Select[*Ts],
    user_id: UUID,
    workspace_id: UUID,
    document_ids: Sequence[UUID] | None = None,
) -> Select[*Ts]:
    """Limit a SELECT over chunks to those visible in one of the user's workspaces.

    With `document_ids`, only chunks of those documents remain (named papers, SRS §7.4); the
    workspace and ownership filters still apply.
    """
    scoped = (
        statement.select_from(Chunk)
        .join(WorkspaceDocument, WorkspaceDocument.document_id == Chunk.document_id)
        .join(Workspace, Workspace.id == WorkspaceDocument.workspace_id)
        .join(Document, Document.id == Chunk.document_id)
        .where(
            WorkspaceDocument.workspace_id == workspace_id,
            Workspace.user_id == user_id,
            Document.user_id == user_id,
            Document.status == "ready",
        )
    )
    if document_ids is not None:
        scoped = scoped.where(Chunk.document_id.in_(list(document_ids)))
    return scoped


def lexical_query(query: str) -> ColumnElement[object]:
    """A tsquery matching any of the query's terms (OR), built only from `plainto_tsquery`.

    `plainto_tsquery` parses the raw text safely (operators and punctuation are not syntax)
    and joins lexemes with '&'; switching those to '|' ranks chunks by how many terms they
    share instead of requiring all of them. Only stopwords → an empty query, no error.
    """
    config = cast(literal(TS_CONFIG), REGCONFIG)
    plain = cast(func.plainto_tsquery(config, cast(literal(query), Text)), Text)
    # 'simple' keeps the lexemes as they are: parsing them with 'english' again would stem
    # them twice ('porosity' → 'poros' → 'poro') and miss the stored vectors.
    simple = cast(literal("simple"), REGCONFIG)
    return func.to_tsquery(simple, func.replace(plain, "&", "|"))


class ChunkRepository:
    """Workspace-scoped dense and full-text search over chunks."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def workspace_owned(self, user_id: UUID, workspace_id: UUID) -> bool:
        """True if the workspace exists and belongs to `user_id`."""
        found = await self._session.scalar(
            select(Workspace.id).where(Workspace.id == workspace_id, Workspace.user_id == user_id)
        )
        return found is not None

    async def dense_search(
        self,
        user_id: UUID,
        workspace_id: UUID,
        query_vector: Sequence[float],
        *,
        embedding_model: str,
        limit: int,
        document_ids: Sequence[UUID] | None = None,
    ) -> list[ChunkHit]:
        """Nearest chunks by cosine distance, exact (D-059).

        The workspace's chunks are selected in a MATERIALIZED CTE first, so the planner cannot
        use the HNSW index, which would filter after finding the global nearest neighbours and
        could return fewer than `limit` chunks for a small workspace.
        """
        scoped = (
            _in_workspace(select(Chunk.id, Chunk.embedding), user_id, workspace_id, document_ids)
            .where(Chunk.embedding_model == embedding_model)
            .cte("scoped")
            .prefix_with("MATERIALIZED")
        )
        distance = scoped.c.embedding.cosine_distance(list(query_vector)).label("distance")
        rows = await self._session.execute(
            select(scoped.c.id, distance).order_by(distance, scoped.c.id).limit(limit)
        )
        return [ChunkHit(chunk_id=row.id, score=float(row.distance)) for row in rows]

    async def lexical_search(
        self,
        user_id: UUID,
        workspace_id: UUID,
        query: str,
        *,
        limit: int,
        document_ids: Sequence[UUID] | None = None,
    ) -> list[ChunkHit]:
        """Chunks sharing terms with `query`, best `ts_rank_cd` first."""
        tsquery = lexical_query(query)
        rank = func.ts_rank_cd(Chunk.tsv, tsquery).label("rank")
        rows = await self._session.execute(
            _in_workspace(select(Chunk.id, rank), user_id, workspace_id, document_ids)
            .where(Chunk.tsv.op("@@")(tsquery))
            .order_by(rank.desc(), Chunk.id)
            .limit(limit)
        )
        return [ChunkHit(chunk_id=row.id, score=float(row.rank)) for row in rows]

    async def load(
        self, user_id: UUID, workspace_id: UUID, chunk_ids: Sequence[UUID]
    ) -> list[ChunkRecord]:
        """Provenance for `chunk_ids`, limited to the workspace's chunks (any order)."""
        if not chunk_ids:
            return []
        rows = await self._session.execute(
            _in_workspace(
                select(
                    Chunk.id,
                    Chunk.document_id,
                    Document.title,
                    Chunk.chunk_index,
                    Chunk.page_start,
                    Chunk.page_end,
                    Chunk.section,
                    Chunk.text,
                ),
                user_id,
                workspace_id,
            ).where(Chunk.id.in_(list(chunk_ids)))
        )
        return [
            ChunkRecord(
                chunk_id=row.id,
                document_id=row.document_id,
                document_title=row.title,
                chunk_index=row.chunk_index,
                page_start=row.page_start,
                page_end=row.page_end,
                section=row.section,
                text=row.text,
            )
            for row in rows
        ]

    async def match_documents(
        self, user_id: UUID, workspace_id: UUID, refs: Sequence[str]
    ) -> list[UUID]:
        """Ready documents of the workspace that a paper reference names (SRS §7.4).

        Titles and references are compared as lower-case words (`paper_words`): a reference
        matches when it occurs in a title, when a whole title occurs in it as whole words, or
        when it equals the DOI. `strpos` compares plain strings, so no reference text is ever
        read as a pattern. References shorter than 3 characters are ignored.
        """
        names = [(paper_words(ref), ref.strip().lower()) for ref in refs]
        names = [(words, raw) for words, raw in names if len(words) >= 3]
        if not names:
            return []
        title = func.btrim(
            func.regexp_replace(func.lower(Document.title), _NOT_WORD.pattern, " ", "g")
        )
        matches = [
            or_(
                func.strpos(title, words) > 0,
                and_(
                    func.length(title) >= 3,
                    func.strpos(literal(f" {words} "), func.concat(" ", title, " ")) > 0,
                ),
                func.lower(Document.doi) == raw,
            )
            for words, raw in names
        ]
        rows = await self._session.scalars(
            select(Document.id)
            .join(WorkspaceDocument, WorkspaceDocument.document_id == Document.id)
            .join(Workspace, Workspace.id == WorkspaceDocument.workspace_id)
            .where(
                WorkspaceDocument.workspace_id == workspace_id,
                Workspace.user_id == user_id,
                Document.user_id == user_id,
                Document.status == "ready",
                or_(*matches),
            )
            .order_by(Document.id)
        )
        return list(rows)


def paper_words(text: str) -> str:
    """`text` lower-cased with every run of non-alphanumerics turned into one space."""
    return _NOT_WORD.sub(" ", text.lower()).strip()
