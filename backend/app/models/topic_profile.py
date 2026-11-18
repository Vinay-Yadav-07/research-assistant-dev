"""Per-workspace topic profile used by the compatibility check (S7, SRS §11.2)."""

from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models._types import EMBEDDING_DIMENSION, UpdatedAt
from app.models.base import Base


class TopicProfile(Base):
    """Centroid of the workspace's document embeddings; keywords and summary come in Phase 2."""

    __tablename__ = "topic_profiles"

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    # Null until the first document is ready (an empty workspace skips the check).
    centroid_embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSION))
    # Documents averaged into the centroid, so it can be updated incrementally.
    document_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    keywords: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    summary: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[UpdatedAt]
