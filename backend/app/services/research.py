"""Research outputs (FR-20, FR-21) and saved findings with their export (FR-26, FR-32).

Callers of `save_contradictions` and `save_gaps` check workspace ownership first; the findings
methods check it themselves and raise NotFoundError for non-owned workspaces (D-047).
"""

from collections.abc import Sequence
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel

from app.core.errors import NotFoundError
from app.models.document import Document
from app.models.research import Contradiction, ResearchGap, SavedFinding
from app.schemas.research import FindingCreate, FindingRead
from app.services.export import cited_document_ids, to_bibtex, to_markdown


class ContradictionRecord(BaseModel):
    """One contradiction as stored: both findings, snapshots of their passages, and the label."""

    claim_a: str
    claim_b: str
    # Citation snapshots, each tagged with the finding it belongs to (`side`: "a" or "b").
    evidence_refs: list[dict[str, Any]]
    context_note: str
    label: Literal["potential_contradiction", "context_dependent"]


class GapRecord(BaseModel):
    """One corpus gap as stored, with snapshots of the passages it cites."""

    description: str
    evidence_refs: list[dict[str, Any]]


class ResearchStore(Protocol):
    """Persistence the service needs; `ResearchRepository` implements it."""

    async def replace_contradictions(
        self, user_id: UUID, workspace_id: UUID, contradictions: Sequence[Contradiction]
    ) -> None: ...

    async def replace_gaps(
        self, user_id: UUID, workspace_id: UUID, scope: str, gaps: Sequence[ResearchGap]
    ) -> None: ...

    async def workspace_name(self, user_id: UUID, workspace_id: UUID) -> str | None: ...

    async def add_finding(
        self, user_id: UUID, workspace_id: UUID, *, type: str, title: str, content: dict[str, Any]
    ) -> SavedFinding: ...

    async def list_findings(self, user_id: UUID, workspace_id: UUID) -> list[SavedFinding]: ...

    async def documents(self, user_id: UUID, document_ids: Sequence[UUID]) -> list[Document]: ...

    async def commit(self) -> None: ...


class ResearchService:
    """Stores one user's research outputs."""

    def __init__(self, store: ResearchStore) -> None:
        self._store = store

    async def save_contradictions(
        self, user_id: UUID, workspace_id: UUID, records: Sequence[ContradictionRecord]
    ) -> None:
        """Replace the workspace's contradictions with `records` and commit."""
        await self._store.replace_contradictions(
            user_id,
            workspace_id,
            [Contradiction(**record.model_dump()) for record in records],
        )
        await self._store.commit()

    async def save_gaps(
        self, user_id: UUID, workspace_id: UUID, records: Sequence[GapRecord]
    ) -> None:
        """Replace the workspace's corpus gaps with `records` and commit."""
        await self._store.replace_gaps(
            user_id,
            workspace_id,
            "corpus",
            [ResearchGap(**record.model_dump()) for record in records],
        )
        await self._store.commit()

    async def save_finding(
        self, user_id: UUID, workspace_id: UUID, body: FindingCreate
    ) -> FindingRead:
        """Store an output the user wants to keep."""
        await self._require_workspace(user_id, workspace_id)
        finding = await self._store.add_finding(
            user_id, workspace_id, type=body.type, title=body.title.strip(), content=body.content
        )
        await self._store.commit()
        return FindingRead.model_validate(finding)

    async def list_findings(self, user_id: UUID, workspace_id: UUID) -> list[FindingRead]:
        """The workspace's saved findings, oldest first."""
        await self._require_workspace(user_id, workspace_id)
        findings = await self._store.list_findings(user_id, workspace_id)
        return [FindingRead.model_validate(f) for f in findings]

    async def export_markdown(self, user_id: UUID, workspace_id: UUID) -> str:
        """All saved findings as one Markdown document with numbered references."""
        name = await self._require_workspace(user_id, workspace_id)
        return to_markdown(name, await self._store.list_findings(user_id, workspace_id))

    async def export_bibtex(self, user_id: UUID, workspace_id: UUID) -> str:
        """One BibTeX entry per corpus paper the saved findings cite."""
        await self._require_workspace(user_id, workspace_id)
        ids = cited_document_ids(await self._store.list_findings(user_id, workspace_id))
        by_id = {d.id: d for d in await self._store.documents(user_id, ids)}
        return to_bibtex([by_id[i] for i in ids if i in by_id])

    async def _require_workspace(self, user_id: UUID, workspace_id: UUID) -> str:
        name = await self._store.workspace_name(user_id, workspace_id)
        if name is None:
            raise NotFoundError("Workspace not found.")
        return name
