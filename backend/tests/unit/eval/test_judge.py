"""Ragas metrics through our providers (SRS §17.3), with the fake LLM and embedder."""

import pytest
from ragas.metrics.collections.answer_relevancy.util import AnswerRelevanceOutput
from ragas.metrics.collections.faithfulness.util import (
    NLIStatementOutput,
    StatementGeneratorOutput,
)

from app.core.config import Settings
from app.core.errors import ProviderConfigurationError
from app.providers.fakes import FakeEmbedder, FakeLLM
from eval.judge import RagasEmbeddings, RagasLLM, RagasScorer, build_judge

QUESTION = "Which protein adsorbs first on implants?"


def verdicts(*values: int) -> dict[str, object]:
    return {
        "statements": [
            {"statement": f"s{i}", "reason": "r", "verdict": v} for i, v in enumerate(values)
        ]
    }


def relevance(question: str, noncommittal: int = 0) -> dict[str, object]:
    return {"question": question, "noncommittal": noncommittal}


async def test_llm_adapter_sends_one_user_message_with_the_schema() -> None:
    llm = FakeLLM(structured={StatementGeneratorOutput: [{"statements": ["a", "b"]}]})

    output = await RagasLLM(llm).agenerate("PROMPT", StatementGeneratorOutput)

    assert output.statements == ["a", "b"]
    [call] = llm.calls
    assert call.schema is StatementGeneratorOutput
    assert [(m.role, m.content) for m in call.messages] == [("user", "PROMPT")]
    with pytest.raises(NotImplementedError):
        RagasLLM(llm).generate("PROMPT", StatementGeneratorOutput)


async def test_embedding_adapter_uses_passage_embeddings() -> None:
    embedder = FakeEmbedder(dimension=16)
    adapter = RagasEmbeddings(embedder)

    assert await adapter.aembed_text("x") == (await embedder.embed_documents(["x"]))[0]
    assert await adapter.aembed_texts(["x", "y"]) == await embedder.embed_documents(["x", "y"])


async def test_scorer_computes_faithfulness_and_relevancy() -> None:
    llm = FakeLLM(
        structured={
            StatementGeneratorOutput: [{"statements": ["s0", "s1", "s2", "s3"]}],
            NLIStatementOutput: [verdicts(1, 1, 1, 0)],
            AnswerRelevanceOutput: [relevance(QUESTION)],
        }
    )
    scorer = RagasScorer(llm, FakeEmbedder(dimension=64), strictness=1)

    scores = await scorer.score(QUESTION, "Fibrinogen adsorbs first.", ["Fibrinogen first."])

    assert scores.faithfulness == 0.75
    assert scores.answer_relevancy == pytest.approx(1.0)
    assert len(llm.calls) == 3


async def test_without_passages_only_relevancy_is_scored() -> None:
    llm = FakeLLM(
        structured={AnswerRelevanceOutput: [relevance(QUESTION, 1), relevance(QUESTION, 1)]}
    )
    scorer = RagasScorer(llm, FakeEmbedder(dimension=64), strictness=2)

    scores = await scorer.score(QUESTION, "Probably fibrinogen.", [])

    assert scores.faithfulness is None
    # Every generated question noncommittal: Ragas scores the answer 0.
    assert scores.answer_relevancy == 0.0
    assert len(llm.calls) == 2


async def test_no_statements_gives_no_faithfulness_score() -> None:
    llm = FakeLLM(
        structured={
            StatementGeneratorOutput: [{"statements": []}],
            AnswerRelevanceOutput: [relevance(QUESTION)],
        }
    )
    scores = await RagasScorer(llm, FakeEmbedder(dimension=64), strictness=1).score(
        QUESTION, "Hmm.", ["Fibrinogen first."]
    )

    assert scores.faithfulness is None


def test_fake_judge_needs_no_key() -> None:
    assert build_judge(Settings(eval_judge_provider="fake")).model_name == "fake-llm-judge"


def test_judge_must_not_be_the_strong_tier_model() -> None:
    settings = Settings(
        llm_strong_provider="groq",
        llm_strong_model="openai/gpt-oss-120b",
        eval_judge_provider="groq",
        eval_judge_model="openai/gpt-oss-120b",
        groq_api_key="k",
    )
    with pytest.raises(ProviderConfigurationError, match="must differ"):
        build_judge(settings)


def test_demo_cannot_judge() -> None:
    with pytest.raises(ProviderConfigurationError, match="demo"):
        build_judge(Settings(eval_judge_provider="demo"))


def test_hosted_judge_gets_its_own_model_and_limits() -> None:
    settings = Settings(
        llm_strong_provider="gemini",
        eval_judge_provider="groq",
        eval_judge_model="openai/gpt-oss-120b",
        groq_api_key="k",
    )
    assert build_judge(settings).model_name == "openai/gpt-oss-120b"
