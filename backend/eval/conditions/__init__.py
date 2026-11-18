"""Experimental conditions (SRS §17.2). Phase 2 implements the baselines C1 and C2."""

from eval.conditions.base import BaselineAnswer, Condition, ConditionOutput
from eval.conditions.c1_llm_only import LLMOnly
from eval.conditions.c2_conventional_rag import ConventionalRAG, Retrieve

__all__ = [
    "BaselineAnswer",
    "Condition",
    "ConditionOutput",
    "ConventionalRAG",
    "LLMOnly",
    "Retrieve",
]
