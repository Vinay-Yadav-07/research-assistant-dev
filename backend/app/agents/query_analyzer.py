"""A1 Query Analyzer (SRS §5.2, §7.4): classify the question and plan search-ready sub-questions.

A1 never answers: it returns a `QueryPlan` whose sub-questions only ask. The graph routes
`out_of_scope` plans to the S6 scoped refusal and retrieves evidence per sub-question otherwise.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.prompts import load_prompt
from app.providers.llm import ChatMessage, LLMProvider
from app.services.guardrails import data_block

PROMPT_VERSION = "v1"
MAX_SUB_QUESTIONS = 4  # Fixed by SRS §7.4.

Intent = Literal[
    "simple_qa",
    "multi_hop",
    "comparison",
    "aggregation",
    "contradiction",
    "gap",
    "discovery",
    "out_of_scope",
]


class SubQuestion(BaseModel):
    """One search-ready sub-question; `depends_on` names earlier sub-questions it needs."""

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    search_keywords: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    paper_refs: list[str] = Field(default_factory=list)


class QueryPlan(BaseModel):
    """A1's output: the intent, at most four sub-questions, and papers named in the question."""

    intent: Intent
    sub_questions: list[SubQuestion] = Field(default_factory=list, max_length=MAX_SUB_QUESTIONS)
    paper_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_structure(self) -> "QueryPlan":
        if self.intent == "out_of_scope" and self.sub_questions:
            raise ValueError("an out_of_scope plan has no sub-questions")
        if self.intent not in ("out_of_scope", "simple_qa") and not self.sub_questions:
            raise ValueError(f"a {self.intent} plan needs at least one sub-question")
        seen: set[str] = set()
        for sub in self.sub_questions:
            if sub.id in seen:
                raise ValueError(f"duplicate sub-question id {sub.id!r}")
            unknown = [dep for dep in sub.depends_on if dep not in seen]
            if unknown:
                raise ValueError(f"{sub.id!r} depends on {unknown}, which are not earlier ids")
            seen.add(sub.id)
        return self


class QueryAnalyzer:
    """A1. Give it the fast-tier LLM (SRS §7.4: a fast, low-cost model)."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def analyze(self, question: str) -> QueryPlan:
        """Plan `question`, which has already passed the S6 input check.

        Raises `LLMOutputError` if the model's plan does not validate.
        """
        messages = [
            ChatMessage(
                role="system", content=load_prompt("agents", "query_analyzer", PROMPT_VERSION)
            ),
            ChatMessage(role="user", content=data_block("question", question)),
        ]
        result = await self._llm.generate_structured(messages, QueryPlan, temperature=0)
        return _normalized(result.output, question)


def _normalized(plan: QueryPlan, question: str) -> QueryPlan:
    """A simple question is not decomposed: one sub-question, the question itself."""
    if plan.intent != "simple_qa":
        return plan
    first = plan.sub_questions[0] if plan.sub_questions else None
    only = SubQuestion(
        id="q1",
        text=question,
        search_keywords=first.search_keywords if first else [],
        paper_refs=first.paper_refs if first else list(plan.paper_refs),
    )
    return plan.model_copy(update={"sub_questions": [only]})
