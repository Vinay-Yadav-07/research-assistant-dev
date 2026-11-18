"""S2 retrieval with fake embedder and reranker over an in-memory chunk store.

The SQL (isolation, exact dense search, full-text queries) is covered by
`tests/integration/test_retrieval_db.py`.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from app.core.errors import InvalidInputError, NotFoundError
from app.providers.fakes import FakeEmbedder, FakeReranker
from app.repositories.chunks import ChunkHit, ChunkRecord, paper_words
from app.services.retrieval import RetrievalOptions, RetrievalService, reciprocal_rank_fusion

USER = uuid4()
WORKSPACE = uuid4()
EMBEDDER = FakeEmbedder(dimension=384)


@dataclass
class StoredChunk:
    workspace_id: UUID
    user_id: UUID
    record: ChunkRecord
    embedding: list[float]
    model: str


class InMemoryChunkStore:
    """Dense = exact cosine, lexical = shared-word count; both scoped like the repository."""

    def __init__(self) -> None:
        self.chunks: list[StoredChunk] = []
        self.workspaces: dict[UUID, UUID] = {WORKSPACE: USER}
        self.dense_calls: list[tuple[str, int]] = []
        self.lexical_queries: list[str] = []

    async def add(
        self,
        text: str,
        *,
        workspace_id: UUID = WORKSPACE,
        user_id: UUID = USER,
        page: int = 1,
        document_id: UUID | None = None,
        title: str = "Paper",
    ) -> UUID:
        record = ChunkRecord(
            chunk_id=uuid4(),
            document_id=document_id or uuid4(),
            document_title=title,
            chunk_index=len(self.chunks),
            page_start=page,
            page_end=page,
            section="Results",
            text=text,
        )
        [embedding] = await EMBEDDER.embed_documents([text])
        self.chunks.append(
            StoredChunk(workspace_id, user_id, record, embedding, EMBEDDER.model_name)
        )
        return record.chunk_id

    def _visible(
        self, user_id: UUID, workspace_id: UUID, document_ids: Sequence[UUID] | None = None
    ) -> list[StoredChunk]:
        if self.workspaces.get(workspace_id) != user_id:
            return []
        return [
            c
            for c in self.chunks
            if c.workspace_id == workspace_id
            and c.user_id == user_id
            and (document_ids is None or c.record.document_id in document_ids)
        ]

    async def workspace_owned(self, user_id: UUID, workspace_id: UUID) -> bool:
        return self.workspaces.get(workspace_id) == user_id

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
        self.dense_calls.append((embedding_model, limit))
        scored = [
            ChunkHit(
                c.record.chunk_id,
                1 - sum(a * b for a, b in zip(query_vector, c.embedding, strict=True)),
            )
            for c in self._visible(user_id, workspace_id, document_ids)
            if c.model == embedding_model
        ]
        return sorted(scored, key=lambda hit: hit.score)[:limit]

    async def lexical_search(
        self,
        user_id: UUID,
        workspace_id: UUID,
        query: str,
        *,
        limit: int,
        document_ids: Sequence[UUID] | None = None,
    ) -> list[ChunkHit]:
        self.lexical_queries.append(query)
        terms = set(words(query))
        scored = [
            ChunkHit(c.record.chunk_id, float(len(terms & set(words(c.record.text)))))
            for c in self._visible(user_id, workspace_id, document_ids)
        ]
        return sorted([h for h in scored if h.score > 0], key=lambda hit: -hit.score)[:limit]

    async def load(
        self, user_id: UUID, workspace_id: UUID, chunk_ids: Sequence[UUID]
    ) -> list[ChunkRecord]:
        wanted = set(chunk_ids)
        return [
            c.record for c in self._visible(user_id, workspace_id) if c.record.chunk_id in wanted
        ]

    async def match_documents(
        self, user_id: UUID, workspace_id: UUID, refs: Sequence[str]
    ) -> list[UUID]:
        names = [paper_words(ref) for ref in refs if len(paper_words(ref)) >= 3]
        found = {
            c.record.document_id
            for c in self._visible(user_id, workspace_id)
            for name in names
            if c.record.document_title
            and (
                name in paper_words(c.record.document_title)
                or f" {paper_words(c.record.document_title)} " in f" {name} "
            )
        }
        return sorted(found, key=str)


def words(text: str) -> list[str]:
    return re.findall(r"[a-z]{4,}", text.lower())


def options(**overrides: int) -> RetrievalOptions:
    values = {
        "dense_top_k": 30,
        "lexical_top_k": 30,
        "rrf_k": 60,
        "rerank_candidates": 20,
        "top_k": 8,
        "max_query_chars": 200,
    }
    values.update(overrides)
    return RetrievalOptions(**values)


def service(store: InMemoryChunkStore, **overrides: int) -> RetrievalService:
    return RetrievalService(
        store, embedder=EMBEDDER, reranker=FakeReranker(), options=options(**overrides)
    )


@pytest.fixture
def store() -> InMemoryChunkStore:
    return InMemoryChunkStore()


# --- RRF ---


def test_rrf_rewards_agreement_between_rankings() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()

    fused = reciprocal_rank_fusion([[a, b, c], [b, c]], k=60)

    assert [item for item, _ in fused] == [b, c, a]
    assert fused[0][1] == pytest.approx(1 / 62 + 1 / 61)
    assert fused[2][1] == pytest.approx(1 / 61)


def test_rrf_handles_empty_rankings_and_ties_deterministically() -> None:
    a, b = sorted([uuid4(), uuid4()], key=str)

    assert reciprocal_rank_fusion([[], []], k=60) == []
    assert [item for item, _ in reciprocal_rank_fusion([[b], [a]], k=60)] == [a, b]


def test_smaller_k_weights_top_ranks_more() -> None:
    a, b = uuid4(), uuid4()
    # a: rank 1 in one list only; b: rank 4 in both (2/64 > 1/61, but 2/5 < 1/2).
    rankings = [[a, uuid4(), uuid4(), b], [uuid4(), uuid4(), uuid4(), b]]

    def order(k: int) -> list[UUID]:
        return [item for item, _ in reciprocal_rank_fusion(rankings, k=k) if item in (a, b)]

    assert order(60) == [b, a]
    assert order(1) == [a, b]


# --- service ---


async def test_relevant_chunk_ranks_first_with_provenance(store: InMemoryChunkStore) -> None:
    relevant = await store.add(
        "Higher porosity of electrospun scaffolds improved fibroblast infiltration.", page=4
    )
    await store.add("Scaffold scaffold scaffold fabrication by scaffold casting.")
    await store.add("Stiffer hydrogels promoted osteogenic differentiation of stem cells.")

    result = await service(store).retrieve(
        USER, WORKSPACE, "How does scaffold porosity affect fibroblast infiltration?"
    )

    top = result.evidence[0]
    assert top.chunk_id == relevant
    assert (top.page_start, top.page_end, top.section, top.document_title) == (
        4,
        4,
        "Results",
        "Paper",
    )
    assert top.dense_rank is not None and top.lexical_rank is not None
    assert top.rerank_score is not None and 0 <= top.rerank_score <= 1
    scores = [chunk.rerank_score or 0 for chunk in result.evidence]
    assert scores == sorted(scores, reverse=True)


async def test_evidence_is_limited_to_top_k(store: InMemoryChunkStore) -> None:
    for i in range(12):
        await store.add(f"Scaffold porosity measurement number {i} with micro tomography.")

    default = await service(store).retrieve(USER, WORKSPACE, "scaffold porosity")
    custom = await service(store).retrieve(USER, WORKSPACE, "scaffold porosity", top_k=3)

    assert len(default.evidence) == 8
    assert len(custom.evidence) == 3


async def test_only_rerank_candidates_are_reranked(store: InMemoryChunkStore) -> None:
    for i in range(10):
        await store.add(f"Scaffold porosity sample {i}.")

    debug = await service(store, rerank_candidates=4, top_k=8).debug(USER, WORKSPACE, "porosity")

    assert len(debug.candidates) == 10
    assert sum(c.rerank_score is not None for c in debug.candidates) == 4
    assert len(debug.evidence) == 4
    assert {c.chunk_id for c in debug.evidence} == {c.chunk_id for c in debug.candidates[:4]}


async def test_search_limits_and_model_come_from_options(store: InMemoryChunkStore) -> None:
    await store.add("porosity")

    debug = await service(store, dense_top_k=7, lexical_top_k=5).debug(USER, WORKSPACE, "porosity")

    assert store.dense_calls == [(EMBEDDER.model_name, 7)]
    assert debug.embedding_model == EMBEDDER.model_name
    assert debug.reranker_model == "fake-coverage-reranker-v1"
    assert debug.timings.total_ms >= 0


async def test_chunk_found_by_one_search_only_is_still_a_candidate(
    store: InMemoryChunkStore,
) -> None:
    lexical_only = await store.add("Porosity porosity porosity.")

    debug = await service(store, dense_top_k=1).debug(USER, WORKSPACE, "porosity")

    candidate = next(c for c in debug.candidates if c.chunk_id == lexical_only)
    assert candidate.lexical_rank == 1


async def test_empty_workspace_returns_no_evidence(store: InMemoryChunkStore) -> None:
    debug = await service(store).debug(USER, WORKSPACE, "anything at all")

    assert debug.evidence == []
    assert debug.candidates == []
    assert (debug.dense_hits, debug.lexical_hits) == (0, 0)


async def test_other_workspaces_are_never_searched(store: InMemoryChunkStore) -> None:
    other = uuid4()
    store.workspaces[other] = USER
    await store.add("Scaffold porosity in the other workspace.", workspace_id=other)
    mine = await store.add("Unrelated cardiac patch text.")

    result = await service(store).retrieve(USER, WORKSPACE, "scaffold porosity")

    assert [chunk.chunk_id for chunk in result.evidence] == [mine]


async def test_another_users_workspace_is_not_found(store: InMemoryChunkStore) -> None:
    with pytest.raises(NotFoundError):
        await service(store).retrieve(uuid4(), WORKSPACE, "porosity")


@pytest.mark.parametrize("query", ["", "   \n\t"])
async def test_empty_query_is_invalid(store: InMemoryChunkStore, query: str) -> None:
    with pytest.raises(InvalidInputError, match="empty"):
        await service(store).retrieve(USER, WORKSPACE, query)


async def test_overlong_query_is_invalid(store: InMemoryChunkStore) -> None:
    with pytest.raises(InvalidInputError) as raised:
        await service(store).retrieve(USER, WORKSPACE, "x" * 201)

    assert raised.value.details == {"max_chars": 200}


async def test_query_is_stripped(store: InMemoryChunkStore) -> None:
    result = await service(store).retrieve(USER, WORKSPACE, "  porosity  ")

    assert result.query == "porosity"


# --- named papers and search keywords ---


async def test_document_filter_limits_evidence_to_those_documents(
    store: InMemoryChunkStore,
) -> None:
    named = uuid4()
    await store.add("Porosity of sintered scaffolds was ninety percent.", document_id=named)
    await store.add("Porosity of printed scaffolds was seventy percent.")

    result = await service(store).retrieve(
        USER, WORKSPACE, "scaffold porosity", document_ids=[named]
    )

    assert [chunk.document_id for chunk in result.evidence] == [named]


async def test_empty_document_filter_finds_nothing(store: InMemoryChunkStore) -> None:
    await store.add("Porosity of sintered scaffolds was ninety percent.")

    result = await service(store).retrieve(USER, WORKSPACE, "scaffold porosity", document_ids=[])

    assert result.evidence == []


async def test_extra_terms_reach_only_the_full_text_search(store: InMemoryChunkStore) -> None:
    await store.add("Gelatin coatings degraded within weeks.")

    result = await service(store).retrieve(
        USER, WORKSPACE, "coating breakdown", extra_terms=["gelatin", " ", "degradation"]
    )

    assert store.lexical_queries == ["coating breakdown gelatin degradation"]
    assert result.query == "coating breakdown"
    assert [chunk.text for chunk in result.evidence] == ["Gelatin coatings degraded within weeks."]


async def test_paper_references_resolve_to_workspace_documents(
    store: InMemoryChunkStore,
) -> None:
    hydrogel = uuid4()
    await store.add("Text.", document_id=hydrogel, title="Hydrogels for Biomedical Applications")
    await store.add("Text.", title="Plasmonic Nanomaterials")
    await store.add("Text.", workspace_id=uuid4(), title="Hydrogels elsewhere")

    found = await service(store).resolve_papers(USER, WORKSPACE, ["hydrogels", "xy"])

    assert found == [hydrogel]
    assert await service(store).resolve_papers(USER, WORKSPACE, []) == []


async def test_dense_only_uses_neither_full_text_nor_reranker(store: InMemoryChunkStore) -> None:
    for i in range(10):
        await store.add(f"Scaffold porosity sample {i}.")

    result = await service(store, top_k=8).retrieve_dense(USER, WORKSPACE, "  scaffold porosity ")

    assert store.lexical_queries == []
    assert store.dense_calls == [(EMBEDDER.model_name, 8)]
    assert result.query == "scaffold porosity"
    assert [chunk.dense_rank for chunk in result.evidence] == list(range(1, 9))
    assert all(c.rerank_score is None and c.lexical_rank is None for c in result.evidence)


async def test_dense_only_keeps_the_dense_order_and_top_k(store: InMemoryChunkStore) -> None:
    near = await store.add("Higher porosity of electrospun scaffolds improved infiltration.")
    await store.add("Stiffer hydrogels promoted osteogenic differentiation.")

    result = await service(store).retrieve_dense(
        USER, WORKSPACE, "Higher porosity of electrospun scaffolds improved infiltration.", top_k=1
    )

    assert [chunk.chunk_id for chunk in result.evidence] == [near]


async def test_dense_only_is_scoped_to_the_users_workspace(store: InMemoryChunkStore) -> None:
    other = uuid4()
    store.workspaces[other] = USER
    await store.add("Scaffold porosity in the other workspace.", workspace_id=other)
    mine = await store.add("Unrelated cardiac patch text.")

    result = await service(store).retrieve_dense(USER, WORKSPACE, "scaffold porosity")

    assert [chunk.chunk_id for chunk in result.evidence] == [mine]
    with pytest.raises(NotFoundError):
        await service(store).retrieve_dense(uuid4(), WORKSPACE, "porosity")
    with pytest.raises(InvalidInputError):
        await service(store).retrieve_dense(USER, WORKSPACE, " ")


def test_paper_words_fold_case_and_punctuation() -> None:
    assert paper_words("  “Gels”: a Review (2023)! ") == "gels a review 2023"
