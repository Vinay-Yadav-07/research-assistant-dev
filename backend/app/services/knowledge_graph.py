"""S10 Knowledge Graph Service: per-paper extraction with evidence validation (SRS §9.1, D-081).

A paper's chunks are filtered (short passages, reference lists, back matter) and read in
batches; each batch is one graph-tier LLM call that labels passages `E1`, `E2`, ... and returns
entities and relationships. A relationship is kept only if its cited passage states it: the
label is in the batch, the quote is a verbatim span of that passage (at most two sentences),
both entities are named in the quote (a finding is entailed by it instead), the entity types fit
the relationship, the paper states it about its own work without hedging (and neither the
quote nor the sentence before it clearly credits cited or background research), and the local NLI
model scores the quote as entailing the relationship's statement. Everything else is rejected
and counted per rule. No further LLM calls are made to validate.
"""

import logging
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.errors import LLMOutputError
from app.prompts import load_prompt
from app.providers.llm import ChatMessage, LLMProvider
from app.providers.nli import NLIPair, NLIProvider
from app.repositories.chunks import ChunkRecord
from app.repositories.knowledge_graph import NewEntityMention, NewRelationMention, PaperExtraction
from app.schemas.knowledge_graph import EntityType, RelationType
from app.services.citations import LABEL_PREFIX, CitationService
from app.services.guardrails import clean_metadata_text, data_block
from app.services.knowledge_graph_jobs import CallBudget

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v2"
# Prompt and validation rules together: changing either makes every paper pending again.
EXTRACTOR_VERSION = f"kg-extraction.{PROMPT_VERSION}+rules.v3"

Stance = Literal["own_work", "other_work", "hedged"]

