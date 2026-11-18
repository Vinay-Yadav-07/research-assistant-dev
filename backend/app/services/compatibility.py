"""Pre-upload compatibility check (FR-22, SRS §11.2): a fast look at the first pages only.

Nothing is stored. The document's vector is formed as for stored documents (the mean of its
first chunks), but from the first `max_pages` pages, so the result can differ slightly from
the score recorded once the document is ingested.
"""

from uuid import UUID

from app.core.errors import DocumentParseError, NotFoundError
from app.providers.embedding import EmbeddingProvider
from app.providers.parser import DocumentParser
from app.schemas.documents import CompatibilityResult
from app.services.documents import check_pdf
from app.services.ingestion import NO_TEXT, IngestionOptions, prepare_chunks
from app.services.topic_profile import (
    CompatibilityOptions,
    TopicProfileStore,
    is_compatible,
    mean_vector,
    normalize,
    similarity,
)


class CompatibilityService:
    """Scores an uploaded PDF against an owned workspace's topic profile before ingestion."""

    def __init__(
        self,
        store: TopicProfileStore,
        *,
        parser: DocumentParser,
        embedder: EmbeddingProvider,
        options: CompatibilityOptions,
        ingestion: IngestionOptions,
    ) -> None:
        self._store = store
        self._parser = parser
        self._embedder = embedder
        self._options = options
        self._ingestion = ingestion

    async def check(self, user_id: UUID, workspace_id: UUID, data: bytes) -> CompatibilityResult:
        """Score the PDF; an empty workspace skips the check without parsing."""
        state = await self._store.get(user_id, workspace_id)
        if state is None:
            raise NotFoundError("Workspace not found.")
        check_pdf(data)
        threshold = self._options.threshold
        if state.centroid is None:
            return CompatibilityResult(
                score=None, threshold=threshold, compatible=True, skipped=True
            )
        vector = await self.document_vector(data)
        score = similarity(state, vector)
        return CompatibilityResult(
            score=score,
            threshold=threshold,
            compatible=is_compatible(score, threshold),
            skipped=False,
        )

    async def document_vector(self, data: bytes) -> list[float]:
        """Normalized mean embedding of the first chunks of the PDF's first pages."""
        return await pdf_vector(
            data,
            parser=self._parser,
            embedder=self._embedder,
            ingestion=self._ingestion,
            first_chunks=self._options.first_chunks,
            max_pages=self._options.max_pages,
        )


async def pdf_vector(
    data: bytes,
    *,
    parser: DocumentParser,
    embedder: EmbeddingProvider,
    ingestion: IngestionOptions,
    first_chunks: int,
    max_pages: int | None,
) -> list[float]:
    """Normalized mean embedding of the PDF's first chunks, chunked as ingestion does.

    With `max_pages=None` the whole PDF is parsed, as for a stored document.
    """
    parsed = await parser.parse(data, max_pages=max_pages)
    drafts = prepare_chunks(parsed.pages, embedder.count_tokens, ingestion)
    if not drafts:
        raise DocumentParseError(NO_TEXT)
    first = [draft.text for draft in drafts[:first_chunks]]
    return normalize(mean_vector(await embedder.embed_documents(first)))
