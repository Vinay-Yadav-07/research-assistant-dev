"""The real local models; downloads weights on first use. Run: `uv run pytest -m integration`."""

import pytest

from app.core.config import Settings
from app.providers.factory import build_providers
from app.providers.nli import NLIPair

pytestmark = pytest.mark.integration

PASSAGES = [
    "Aligned electrospun fibres increased osteogenic differentiation of mesenchymal stem cells.",
    "The stock market fell sharply after the central bank raised interest rates.",
]


@pytest.fixture(scope="module")
def local_settings() -> Settings:
    return Settings(
        _env_file=None,
        embedding_provider="sentence_transformers",
        reranker_provider="cross_encoder",
        nli_provider="cross_encoder",
    )


async def test_embedder_ranks_the_relevant_passage_first(local_settings: Settings) -> None:
    embedder = build_providers(local_settings).embedder

    query = await embedder.embed_query("Does fibre alignment affect stem cell differentiation?")
    passages = await embedder.embed_documents(PASSAGES)

    assert len(query) == local_settings.embedding_dimension
    relevant, unrelated = (sum(a * b for a, b in zip(query, p, strict=True)) for p in passages)
    assert relevant > unrelated


async def test_reranker_scores_relevance_in_unit_interval(local_settings: Settings) -> None:
    reranker = build_providers(local_settings).reranker

    relevant, unrelated = await reranker.score("fibre alignment and stem cells", PASSAGES)

    assert 0.0 <= unrelated < relevant <= 1.0


async def test_nli_detects_entailment_and_contradiction(local_settings: Settings) -> None:
    nli = build_providers(local_settings).nli
    premise = "The coated scaffolds had a compressive strength of 4.19 MPa, the bare ones 2.90 MPa."

    entailed, contradicted = await nli.classify(
        [
            NLIPair(premise=premise, hypothesis="Coating increased the compressive strength."),
            NLIPair(premise=premise, hypothesis="Coating reduced the compressive strength."),
        ]
    )

    assert entailed.entailment > max(entailed.neutral, entailed.contradiction)
    assert contradicted.contradiction > max(contradicted.neutral, contradicted.entailment)
