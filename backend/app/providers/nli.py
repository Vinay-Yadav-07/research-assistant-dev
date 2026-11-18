"""Natural-language-inference provider interface (first-pass claim checking)."""

from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, Field


class NLIPair(BaseModel):
    """A premise (evidence text) and a hypothesis (claim) to compare."""

    premise: str
    hypothesis: str


class NLIScores(BaseModel):
    """Class probabilities for one pair; they sum to 1."""

    entailment: float = Field(ge=0.0, le=1.0)
    neutral: float = Field(ge=0.0, le=1.0)
    contradiction: float = Field(ge=0.0, le=1.0)


class NLIProvider(Protocol):
    """Classifies whether evidence entails, contradicts, or is neutral towards a claim."""

    @property
    def model_name(self) -> str: ...

    async def classify(self, pairs: Sequence[NLIPair]) -> list[NLIScores]:
        """Score every pair; output order matches input order."""
        ...
