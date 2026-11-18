"""Request schema for the retrieval debug endpoint (S2)."""

from pydantic import BaseModel, ConfigDict, Field


class RetrievalDebugRequest(BaseModel):
    """Body of `POST /workspaces/{id}/retrieval/debug`. Length is checked by the service (S6)."""

    model_config = ConfigDict(extra="forbid")

    query: str
    # Evidence kept after reranking; defaults to RETRIEVAL_TOP_K.
    top_k: int | None = Field(default=None, ge=1, le=50)
