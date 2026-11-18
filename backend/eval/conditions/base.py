"""What every condition returns for one question."""

from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel, Field

from app.services.retrieval import RetrievedChunk


class BaselineAnswer(BaseModel):
    """The structured output of a baseline generation call (C1, C2)."""

    answer: str = Field(description="The answer, or a short statement that it cannot be given")
    abstained: bool = Field(description="True only if the question was not answered")


@dataclass(frozen=True)
class ConditionOutput:
    """One condition's answer to one question, with the passages it was given (if any)."""

    answer: str
    abstained: bool
    contexts: list[RetrievedChunk] = field(default_factory=list)
    retrieval_ms: float | None = None


class Condition(Protocol):
    """A system configuration that answers benchmark questions."""

    @property
    def name(self) -> str: ...

    async def run(self, question: str) -> ConditionOutput: ...