# Entity types each side of a relationship may have (SRS §9.1).
ALLOWED_TYPES: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "uses": (frozenset({"method"}), frozenset({"method", "tool", "dataset", "concept"})),
    "evaluated_on": (frozenset({"method"}), frozenset({"dataset"})),
    "measured_by": (frozenset({"method", "task", "finding"}), frozenset({"metric"})),
    "addresses": (frozenset({"method"}), frozenset({"task"})),
    "compared_with": (frozenset({"method"}), frozenset({"method"})),
    "reports": (frozenset({"method", "dataset", "tool", "task"}), frozenset({"finding"})),
}
# The statement NLI checks against the quote; a finding endpoint is checked by its own text.
TEMPLATES: dict[str, str] = {
    "uses": "{source} uses {target}.",
    "evaluated_on": "{source} is evaluated on {target}.",
    "measured_by": "{source} is measured by {target}.",
    "addresses": "{source} addresses {target}.",
    "compared_with": "{source} is compared with {target}.",
}
MAX_NAME_CHARS = 120
MAX_FINDING_CHARS = 300
MAX_QUOTE_CHARS = 600
MAX_QUOTE_SENTENCES = 2
# Plans and future work are never facts about the paper's own work (backup to the stance).
_FUTURE_WORK = re.compile(
    r"\b(future work|in (the )?future|we plan|we intend|will be (investigated|explored|studied))\b"
)
# "et al." ends an abbreviation, not a sentence.
_SENTENCE_END = re.compile(r"(?<=[.!?])(?<!\bet al\.)\s+")
# Attribution (rules.v2): patterns over folded (lower-case) text unless noted.
_OWN_WORK = re.compile(
    r"\b(we|our|ours|here(in)?|the proposed|this (study|paper|work|article|research|thesis|"
    r"manuscript|report)|the (present|current) (study|paper|work))\b"
)
# What still marks the paper's own words in a review, where "this study" or "the proposed"
# usually describe a cited study: the first person, or naming the review itself.
_REVIEW_OWN = re.compile(
    r"\b(we|our|ours|here(in)?|(this|the present) (review|survey|perspective))\b"
)
_FIRST_PERSON = re.compile(r"\b(we|our|ours)\b")
_THEIR_AUTHORS = re.compile(r"\b(the|these|its|their) authors\b")
# A paper that calls itself a review: in its title, or in its opening passages.
_REVIEW_TITLE = re.compile(
    r"\b(review|reviews|survey|overview|perspectives?|state of the art|advances in|"
    r"advancements in|challenges and opportunities|progress in|a primer|tutorial)\b"
)
_REVIEW_SELF = re.compile(
    r"\b(this|our|the present) (review|mini-review|survey)\b|\bin this review\b"
)
REVIEW_OPENING_CHUNKS = 3
# One entity named as the other ("these singularities, which we call 'switch points'"): the
# quote states identity, not a relationship between two things.
_NAMING = (
    r",? (?:(?:which|that) )?(?:(?:we|is|are) )?(?:call|called|term|termed|name|named|dubbed|"
    r"known as|referred to as) \"?"
)
_PREPOSITION = re.compile(r" (of|in|on|for|with|from|at|by|around|between) ")
# Words that may follow a complete noun phrase; any other word after a concept means the
# concept was cut out of a longer phrase ("Between-the-Eyes area").
_PHRASE_END = re.compile(
    r"("
    r"the|a|an|and|or|but|nor|of|in|on|at|by|for|with|to|from|into|onto|over|under|"
    r"between|among|through|during|before|after|as|than|that|which|who|whose|where|when|"
    r"while|is|are|was|were|be|been|has|have|had|do|does|did|can|could|may|might|will|"
    r"would|should|must|it|its|this|these|those|their|our|we|they|via|per|versus|vs|"
    r"against|within|without|across|around|about|both|each|such|also|not|only|then|thus|"
    r"so|if|because|since|until"
    r")$"
)
_BACKGROUND = re.compile(
    r"\b(has|have) been (widely |extensively |previously )?(developed|proposed|shown|reported|"
    r"demonstrated|studied|investigated|suggested|introduced)\b"
    r"|\b(previous|prior|earlier|existing|past) (studies|study|work|works|research|literature|"
    r"reports)\b|\bit is (well )?(known|established)\b|\b(studies|researchers|scholars) have\b"
)
# Background phrasing that may still frame the paper's own work: a concessive opening ("Although
# methods have been proposed, it was possible ..."), a pointer to its own figures and tables, or
# its own result compared with earlier work ("consistent with previous reports").
_FRAMED = re.compile(
    r"^(although|though|even though|while|whereas|despite)\b|\b(fig|figure|table)s?\b"
    r"|\b(consistent with|in line with|in agreement with|agrees? with|similar to|compared (to|with)"
    r"|unlike|contrary to|confirms?|than) (the |those of |that of )?(previous|prior|earlier|"
    r"existing|past)\b"
)
_REPORTS = (
    r"(took|found|showed|reported|proposed|developed|demonstrated|studied|examined|"
    r"investigated|analy[sz]ed|concluded|observed|argued|suggested|used|introduced|presented)"
)
_NAMED_REPORT = re.compile(rf"\bet al\.?,?\s*(\(\d{{4}}[a-z]?\)|\[[\d,\s–-]+\])?\s*{_REPORTS}\b")
_OTHER_REPORTER = re.compile(
    rf"\bet al\b|\bthe (report|survey)\b|\b(previous|prior|earlier|other) "
    rf"(studies|study|work|research)\b|\b(researchers|scholars|he|she|they) {_REPORTS}\b"
)
# A sentence opening with a surname and a reporting verb ("Wang took ... and found"); case
# matters. Plural or common opening words ("Results", "Analysis", "Research") are not names.
_NAMED_SUBJECT = re.compile(
    rf"^(?!(The|This|These|Those|That|It|Its|In|On|For|To|As|At|By|With|From|However|Our|We|"
    rf"Research|Evidence|Data|Theory|Work|Table|Figure|Fig|Section|Experiment|Training|Testing)\b)"
    rf"[A-Z][a-z]+(?<!s)(?<!tion)(?<!sion)(?<!ment)(?<!ity)(?<!ance)(?<!ence)(?<!ure)(?<!ogy)"
    rf"( (and|&) [A-Z][a-z]+| et al\.?)?( \(\d{{4}}\))? {_REPORTS}\b"
)
_CONTINUES = re.compile(
    r"(it (is|was) also|also|they|their|he|his|she|her|the authors|these authors|"
    r"the same (study|authors))\b"
)
_BACK_MATTER = re.compile(
    r"^\s*(acknowledg|funding|conflicts? of interest|competing interests?|author contributions?)",
    re.IGNORECASE,
)
# One entry of a reference list: a short line that is numbered, or that carries a DOI or
# "et al." together with a year. Body paragraphs are longer and rarely numbered.
_ENTRY_NUMBER = re.compile(r"^\s*(\[\d{1,3}\]|\d{1,3}[.)])\s")
_ENTRY_MARKER = re.compile(r"\bdoi\b|\bet al\.", re.IGNORECASE)
_YEAR = re.compile(r"\b(19|20)\d{2}[a-z]?\b")
MAX_ENTRY_CHARS = 400
_PUNCTUATION = str.maketrans(
    {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "‐": "-", "‑": "-", "−": "-"}
)


