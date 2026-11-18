"""In-memory topic profile store mirroring `TopicProfileRepository`'s ownership rules."""

from dataclasses import dataclass, field
from uuid import UUID

from app.repositories.topic_profiles import ProfileState
from app.services.topic_profile import mean_vector


@dataclass
class LinkResult:
    score: float | None = None
    override: bool = False


@dataclass
class InMemoryProfileStore:
    """Workspace owners, profiles, document chunk vectors, and link scores."""

    workspaces: dict[UUID, UUID] = field(default_factory=dict)
    profiles: dict[UUID, ProfileState] = field(default_factory=dict)
    # document id -> (owner, chunk embeddings in chunk order)
    chunks: dict[UUID, tuple[UUID, list[list[float]]]] = field(default_factory=dict)
    links: dict[tuple[UUID, UUID], LinkResult] = field(default_factory=dict)
    locked: list[UUID] = field(default_factory=list)

    async def get(self, user_id: UUID, workspace_id: UUID) -> ProfileState | None:
        if self.workspaces.get(workspace_id) != user_id:
            return None
        return self.profiles.get(workspace_id, ProfileState(centroid=None, document_count=0))

    async def lock(self, user_id: UUID, workspace_id: UUID) -> ProfileState | None:
        state = await self.get(user_id, workspace_id)
        if state is not None:
            self.locked.append(workspace_id)
        return state

    async def save(self, workspace_id: UUID, state: ProfileState) -> None:
        self.profiles[workspace_id] = state

    async def document_vector(
        self, user_id: UUID, document_id: UUID, *, first_chunks: int
    ) -> list[float] | None:
        owner, vectors = self.chunks.get(document_id, (None, []))
        if owner != user_id or not vectors:
            return None
        return mean_vector(vectors[:first_chunks])

    async def linked_workspaces(self, user_id: UUID, document_id: UUID) -> list[UUID]:
        return sorted(
            workspace_id
            for workspace_id, linked in self.links
            if linked == document_id and self.workspaces.get(workspace_id) == user_id
        )

    async def set_score(self, workspace_id: UUID, document_id: UUID, score: float | None) -> None:
        self.links[(workspace_id, document_id)].score = score
