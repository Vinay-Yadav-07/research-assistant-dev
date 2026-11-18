"""A4 output and saved-finding persistence. Every query filters by `user_id` and `workspace_id`."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.research import Contradiction, ResearchGap, SavedFinding
from app.models.workspace import Workspace


class ResearchRepository:
    """Reads and writes one user's research outputs within the caller's session.

    Callers check that the workspace is owned before writing.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def workspace_name(self, user_id: UUID, workspace_id: UUID) -> str | None:
        """The workspace's name, or None if it is missing or owned by someone else."""
        return await self._session.scalar(
            select(Workspace.name).where(Workspace.id == workspace_id, Workspace.user_id == user_id)
        )

    async def documents(self, user_id: UUID, document_ids: Sequence[UUID]) -> list[Document]:
        """The user's documents among `document_ids`; missing and non-owned ones are left out."""
        if not document_ids:
            return []
        result = await self._session.scalars(
            select(Document).where(Document.id.in_(document_ids), Document.user_id == user_id)
        )
        return list(result)

    async def add_finding(
        self, user_id: UUID, workspace_id: UUID, *, type: str, title: str, content: dict[str, Any]
    ) -> SavedFinding:
        """Insert a saved finding."""
        finding = SavedFinding(
            user_id=user_id, workspace_id=workspace_id, type=type, title=title, content_json=content
        )
        self._session.add(finding)
        await self._session.flush()
        await self._session.refresh(finding)
        return finding

    async def list_findings(self, user_id: UUID, workspace_id: UUID) -> list[SavedFinding]:
        """The workspace's saved findings, oldest first."""
        result = await self._session.scalars(
            select(SavedFinding)
            .where(SavedFinding.workspace_id == workspace_id, SavedFinding.user_id == user_id)
            .order_by(SavedFinding.created_at, SavedFinding.id)
        )
        return list(result)

    async def replace_contradictions(
        self, user_id: UUID, workspace_id: UUID, contradictions: Sequence[Contradiction]
    ) -> None:
        """Replace the workspace's contradictions with the latest analysis."""
        await self._session.execute(
            delete(Contradiction).where(
                Contradiction.workspace_id == workspace_id, Contradiction.user_id == user_id
            )
        )
        for contradiction in contradictions:
            contradiction.user_id = user_id
            contradiction.workspace_id = workspace_id
        self._session.add_all(contradictions)
        await self._session.flush()

    async def list_contradictions(self, user_id: UUID, workspace_id: UUID) -> list[Contradiction]:
        """The workspace's contradictions, oldest first."""
        result = await self._session.scalars(
            select(Contradiction)
            .where(Contradiction.workspace_id == workspace_id, Contradiction.user_id == user_id)
            .order_by(Contradiction.created_at, Contradiction.id)
        )
        return list(result)

    async def replace_gaps(
        self, user_id: UUID, workspace_id: UUID, scope: str, gaps: Sequence[ResearchGap]
    ) -> None:
        """Replace the workspace's gaps of one scope with the latest analysis."""
        await self._session.execute(
            delete(ResearchGap).where(
                ResearchGap.workspace_id == workspace_id,
                ResearchGap.user_id == user_id,
                ResearchGap.scope == scope,
            )
        )
        for gap in gaps:
            gap.user_id = user_id
            gap.workspace_id = workspace_id
            gap.scope = scope
        self._session.add_all(gaps)
        await self._session.flush()

    async def list_gaps(self, user_id: UUID, workspace_id: UUID) -> list[ResearchGap]:
        """The workspace's gaps, oldest first."""
        result = await self._session.scalars(
            select(ResearchGap)
            .where(ResearchGap.workspace_id == workspace_id, ResearchGap.user_id == user_id)
            .order_by(ResearchGap.created_at, ResearchGap.id)
        )
        return list(result)

    async def commit(self) -> None:
        """Commit the session's transaction."""
        await self._session.commit()
