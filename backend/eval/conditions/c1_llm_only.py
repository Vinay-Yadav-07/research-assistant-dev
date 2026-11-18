"""C1 LLM-only (SRS §17.2): the question goes to the LLM with no retrieval."""

from app.providers.llm import ChatMessage, LLMProvider
from app.services.guardrails import data_block
from eval.conditions.base import BaselineAnswer, ConditionOutput
from eval.prompts import load_prompt

PROMPT_VERSION = "v1"


class LLMOnly:
    """Answers from the model's own knowledge."""

    name = "C1"

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def run(self, question: str) -> ConditionOutput:
        """One structured LLM call with the question only."""
        messages = [
            ChatMessage(role="system", content=load_prompt("c1_llm_only", PROMPT_VERSION)),
            ChatMessage(role="user", content=data_block("question", question)),
        ]
        result = await self._llm.generate_structured(messages, BaselineAnswer, temperature=0)
        return ConditionOutput(answer=result.output.answer, abstained=result.output.abstained)
