"""Topic profile and compatibility scoring (S7, FR-22, SRS §11.2; centroid only, D-045).

A document's topic vector is the normalized mean of its first chunk embeddings (abstract and
first section). A workspace's centroid is the mean of its ready documents' vectors, updated
incrementally when a document becomes ready, is linked, or is removed. Compatibility is the
cosine similarity between a document vector and the centroid; an empty workspace has none.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.core.config import Settings
from app.core.errors import CompatibilityWarningError, NotFoundError
from app.repositories.topic_profiles import ProfileState


class TopicProfileStore(Protocol):
    """Persistence S7 needs; `TopicProfileRepository` implements it."""

    async def get(self, user_id: UUID, workspace_id: UUID) -> ProfileState | None: ...

    async def lock(self, user_id: UUID, workspace_id: UUID) -> ProfileState | None: ...

    async def save(self, workspace_id: UUID, state: ProfileState) -> None: ...

    async def document_vector(
        self, user_id: UUID, document_id: UUID, *, first_chunks: int
    ) -> list[float] | None: ...

    async def linked_workspaces(self, user_id: UUID, document_id: UUID) -> list[UUID]: ...

    async def set_score(
        self, workspace_id: UUID, document_id: UUID, score: float | None
    ) -> None: ...


@dataclass(frozen=True)
class CompatibilityOptions:
    """How document vectors are formed and when a document counts as unrelated."""

    first_chunks: int
    max_pages: int
    threshold: float

    @classmethod
    def from_settings(cls, settings: Settings) -> "CompatibilityOptions":
        """Read the options from the application settings."""
        return cls(
            first_chunks=settings.compatibility_chunks,
            max_pages=settings.compatibility_max_pages,
            threshold=settings.compatibility_threshold,
        )


def normalize(vector: Sequence[float]) -> list[float]:
    """The vector scaled to unit length (a zero vector is returned unchanged)."""
    norm = math.sqrt(sum(value * value for value in vector))
    return list(vector) if norm == 0.0 else [value / norm for value in vector]


def mean_vector(vectors: Sequence[Sequence[float]]) -> list[float]:
    """Element-wise mean of equally long vectors."""
    count = len(vectors)
    return [sum(values) / count for values in zip(*vectors, strict=True)]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity; 0.0 if either vector is zero."""
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    if norm == 0.0:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm


def add_to_centroid(state: ProfileState, vector: Sequence[float]) -> ProfileState:
    """The profile with one more document averaged in."""
    if state.centroid is None or state.document_count <= 0:
        return ProfileState(centroid=list(vector), document_count=1)
    count = state.document_count
    centroid = [(c * count + v) / (count + 1) for c, v in zip(state.centroid, vector, strict=True)]
    return ProfileState(centroid=centroid, document_count=count + 1)


def remove_from_centroid(state: ProfileState, vector: Sequence[float]) -> ProfileState:
    """The profile with one document taken out; empty again after the last one."""
    if state.centroid is None or state.document_count <= 1:
        return ProfileState(centroid=None, document_count=0)
    count = state.document_count
    centroid = [(c * count - v) / (count - 1) for c, v in zip(state.centroid, vector, strict=True)]
    return ProfileState(centroid=centroid, document_count=count - 1)


def similarity(state: ProfileState, vector: Sequence[float]) -> float | None:
    """Compatibility of a document vector with the profile; None for an empty workspace."""
    if state.centroid is None:
        return None
    return cosine(state.centroid, vector)


def is_compatible(score: float | None, threshold: float) -> bool:
    """True unless the score is known and below the threshold."""
    return score is None or score >= threshold


class TopicProfileService:
    """Keeps workspace centroids in step with their ready documents, in the caller's transaction.

    Callers lock the document row first, so a document becoming ready and being linked or
    removed are serialized; profile rows are then locked in workspace id order.
    """

    def __init__(self, store: TopicProfileStore, options: CompatibilityOptions) -> None:
        self._store = store
        self._options = options

    async def include(
        self, user_id: UUID, workspace_id: UUID, document_id: UUID, *, override: bool
    ) -> float | None:
        """Add a ready document to the centroid and return its score from before the update.

        Raises `CompatibilityWarningError` (nothing changed) if the score is below the
        threshold and `override` is false.
        """
        vector = await self._document_vector(user_id, document_id)
        if vector is None:
            return None
        state = await self._store.lock(user_id, workspace_id)
        if state is None:
            raise NotFoundError("Workspace not found.")
        score = similarity(state, vector)
        if not override and not is_compatible(score, self._options.threshold):
            raise CompatibilityWarningError(details=self.warning_details(score))
        await self._store.save(workspace_id, add_to_centroid(state, vector))
        return score

    async def exclude(self, user_id: UUID, workspace_id: UUID, document_id: UUID) -> None:
        """Take a ready document out of the workspace centroid before it is unlinked."""
        vector = await self._document_vector(user_id, document_id)
        if vector is None:
            return
        state = await self._store.lock(user_id, workspace_id)
        if state is not None:
            await self._store.save(workspace_id, remove_from_centroid(state, vector))

    async def document_ready(self, user_id: UUID, document_id: UUID) -> None:
        """Score a newly ready document in each workspace it is linked to and add it there.

        The user was warned before upload, so nothing is refused here.
        """
        for workspace_id in await self._store.linked_workspaces(user_id, document_id):
            score = await self.include(user_id, workspace_id, document_id, override=True)
            await self._store.set_score(workspace_id, document_id, score)

    def warning_details(self, score: float | None) -> dict[str, float | None]:
        """Details sent with a compatibility warning."""
        return {"score": score, "threshold": self._options.threshold}

    async def _document_vector(self, user_id: UUID, document_id: UUID) -> list[float] | None:
        mean = await self._store.document_vector(
            user_id, document_id, first_chunks=self._options.first_chunks
        )
        return None if mean is None else normalize(mean)
