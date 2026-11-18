import asyncio
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.providers.fakes import FakeEmbedder

BACKEND_DIR = Path(__file__).resolve().parents[3]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder(dimension=384)


async def test_vectors_have_the_configured_dimension_and_unit_norm(embedder: FakeEmbedder) -> None:
    vectors = await embedder.embed_documents(["scaffold porosity", "hydrogel stiffness", ""])

    assert embedder.dimension == 384
    for vector in vectors:
        assert len(vector) == 384
        assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0)


async def test_model_name_identifies_the_fake(embedder: FakeEmbedder) -> None:
    assert embedder.model_name == "fake-hash-384-v1"
    assert FakeEmbedder(dimension=16).model_name == "fake-hash-16-v1"


def test_dimension_must_be_positive() -> None:
    with pytest.raises(ValueError):
        FakeEmbedder(dimension=0)


async def test_identical_text_has_cosine_one(embedder: FakeEmbedder) -> None:
    a, b = await embedder.embed_documents(
        ["Scaffold porosity matters.", "Scaffold porosity matters."]
    )

    assert math.isclose(cosine(a, b), 1.0)


async def test_shared_vocabulary_scores_higher_than_unrelated_text(embedder: FakeEmbedder) -> None:
    query = await embedder.embed_query("scaffold porosity and fibroblast infiltration")
    related, unrelated = await embedder.embed_documents(
        [
            "Higher porosity improved fibroblast infiltration into the scaffold.",
            "The melting point of titanium alloys depends on composition.",
        ]
    )

    assert cosine(query, related) > 0.5
    assert abs(cosine(query, unrelated)) < 0.2


async def test_case_punctuation_and_plurals_are_ignored(embedder: FakeEmbedder) -> None:
    a = await embedder.embed_query("Electrospun SCAFFOLDS, porosity!")
    b = await embedder.embed_query("electrospun scaffold porosity")

    assert math.isclose(cosine(a, b), 1.0)


async def test_query_and_document_embeddings_match(embedder: FakeEmbedder) -> None:
    text = "fibre alignment directs neurite outgrowth"

    assert await embedder.embed_query(text) == (await embedder.embed_documents([text]))[0]


async def test_empty_text_is_never_a_zero_vector(embedder: FakeEmbedder) -> None:
    for text in ["", "   ", "!!!", "the of and"]:
        vector = await embedder.embed_query(text)
        assert any(value != 0.0 for value in vector)


async def test_batch_order_is_preserved(embedder: FakeEmbedder) -> None:
    texts = ["alpha scaffold", "beta hydrogel", "gamma bioprinting"]

    batch = await embedder.embed_documents(texts)

    assert batch == [await embedder.embed_query(text) for text in texts]


@pytest.mark.parametrize("hash_seed", ["0", "12345"])
def test_vectors_are_identical_across_processes(embedder: FakeEmbedder, hash_seed: str) -> None:
    text = "Porosity of electrospun PCL scaffolds"
    script = (
        "import asyncio, json\n"
        "from app.providers.fakes import FakeEmbedder\n"
        f"print(json.dumps(asyncio.run(FakeEmbedder(dimension=384).embed_query({text!r}))))\n"
    )
    env = {**os.environ, "PYTHONHASHSEED": hash_seed}

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(completed.stdout) == asyncio.run(embedder.embed_query(text))


def test_fake_counts_whitespace_words() -> None:
    assert FakeEmbedder(8).count_tokens("  Porous scaffolds,\n support cells. ") == 4
    assert FakeEmbedder(8).count_tokens("") == 0
