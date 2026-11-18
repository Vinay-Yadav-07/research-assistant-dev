"""Deterministic lexical NLI."""

from collections.abc import Sequence

from app.providers.fakes._text import NEGATIONS, has_negation, tokenize
from app.providers.nli import NLIPair, NLIProvider, NLIScores

_CONTRADICTION_MIN_COVERAGE = 0.5


class FakeNLI(NLIProvider):
    """Entailment = share of the claim's content words found in the evidence.

    `entailment = c`, `neutral = 1 - c`, `contradiction = 0`, where `c` is that share. If exactly
    one side is negated and `c >= 0.5`, entailment and contradiction swap. This lets tests build
    supported, borderline, unsupported, and contradicted claims from plain sentences.
    """

    @property
    def model_name(self) -> str:
        return "fake-overlap-nli-v1"

    async def classify(self, pairs: Sequence[NLIPair]) -> list[NLIScores]:
        return [_classify(pair) for pair in pairs]


def _classify(pair: NLIPair) -> NLIScores:
    claim_terms = {token for token in tokenize(pair.hypothesis) if token not in NEGATIONS}
    if not claim_terms:
        return NLIScores(entailment=0.0, neutral=1.0, contradiction=0.0)
    evidence_terms = set(tokenize(pair.premise))
    coverage = len(claim_terms & evidence_terms) / len(claim_terms)

    negation_mismatch = has_negation(pair.premise) != has_negation(pair.hypothesis)
    if negation_mismatch and coverage >= _CONTRADICTION_MIN_COVERAGE:
        return NLIScores(entailment=0.0, neutral=1.0 - coverage, contradiction=coverage)
    return NLIScores(entailment=coverage, neutral=1.0 - coverage, contradiction=0.0)
