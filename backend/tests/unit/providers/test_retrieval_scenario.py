"""Shows the fake embedder and reranker behave enough like real ones for S2/S3 tests."""

from app.providers.fakes import FakeEmbedder, FakeReranker

CORPUS = [
    "Higher porosity of electrospun PCL scaffolds improved fibroblast infiltration.",
    "Scaffold scaffold scaffold fabrication: every scaffold was made by scaffold casting.",
    "Stiffer hydrogels promoted osteogenic differentiation of mesenchymal stem cells.",
    "Bioprinted cardiac constructs with perfusable channels stayed viable for 28 days.",
]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


async def dense_ranking(question: str) -> list[int]:
    embedder = FakeEmbedder(dimension=384)
    query = await embedder.embed_query(question)
    vectors = await embedder.embed_documents(CORPUS)
    scores = [cosine(query, vector) for vector in vectors]
    return sorted(range(len(CORPUS)), key=lambda i: -scores[i])


async def test_embedder_ranks_the_relevant_chunk_first() -> None:
    ranking = await dense_ranking("How does scaffold porosity affect fibroblast infiltration?")

    assert ranking[0] == 0


async def test_reranker_prefers_coverage_over_term_repetition() -> None:
    scores = await FakeReranker().score("scaffold porosity", CORPUS)

    assert scores[0] > scores[1]
    assert scores[2] == scores[3] == 0.0


async def test_unanswerable_question_scores_low_everywhere() -> None:
    question = "What is the melting point of titanium alloys?"
    embedder = FakeEmbedder(dimension=384)
    query = await embedder.embed_query(question)
    vectors = await embedder.embed_documents(CORPUS)

    rerank_scores = await FakeReranker().score(question, CORPUS)

    assert max(rerank_scores) < 0.2
    assert max(abs(cosine(query, vector)) for vector in vectors) < 0.2
