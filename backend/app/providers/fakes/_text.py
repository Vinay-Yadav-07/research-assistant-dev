"""Deterministic text helpers shared by the fake providers."""

import hashlib
import re

_WORD = re.compile(r"[a-z0-9]+")
_CONTRACTION = re.compile(r"n't\b")
_SPECIAL_CONTRACTIONS = {"can't": "cannot", "won't": "will not"}


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


STOPWORDS = _words(
    "a an and are as at be been by can could did do does for from had has have how in into is "
    "it its of on or so such than that the their them then there these they this those to was "
    "were what when where which while who why will with would"
)
NEGATIONS = _words("not no never without cannot fail none neither nor")


def normalize(word: str) -> str:
    """Strip a simple plural `s` so `scaffolds` and `scaffold` match."""
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    """Lower-case content words in order: stopwords and single letters removed, plurals folded."""
    lowered = text.lower().replace("\u2019", "'")
    for contraction, expansion in _SPECIAL_CONTRACTIONS.items():
        lowered = lowered.replace(contraction, expansion)
    lowered = _CONTRACTION.sub(" not", lowered)
    return [
        normalize(word)
        for word in _WORD.findall(lowered)
        if word not in STOPWORDS and not (len(word) == 1 and word.isalpha())
    ]


def bigrams(tokens: list[str]) -> list[str]:
    """Adjacent token pairs joined by a space."""
    return [f"{first} {second}" for first, second in zip(tokens, tokens[1:], strict=False)]


def has_negation(text: str) -> bool:
    """True if the text contains a negation word (`not`, `never`, `doesn't`, ...)."""
    return not NEGATIONS.isdisjoint(tokenize(text))


def stable_hash(value: str) -> int:
    """A 64-bit hash that is identical in every process (unlike the salted built-in `hash`)."""
    return int.from_bytes(hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest(), "big")


def coverage_score(query: str, passage: str) -> float:
    """Lexical relevance in [0, 1]: 0.8 x query-term coverage + 0.2 x query-bigram coverage.

    Term frequency is ignored on purpose, so repeating one query word does not raise the score.
    """
    query_tokens = tokenize(query)
    if not query_tokens:
        return 0.0
    passage_tokens = tokenize(passage)
    passage_terms = set(passage_tokens)
    query_terms = set(query_tokens)
    term_coverage = len(query_terms & passage_terms) / len(query_terms)

    query_bigrams = set(bigrams(query_tokens))
    if not query_bigrams:
        return term_coverage
    bigram_coverage = len(query_bigrams & set(bigrams(passage_tokens))) / len(query_bigrams)
    return 0.8 * term_coverage + 0.2 * bigram_coverage
