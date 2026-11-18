"""Ragas faithfulness and answer relevancy (SRS §17.3), judged through our own providers.

Ragas metrics call `agenerate(prompt, schema)` on their LLM and `aembed_text(s)` on their
embeddings. The adapters below route those calls through an `LLMProvider` (so retries, rate
limits, usage counting, and the fakes apply) and through the configured embedder. The judge
must not be A3's model (the strong tier), so a judgment never checks itself.
"""

import math
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel
from ragas.embeddings.base import BaseRagasEmbedding
from ragas.llms.base import InstructorBaseRagasLLM
from ragas.metrics.collections import AnswerRelevancy, Faithfulness

from app.core.config import Settings
from app.core.errors import ProviderConfigurationError
from app.providers.embedding import EmbeddingProvider
from app.providers.fakes import FakeLLM
from app.providers.llm import ChatMessage, LLMProvider
from app.providers.rate_limit import RateLimiter

T = TypeVar("T", bound=BaseModel)


class RagasLLM(InstructorBaseRagasLLM):
    """Ragas' structured LLM interface over an `LLMProvider`; one user message per call."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    def generate(self, prompt: str, response_model: type[T]) -> T:
        """Not used: the metrics are scored with `ascore`."""
        raise NotImplementedError("RagasLLM is async only; use agenerate")

    async def agenerate(self, prompt: str, response_model: type[T]) -> T:
        """One structured call validated against Ragas' schema."""
        messages = [ChatMessage(role="user", content=prompt)]
        result = await self._llm.generate_structured(messages, response_model, temperature=0)
        return result.output


class RagasEmbeddings(BaseRagasEmbedding):
    """Ragas' embedding interface over the configured embedder (passage mode, no prefix)."""

    def __init__(self, embedder: EmbeddingProvider) -> None:
        super().__init__()
        self._embedder = embedder

    def embed_text(self, text: str, **kwargs: Any) -> list[float]:
        """Not used: the metrics are scored with `ascore`."""
        raise NotImplementedError("RagasEmbeddings is async only; use aembed_text")

    async def aembed_text(self, text: str, **kwargs: Any) -> list[float]:
        """The embedding of one text."""
        [vector] = await self._embedder.embed_documents([text])
        return vector

    async def aembed_texts(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        """The embeddings of several texts in one batch."""
        return await self._embedder.embed_documents(texts)


@dataclass(frozen=True)
class RagasScores:
    """Scores in [0, 1]; None where the metric does not apply or Ragas returned NaN."""

    faithfulness: float | None
    answer_relevancy: float | None


class RagasScorer:
    """Scores one answer: faithfulness needs passages, relevancy needs only the answer."""

    def __init__(self, judge: LLMProvider, embedder: EmbeddingProvider, *, strictness: int):
        llm = RagasLLM(judge)
        self._faithfulness = Faithfulness(llm=llm)
        self._relevancy = AnswerRelevancy(
            llm=llm, embeddings=RagasEmbeddings(embedder), strictness=strictness
        )

    async def score(self, question: str, answer: str, contexts: list[str]) -> RagasScores:
        """Faithfulness to `contexts` (None without any) and relevancy to `question`."""
        faithfulness = None
        if contexts:
            result = await self._faithfulness.ascore(
                user_input=question, response=answer, retrieved_contexts=contexts
            )
            faithfulness = _finite(result.value)
        relevancy = await self._relevancy.ascore(user_input=question, response=answer)
        return RagasScores(faithfulness=faithfulness, answer_relevancy=_finite(relevancy.value))


def build_judge(settings: Settings) -> LLMProvider:
    """The judge model from `EVAL_JUDGE_*`; refuses the strong tier's model (A3's judge)."""
    provider, model = settings.eval_judge_provider, settings.eval_judge_model
    if provider == "fake":
        return FakeLLM(model_name="fake-llm-judge")
    if provider == "demo":
        raise ProviderConfigurationError("The demo LLM cannot judge an evaluation.")
    if (provider, model) == (settings.llm_strong_provider, settings.llm_strong_model):
        raise ProviderConfigurationError(
            "EVAL_JUDGE_MODEL must differ from LLM_STRONG_MODEL (A3's judge, SRS §17.3).",
            details={"provider": provider, "model": model},
        )
    from app.providers.live.llm_factory import build_hosted_llm

    limiter = RateLimiter(
        requests_per_minute=settings.eval_judge_rpm,
        tokens_per_minute=settings.eval_judge_tpm,
        requests_per_day=settings.eval_judge_rpd,
    )
    return build_hosted_llm(settings, provider, model, "fast", limiter)


def _finite(value: object) -> float | None:
    if isinstance(value, int | float) and math.isfinite(value):
        return float(value)
    return None