class EntityDraft(BaseModel):
    """An entity the LLM found; `name` as written in its passage (a finding: its statement)."""

    id: str
    type: EntityType
    name: str
    passage: str


class RelationDraft(BaseModel):
    """A relationship the LLM found, with the verbatim quote that states it."""

    source: str
    target: str
    type: RelationType
    passage: str
    quote: str
    stance: Stance


class KGBatchExtraction(BaseModel):
    """The LLM's output for one batch of passages."""

    entities: list[EntityDraft] = Field(default_factory=list)
    relations: list[RelationDraft] = Field(default_factory=list)


@dataclass(frozen=True)
class KGExtractionOptions:
    """Chunk selection, batching, and validation thresholds (SRS §9.1, D-083)."""

    min_chunk_words: int
    max_chunks_per_paper: int
    chunks_per_call: int
    max_output_tokens: int
    entailment_score: float
    contradiction_score: float

    @classmethod
    def from_settings(cls, settings: Settings) -> "KGExtractionOptions":
        """Read the options from the application settings."""
        return cls(
            min_chunk_words=settings.kg_min_chunk_words,
            max_chunks_per_paper=settings.kg_max_chunks_per_paper,
            chunks_per_call=settings.kg_chunks_per_call,
            max_output_tokens=settings.kg_max_output_tokens,
            entailment_score=settings.kg_relation_entailment_score,
            contradiction_score=settings.kg_relation_contradiction_score,
        )


