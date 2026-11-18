"""C2 Conventional RAG (SRS §17.2): dense top 8 + one "answer only from context" prompt."""

import time
from collections.abc import Awaitable, Callable, Sequence

from app.providers.llm import ChatMessage, LLMProvider
from app.services.guardrails import data_block
from app.services.retrieval import RetrievalResult, RetrievedChunk
from eval.conditions.base import BaselineAnswer, ConditionOutput
from eval.prompts import load_prompt

PROMPT_VERSION = "v1"

# Dense-only retrieval in the workspace of the question's corpus (`retrieve_dense`).
Retrieve = Callable[[str], Awaitable[RetrievalResult]]


class ConventionalRAG:
    """Dense retrieval and a single generation call; no reranking, gate, or verification."""

    name = "C2"

    def __init__(self, llm: LLMProvider, retrieve: Retrieve) -> None:
        self._llm = llm
        self._retrieve = retrieve

    async def run(self, question: str) -> ConditionOutput:
        """Retrieve the passages, then answer from them."""
        started = time.perf_counter()
        retrieved = await self._retrieve(question)
        retrieval_ms = round((time.perf_counter() - started) * 1000, 1)
        user = "\n\n".join(
            [data_block("question", question), data_block("context", passages(retrieved.evidence))]
        )
        messages = [
            ChatMessage(role="system", content=load_prompt("c2_conventional_rag", PROMPT_VERSION)),
            ChatMessage(role="user", content=user),
        ]
        result = await self._llm.generate_structured(messages, BaselineAnswer, temperature=0)
        return ConditionOutput(
            answer=result.output.answer,
            abstained=result.output.abstained,
            contexts=list(retrieved.evidence),
            retrieval_ms=retrieval_ms,
        )


def passages(chunks: Sequence[RetrievedChunk]) -> str:
    """Numbered passages with title and page; an empty context says so."""
    if not chunks:
        return "(no passages)"
    return "\n\n".join(
        f"[{number}] {chunk.document_title or 'Untitled'}, p. {chunk.page_start}\n{chunk.text}"
        for number, chunk in enumerate(chunks, start=1)
    )