def is_reference_list(text: str) -> bool:
    """True when at least half of the passage's lines look like reference entries.

    Judged by content, so body text the parser mislabels "References" is kept.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    return sum(1 for line in lines if _is_entry(line)) * 2 >= len(lines)


def _is_entry(line: str) -> bool:
    if len(line) > MAX_ENTRY_CHARS:
        return False
    return bool(_ENTRY_NUMBER.match(line)) or bool(
        _ENTRY_MARKER.search(line) and _YEAR.search(line)
    )


def select_chunks(chunks: Sequence[ChunkRecord], options: KGExtractionOptions) -> list[ChunkRecord]:
    """The paper's passages worth reading, in order: no short passages, reference lists, or
    back matter, and at most `max_chunks_per_paper`."""
    kept = [
        chunk
        for chunk in chunks
        if len(chunk.text.split()) >= options.min_chunk_words
        and not is_reference_list(chunk.text)
        and not (chunk.section and _BACK_MATTER.match(chunk.section))
    ]
    return kept[: options.max_chunks_per_paper]


def batches(chunks: Sequence[ChunkRecord], size: int) -> list[list[ChunkRecord]]:
    """Consecutive groups of at most `size` passages."""
    return [list(chunks[start : start + size]) for start in range(0, len(chunks), size)]


def _fold(text: str) -> list[tuple[str, int]]:
    """`text` normalized for matching, one (character, source index) pair per output character:
    NFKC, casefolded, typographic quotes and dashes made plain, whitespace runs as one space."""
    out: list[tuple[str, int]] = []
    for index, char in enumerate(text):
        folded = unicodedata.normalize("NFKC", char).translate(_PUNCTUATION).casefold()
        for piece in folded:
            if piece.isspace():
                if out and out[-1][0] != " ":
                    out.append((" ", index))
            else:
                out.append((piece, index))
    return out


def fold(text: str) -> str:
    """`text` normalized for comparison (see `_fold`), without surrounding spaces."""
    return "".join(char for char, _ in _fold(text)).strip()


def verbatim_span(quote: str, text: str) -> str | None:
    """The span of `text` that `quote` reproduces (ignoring case, spacing, quote and dash
    forms), exactly as it appears in `text`; None if `text` has no such span."""
    needle = fold(quote)
    if not needle:
        return None
    folded = _fold(text)
    haystack = "".join(char for char, _ in folded)
    start = haystack.find(needle)
    if start < 0:
        return None
    first, last = folded[start][1], folded[start + len(needle) - 1][1]
    return text[first : last + 1]


@dataclass(frozen=True)
class AttributionContext:
    """The sentence just before a quote, for judging who the quote is about (never evidence).

    `source` says where it came from: the quote's own passage, the previous passage of the
    paper, or nowhere ("none", when the quote opens the paper).
    """

    text: str
    source: Literal["same_passage", "previous_passage", "none"]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]


def attribution_context(
    quote: str, chunk: ChunkRecord, previous: ChunkRecord | None
) -> AttributionContext:
    """The sentence before `quote` (a verbatim span of `chunk`).

    When the quote opens its passage, the sentence before it is taken from the previous
    passage: where passages overlap the quote is found there too, otherwise that passage's last
    sentence is used.
    """
    before = _text_before(quote, chunk.text)
    if before:
        return AttributionContext(before[-1], "same_passage")
    if previous is not None:
        earlier = _text_before(quote, previous.text)
        if earlier:
            return AttributionContext(earlier[-1], "previous_passage")
        if verbatim_span(quote, previous.text) is None and _sentences(previous.text):
            return AttributionContext(_sentences(previous.text)[-1], "previous_passage")
    return AttributionContext("", "none")


def is_review(chunks: Sequence[ChunkRecord]) -> bool:
    """True when the paper calls itself a review: its title ("..., Perspectives", "A survey of
    ...") or its opening passages ("In this review", "this survey")."""
    title = fold(chunks[0].document_title or "") if chunks else ""
    opening = " ".join(fold(c.text) for c in chunks[:REVIEW_OPENING_CHUNKS])
    return bool(_REVIEW_TITLE.search(title) or _REVIEW_SELF.search(opening))


def attribution_problem(
    quote: str, context: AttributionContext, *, review: bool = False
) -> str | None:
    """`cited_study`, `background`, or `review_literature` when the quote, read with the sentence
    before it, clearly reports other research; None otherwise.

    In a research paper, a quote that marks the paper's own work ("we", "our", "this study",
    "here", "the proposed") is kept, unless it credits "the authors" right after a sentence
    reporting a cited study ("Chen et al. created ... In this study, the authors developed").
    In a review, "this study" and "the proposed" usually describe a cited study, so only the
    first person or naming the review ("this review") keeps a quote (`review_literature`).
    Otherwise rejected: background phrasing in the quote ("have been developed", "previous
    studies"); a named study's reporting verb in the quote ("Smith et al. found"); or a context
    sentence in which another study reports something ("Wang ... found that", "the report found
    that"), when the quote completes that clause or continues it ("It is also concluded ...").
    """
    text = fold(quote)
    if review:
        return None if _REVIEW_OWN.search(text) else "review_literature"
    if _OWN_WORK.search(text):
        if (
            _THEIR_AUTHORS.search(text)
            and not _FIRST_PERSON.search(text)
            and _reports_other(context)
        ):
            return "cited_study"
        return None
    if _BACKGROUND.search(text) and not _FRAMED.search(text):
        return "background"
    if _NAMED_REPORT.search(text):
        return "cited_study"
    if not _reports_other(context):
        return None
    before = fold(context.text)
    if before.endswith((" that", ":")) or _CONTINUES.match(text):
        return "cited_study"
    return None


def _reports_other(context: AttributionContext) -> bool:
    """The context sentence reports another study ("Wang ... found", "Chen et al. created") and
    does not speak of the paper's own work."""
    before = fold(context.text)
    if not before or _OWN_WORK.search(before):
        return False
    return bool(_OTHER_REPORTER.search(before) or _NAMED_SUBJECT.match(context.text.strip()))


def names_as_identity(first: str, second: str, quote: str) -> bool:
    """True if the quote names one entity as the other ("singularities ..., which we call
    'switch points'"), in either order."""
    text = fold(quote)
    for named, name in ((first, second), (second, first)):
        head = _PREPOSITION.split(f" {fold(named)} ", maxsplit=1)[0].split()
        if not head or not fold(name):
            continue
        stem = head[-1][:-1] if len(head[-1]) > 3 and head[-1].endswith("s") else head[-1]
        if re.search(rf"\b{re.escape(stem)}\w*{_NAMING}{re.escape(fold(name))}", text):
            return True
    return False


def inside_phrase(name: str, quote: str) -> bool:
    """True if every mention of `name` in the quote runs on into a longer noun phrase (the
    next word is neither punctuation nor a function word, verb form, or adverb)."""
    text = fold(quote)
    ends = [m.end() for m in re.finditer(rf"(?<!\w){re.escape(fold(name))}(?:e?s)?(?!\w)", text)]
    for end in ends:
        word = re.match(r" ([a-z][a-z-]*)\b", text[end:])
        if word is None or _PHRASE_END.match(word[1]) or word[1].endswith(("ed", "ing", "ly")):
            return False
    return bool(ends)


def _text_before(quote: str, text: str) -> list[str]:
    """Whole sentences of `text` before the quote's span (empty if it is not in `text`)."""
    span = verbatim_span(quote, text)
    if span is None:
        return []
    return _sentences(text[: text.find(span)])


def names_in(name: str, text: str) -> bool:
    """True if `name` occurs in `text` as whole words (a plural "s"/"es" may follow)."""
    needle = fold(name)
    if not needle:
        return False
    pattern = rf"(?<!\w){re.escape(needle)}(?:e?s)?(?!\w)"
    return re.search(pattern, fold(text)) is not None


def normalize_key(name: str) -> str:
    """The merge key of an entity name: case, Unicode form, punctuation (inner hyphens become
    spaces), whitespace, and a trailing plural "s" do not matter."""
    words = re.sub(r"[^\w\s]|_", " ", fold(name)).split()
    if words:
        last = words[-1]
        if len(last) > 3 and last.endswith("s") and not last.endswith(("ss", "us", "is")):
            words[-1] = last[:-1]
    return " ".join(words)


@dataclass
class _Candidate:
    relation: RelationDraft
    chunk: ChunkRecord
    quote: str
    source: EntityDraft
    target: EntityDraft
    hypothesis: str


@dataclass
class BatchResult:
    """What one batch kept, and its rejections per rule."""

    entities: list[NewEntityMention] = field(default_factory=list)
    relations: list[NewRelationMention] = field(default_factory=list)
    rejected: Counter[str] = field(default_factory=Counter)


class KnowledgeGraphExtractor:
    """S10's `PaperExtractor`. Give it the graph-tier LLM and the local NLI model."""

    version = EXTRACTOR_VERSION

    def __init__(
        self,
        llm: LLMProvider,
        nli: NLIProvider,
        citations: CitationService,
        options: KGExtractionOptions,
    ) -> None:
        self._llm = llm
        self._nli = nli
        self._citations = citations
        self._options = options

    async def extract(
        self, document_id: UUID, chunks: Sequence[ChunkRecord], budget: CallBudget
    ) -> PaperExtraction:
        """Read one paper. Raises `CallBudgetExceededError` before any call if the budget cannot
        cover all its batches, and lets provider errors (quota, outages) through."""
        selected = select_chunks(chunks, self._options)
        groups = batches(selected, self._options.chunks_per_call)
        budget.ensure(len(groups))
        entities: list[NewEntityMention] = []
        relations: list[NewRelationMention] = []
        rejected: Counter[str] = Counter()
        invalid = 0
        # Each passage's predecessor in the paper, filtered or not, for attribution context.
        previous = {
            after.chunk_id: before for before, after in zip(chunks, chunks[1:], strict=False)
        }
        review = is_review(chunks)
        for number, group in enumerate(groups):
            output = await self._call(group, budget)
            if output is None:
                invalid += 1
                rejected["invalid_output"] += 1
                continue
            result = await self.validate(
                document_id, group, output, prefix=f"b{number}", previous=previous, review=review
            )
            entities += result.entities
            relations += result.relations
            rejected.update(result.rejected)
        status = "failed" if groups and invalid == len(groups) else "completed"
        return PaperExtraction(
            chunks_considered=len(selected),
            entities=entities,
            relations=relations,
            rejected_counts=dict(rejected),
            status=status,
        )

    async def _call(
        self, group: Sequence[ChunkRecord], budget: CallBudget
    ) -> KGBatchExtraction | None:
        """One batch's output; an invalid reply is asked again once, then given up (None)."""
        messages = [
            ChatMessage(
                role="system",
                content=load_prompt("services", "kg_extraction", PROMPT_VERSION),
            ),
            ChatMessage(role="user", content=batch_request(group)),
        ]
        for attempt in range(2):
            budget.take()
            try:
                result = await self._llm.generate_structured(
                    messages,
                    KGBatchExtraction,
                    temperature=0,
                    max_output_tokens=self._options.max_output_tokens,
                )
            except LLMOutputError:
                logger.warning("Knowledge graph batch output invalid (attempt %d)", attempt + 1)
                continue
            return result.output
        return None

    async def validate(
        self,
        document_id: UUID,
        group: Sequence[ChunkRecord],
        output: KGBatchExtraction,
        *,
        prefix: str,
        previous: Mapping[UUID, ChunkRecord] | None = None,
        review: bool = False,
    ) -> BatchResult:
        """Keep what the batch's passages support; count each rejection by rule.

        `previous` maps a passage to the one before it in the paper, so a quote opening its
        passage is judged with the sentence that precedes it; `review` marks a paper that calls
        itself a review (`is_review`), whose quotes need the first person to count as its own.
        """
        result = BatchResult()
        passages = {f"{LABEL_PREFIX}{n}": chunk for n, chunk in enumerate(group, start=1)}
        drafts: dict[str, EntityDraft] = {}
        for entity in output.entities:
            reason = _entity_problem(entity)
            if reason:
                result.rejected[reason] += 1
            elif entity.id.strip() and entity.id.strip() not in drafts:
                drafts[entity.id.strip()] = entity
        candidates: list[_Candidate] = []
        for relation in output.relations:
            candidate = self._screen(
                relation, drafts, passages, previous or {}, review, result.rejected
            )
            if candidate is not None:
                candidates.append(candidate)
        scores = (
            await self._nli.classify(
                [NLIPair(premise=c.quote, hypothesis=c.hypothesis) for c in candidates]
            )
            if candidates
            else []
        )
        mentions = _MentionSet(document_id, prefix, self._citations)
        used: set[str] = set()
        for candidate, score in zip(candidates, scores, strict=True):
            if score.entailment < self._options.entailment_score:
                result.rejected["not_entailed"] += 1
                continue
            if score.contradiction >= self._options.contradiction_score:
                result.rejected["contradicted"] += 1
                continue
            source = mentions.add(candidate.source, candidate.chunk, candidate.quote)
            target = mentions.add(candidate.target, candidate.chunk, candidate.quote)
            if source == target:
                # Two drafts with the same name in one passage are one mention.
                result.rejected["self_relation"] += 1
                continue
            used.update((candidate.source.id.strip(), candidate.target.id.strip()))
            result.relations.append(
                NewRelationMention(
                    chunk_id=candidate.chunk.chunk_id,
                    source_key=source,
                    target_key=target,
                    relation_type=candidate.relation.type,
                    quote=candidate.quote,
                    entailment_score=score.entailment,
                )
            )
        for entity_id, entity in drafts.items():
            if entity_id in used or entity.type == "finding":
                continue
            chunk = passages.get(entity.passage.strip())
            if chunk is None or not names_in(entity.name, chunk.text):
                result.rejected["entity_not_in_passage"] += 1
                continue
            mentions.add(entity, chunk, None)
        result.entities = mentions.mentions
        return result

    def _screen(
        self,
        relation: RelationDraft,
        drafts: dict[str, EntityDraft],
        passages: dict[str, ChunkRecord],
        previous: Mapping[UUID, ChunkRecord],
        review: bool,
        rejected: Counter[str],
    ) -> _Candidate | None:
        """The relationship ready for the NLI check, or None after counting why it failed."""
        chunk = passages.get(relation.passage.strip())
        if chunk is None:
            rejected["label_invalid"] += 1
            return None
        quote = verbatim_span(relation.quote, chunk.text)
        if quote is None:
            rejected["quote_not_verbatim"] += 1
            return None
        sentences = [s for s in _SENTENCE_END.split(quote.strip()) if s.strip()]
        if len(quote) > MAX_QUOTE_CHARS or len(sentences) > MAX_QUOTE_SENTENCES:
            rejected["quote_too_long"] += 1
            return None
        source, target = drafts.get(relation.source.strip()), drafts.get(relation.target.strip())
        if source is None or target is None or source is target:
            rejected["entity_unknown"] += 1
            return None
        sources, targets = ALLOWED_TYPES[relation.type]
        if source.type not in sources or target.type not in targets:
            rejected["type_not_allowed"] += 1
            return None
        named = [e for e in (source, target) if e.type != "finding"]
        if not all(names_in(e.name, quote) for e in named):
            rejected["entity_not_in_quote"] += 1
            return None
        if relation.stance != "own_work" or _FUTURE_WORK.search(fold(quote)):
            rejected["not_own_work"] += 1
            return None
        context = attribution_context(quote, chunk, previous.get(chunk.chunk_id))
        if attribution_problem(quote, context, review=review):
            rejected["attributed_elsewhere"] += 1
            return None
        if all(e.type != "finding" for e in (source, target)) and names_as_identity(
            source.name, target.name, quote
        ):
            rejected["identity_not_relation"] += 1
            return None
        if (
            relation.type == "uses"
            and target.type == "concept"
            and inside_phrase(target.name, quote)
        ):
            rejected["entity_inside_phrase"] += 1
            return None
        finding = next((e for e in (source, target) if e.type == "finding"), None)
        hypothesis = (
            _text(finding)
            if finding is not None
            else TEMPLATES[relation.type].format(
                source=source.name.strip(), target=target.name.strip()
            )
        )
        if relation.type == "compared_with" and normalize_key(source.name) > normalize_key(
            target.name
        ):
            source, target = target, source
        return _Candidate(relation, chunk, quote, source, target, hypothesis)


class _MentionSet:
    """A batch's entity mentions, one per (passage, type, name)."""

    def __init__(self, document_id: UUID, prefix: str, citations: CitationService) -> None:
        self._document_id = document_id
        self._prefix = prefix
        self._citations = citations
        self._keys: dict[tuple[UUID, str, str], str] = {}
        self.mentions: list[NewEntityMention] = []

    def add(self, entity: EntityDraft, chunk: ChunkRecord, quote: str | None) -> str:
        """The mention's key, creating it with `quote` (or the passage's best sentence)."""
        surface = _text(entity)
        key = normalize_key(surface)
        if entity.type == "finding":
            # Findings belong to their paper and never merge across papers.
            key = f"{self._document_id}:{key}"
        identity = (chunk.chunk_id, entity.type, key)
        if identity not in self._keys:
            self._keys[identity] = f"{self._prefix}:{len(self._keys)}"
            self.mentions.append(
                NewEntityMention(
                    key=self._keys[identity],
                    chunk_id=chunk.chunk_id,
                    entity_type=entity.type,
                    surface_text=surface,
                    normalized_key=key,
                    quote=quote or self._citations.quote(surface, chunk.text),
                )
            )
        return self._keys[identity]


def _text(entity: EntityDraft) -> str:
    """An entity's name (a finding: its statement) as stored: plain, cleaned text."""
    return clean_metadata_text(entity.name) or ""


def _entity_problem(entity: EntityDraft) -> str | None:
    """Why an entity draft is unusable, or None."""
    text = _text(entity)
    if not normalize_key(text):
        return "name_empty"
    limit = MAX_FINDING_CHARS if entity.type == "finding" else MAX_NAME_CHARS
    if len(text) > limit:
        return "name_too_long"
    return None


def batch_request(group: Sequence[ChunkRecord]) -> str:
    """The paper title and the batch's passages, each as `[E1] p. 3, Methods` and its text."""
    title = group[0].document_title if group else None
    passages = "\n\n".join(
        f"[{LABEL_PREFIX}{n}] "
        + (
            f"p. {chunk.page_start}"
            if chunk.page_start == chunk.page_end
            else f"pp. {chunk.page_start}-{chunk.page_end}"
        )
        + (f", {chunk.section}" if chunk.section else "")
        + f"\n{chunk.text}"
        for n, chunk in enumerate(group, start=1)
    )
    return "\n\n".join(
        [data_block("paper_title", title or "Untitled"), data_block("passages", passages)]
    )
