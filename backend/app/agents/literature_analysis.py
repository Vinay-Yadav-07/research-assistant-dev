"""A4 Literature Analysis Agent (SRS §5.2, §9, FR-18, FR-19) over selected papers.

Comparison: for each paper and each FR-19 attribute, S2 retrieves that paper's best chunks; one
LLM call per paper fills the paper's cells from those passages. A cell keeps its text only if it
cites at least one passage of its paper; otherwise it reads "Not reported".

Synthesis: S2 retrieves each paper's best chunks for the topic; one LLM call groups claims by
theme. A claim is kept only if it cites a passage of every paper it names (FR-18).

Contradictions (FR-20, SRS §9): from the same per-paper topic evidence, one LLM call extracts
each paper's cited findings; the NLI model screens every pair of findings from different papers;
one LLM call checks the remaining pairs for differing conditions and labels each.

Gaps (FR-21, corpus scope): S2 retrieves each paper's limitations and future-work chunks; one LLM
call groups them into potential gaps across the papers. A gap is kept only if it cites a passage
of every paper it names.

Nothing is stored here; the caller persists contradictions and gaps.
"""

from collections.abc import Sequence
from itertools import combinations
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.errors import InvalidInputError, NotFoundError
from app.prompts import load_prompt
from app.providers.llm import ChatMessage, LLMProvider
from app.providers.nli import NLIPair, NLIProvider
from app.services.citations import LABEL_PREFIX, CitationService, EvidenceSet
from app.services.conversations import CitationDraft
from app.services.guardrails import data_block
from app.services.research import ContradictionRecord, GapRecord
from app.services.retrieval import RetrievalService, RetrievedChunk

COMPARISON_PROMPT_VERSION = "v1"
THEME_SYNTHESIS_PROMPT_VERSION = "v1"
FINDINGS_EXTRACTION_PROMPT_VERSION = "v1"
CONTRADICTION_CHECK_PROMPT_VERSION = "v1"
GAP_ANALYSIS_PROMPT_VERSION = "v1"
PAIR_LABEL_PREFIX = "C"
PAPER_LABEL_PREFIX = "P"
NOT_REPORTED = "Not reported"

Attribute = Literal["objective", "methodology", "materials", "setup", "findings", "limitations"]

# Search query per attribute, run against one paper at a time.
ATTRIBUTE_QUERIES: dict[Attribute, str] = {
    "objective": "aim, objective, and research question of the study",
    "methodology": "methods and experimental design used in the study",
    "materials": "materials, scaffolds, cells, and reagents used",
    "setup": "experimental setup, conditions, parameters, and samples",
    "findings": "main results and findings of the study",
    "limitations": "limitations of the study and future work",
}


class CellDraft(BaseModel):
    """The LLM's value for one attribute of one paper and the passage labels it cites."""

    attribute: Attribute
    # None when the passages do not report this attribute.
    text: str | None = None
    citations: list[str] = Field(default_factory=list)


class PaperCells(BaseModel):
    """The LLM's output for one paper: one cell per attribute."""

    cells: list[CellDraft]


class ComparisonCell(BaseModel):
    """One cell of the table: cited text, or "Not reported" with no citations."""

    attribute: Attribute
    text: str
    reported: bool
    citations: list[CitationDraft]


class PaperColumn(BaseModel):
    """One compared paper and its cells, in attribute order."""

    document_id: UUID
    document_title: str | None
    cells: list[ComparisonCell]


class ComparisonTable(BaseModel):
    """A4's comparison: one column per paper, in the order requested."""

    attributes: list[Attribute]
    papers: list[PaperColumn]


class ClaimDraft(BaseModel):
    """The LLM's claim, the paper labels it generalizes over, and the passage labels it cites."""

    text: str
    papers: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


class ThemeDraft(BaseModel):
    """The LLM's theme and its claims."""

    title: str
    claims: list[ClaimDraft]


class SynthesisDraft(BaseModel):
    """The LLM's output for a synthesis."""

    themes: list[ThemeDraft]


class SynthesisClaim(BaseModel):
    """One claim, the papers its citations come from, and those citations."""

    text: str
    document_ids: list[UUID]
    citations: list[CitationDraft]


class Theme(BaseModel):
    """One theme and its cited claims."""

    title: str
    claims: list[SynthesisClaim]


class ThemeSynthesis(BaseModel):
    """A4's synthesis: themes with at least one kept claim, in the LLM's order."""

    topic: str
    themes: list[Theme]


class FindingDraft(BaseModel):
    """The LLM's finding, the label of its paper, and the passage labels it cites."""

    text: str
    paper: str
    citations: list[str] = Field(default_factory=list)


class FindingsDraft(BaseModel):
    """The LLM's findings on the topic, over all papers."""

    findings: list[FindingDraft]


class PairCheckDraft(BaseModel):
    """The LLM's verdict on one candidate pair; `none` drops the pair."""

    pair: str
    label: Literal["potential_contradiction", "context_dependent", "none"]
    context_note: str = ""


class ContradictionChecksDraft(BaseModel):
    """The LLM's verdicts on the candidate pairs."""

    checks: list[PairCheckDraft]


class GapsDraft(BaseModel):
    """The LLM's gaps; each is a claim over the papers it names."""

    gaps: list[ClaimDraft]


class GapReport(BaseModel):
    """A4's potential corpus gaps, each citing every paper it names."""

    gaps: list[SynthesisClaim]

    def records(self) -> list[GapRecord]:
        """The gaps as stored, each with its citation snapshots."""
        return [
            GapRecord(
                description=gap.text,
                evidence_refs=[c.model_dump(mode="json") for c in gap.citations],
            )
            for gap in self.gaps
        ]


class Finding(BaseModel):
    """One paper's cited finding."""

    text: str
    document_id: UUID
    citations: list[CitationDraft]


class ContradictionPair(BaseModel):
    """Two findings of different papers the NLI model scored as contradicting, with the LLM's
    label and the conditions that may explain the difference."""

    finding_a: Finding
    finding_b: Finding
    label: Literal["potential_contradiction", "context_dependent"]
    context_note: str
    nli_score: float


class ContradictionReport(BaseModel):
    """A4's contradictions on a topic, highest NLI score first."""

    topic: str
    contradictions: list[ContradictionPair]

    def records(self) -> list[ContradictionRecord]:
        """The contradictions as stored, each with its two findings' citation snapshots."""
        return [
            ContradictionRecord(
                claim_a=pair.finding_a.text,
                claim_b=pair.finding_b.text,
                evidence_refs=[
                    {"side": side, **citation.model_dump(mode="json")}
                    for side, finding in (("a", pair.finding_a), ("b", pair.finding_b))
                    for citation in finding.citations
                ],
                context_note=pair.context_note,
                label=pair.label,
            )
            for pair in self.contradictions
        ]


class LiteratureAnalysisAgent:
    """A4. Give it the strong-tier LLM."""

    def __init__(
        self,
        llm: LLMProvider,
        retrieval: RetrievalService,
        citations: CitationService,
        *,
        compare_top_k: int,
        compare_max_papers: int,
        synthesis_top_k: int,
        nli: NLIProvider,
        contradiction_findings_per_paper: int,
        contradiction_nli_score: float,
        contradiction_max_pairs: int,
    ) -> None:
        self._llm = llm
        self._nli = nli
        self._findings_per_paper = contradiction_findings_per_paper
        self._contradiction_nli_score = contradiction_nli_score
        self._contradiction_max_pairs = contradiction_max_pairs
        self._retrieval = retrieval
        self._citations = citations
        self._compare_top_k = compare_top_k
        self._compare_max_papers = compare_max_papers
        self._synthesis_top_k = synthesis_top_k

    async def compare(
        self, user_id: UUID, workspace_id: UUID, document_ids: Sequence[UUID]
    ) -> ComparisonTable:
        """Compare the given papers of one workspace on every FR-19 attribute.

        Raises `InvalidInputError` for more than `compare_max_papers` papers, `NotFoundError` if
        the workspace or any paper is not the user's ready document in that workspace, and
        `LLMOutputError` if a reply does not validate.
        """
        self._check_paper_count(document_ids)
        evidence = [await self._paper_evidence(user_id, workspace_id, d) for d in document_ids]
        papers = [
            await self._compare_paper(document_id, paper)
            for document_id, paper in zip(document_ids, evidence, strict=True)
        ]
        return ComparisonTable(attributes=list(ATTRIBUTE_QUERIES), papers=papers)

    async def synthesize(
        self, user_id: UUID, workspace_id: UUID, topic: str, document_ids: Sequence[UUID]
    ) -> ThemeSynthesis:
        """Synthesize the given papers on `topic` by theme (FR-18).

        Raises like `compare`: `InvalidInputError` for too many papers, `NotFoundError` for a
        paper or workspace that is not the user's, `LLMOutputError` for an invalid reply.
        """
        self._check_paper_count(document_ids)
        papers, evidence = await self._topic_evidence(user_id, workspace_id, topic, document_ids)
        messages = [
            ChatMessage(
                role="system",
                content=load_prompt("agents", "theme_synthesis", THEME_SYNTHESIS_PROMPT_VERSION),
            ),
            ChatMessage(role="user", content=_synthesis_request(topic, papers, evidence)),
        ]
        reply = await self._llm.generate_structured(messages, SynthesisDraft, temperature=0)
        themes = []
        for draft in reply.output.themes:
            claims = [c for c in (self._claim(d, papers, evidence) for d in draft.claims) if c]
            if claims and draft.title.strip():
                themes.append(Theme(title=draft.title.strip(), claims=claims))
        return ThemeSynthesis(topic=topic, themes=themes)

    async def find_contradictions(
        self, user_id: UUID, workspace_id: UUID, topic: str, document_ids: Sequence[UUID]
    ) -> ContradictionReport:
        """Potential contradictions on `topic` between findings of the given papers (FR-20).

        Raises like `synthesize`.
        """
        self._check_paper_count(document_ids)
        papers, evidence = await self._topic_evidence(user_id, workspace_id, topic, document_ids)
        findings = await self._findings(topic, papers, evidence)
        candidates = await self._screen(findings)
        if not candidates:
            return ContradictionReport(topic=topic, contradictions=[])
        pairs = {f"{PAIR_LABEL_PREFIX}{n}": c for n, c in enumerate(candidates, start=1)}
        messages = [
            ChatMessage(
                role="system",
                content=load_prompt(
                    "agents", "contradiction_check", CONTRADICTION_CHECK_PROMPT_VERSION
                ),
            ),
            ChatMessage(role="user", content=_check_request(topic, pairs, papers, evidence)),
        ]
        reply = await self._llm.generate_structured(
            messages, ContradictionChecksDraft, temperature=0
        )
        checks: dict[str, PairCheckDraft] = {}
        for draft in reply.output.checks:
            checks.setdefault(draft.pair.strip(), draft)
        contradictions = []
        for label, (a, b, score) in pairs.items():
            check = checks.get(label)
            if check is None or check.label == "none":
                continue
            contradictions.append(
                ContradictionPair(
                    finding_a=a,
                    finding_b=b,
                    label=check.label,
                    context_note=check.context_note.strip(),
                    nli_score=score,
                )
            )
        return ContradictionReport(topic=topic, contradictions=contradictions)

    async def find_gaps(
        self, user_id: UUID, workspace_id: UUID, document_ids: Sequence[UUID]
    ) -> GapReport:
        """Potential research gaps across the given papers' limitations and future work (FR-21).

        Raises like `compare`.
        """
        self._check_paper_count(document_ids)
        papers, evidence = await self._topic_evidence(
            user_id, workspace_id, ATTRIBUTE_QUERIES["limitations"], document_ids
        )
        messages = [
            ChatMessage(
                role="system",
                content=load_prompt("agents", "gap_analysis", GAP_ANALYSIS_PROMPT_VERSION),
            ),
            ChatMessage(
                role="user",
                content=_synthesis_request(ATTRIBUTE_QUERIES["limitations"], papers, evidence),
            ),
        ]
        reply = await self._llm.generate_structured(messages, GapsDraft, temperature=0)
        gaps = [g for g in (self._claim(d, papers, evidence) for d in reply.output.gaps) if g]
        return GapReport(gaps=gaps)

    async def _findings(
        self, topic: str, papers: dict[str, UUID], evidence: EvidenceSet
    ) -> list[Finding]:
        """Each paper's first findings that cite only that paper's passages."""
        messages = [
            ChatMessage(
                role="system",
                content=load_prompt(
                    "agents", "findings_extraction", FINDINGS_EXTRACTION_PROMPT_VERSION
                ),
            ),
            ChatMessage(role="user", content=_synthesis_request(topic, papers, evidence)),
        ]
        reply = await self._llm.generate_structured(messages, FindingsDraft, temperature=0)
        findings: list[Finding] = []
        per_paper: dict[UUID, int] = {}
        for draft in reply.output.findings:
            text = draft.text.strip()
            document_id = papers.get(draft.paper.strip())
            labels = evidence.check(draft.citations).valid
            if not text or document_id is None or not labels:
                continue
            if any(evidence.chunk(label).document_id != document_id for label in labels):
                continue
            if per_paper.get(document_id, 0) >= self._findings_per_paper:
                continue
            per_paper[document_id] = per_paper.get(document_id, 0) + 1
            findings.append(
                Finding(
                    text=text,
                    document_id=document_id,
                    citations=self._citations.citations_for(text, labels, evidence),
                )
            )
        return findings

    async def _screen(self, findings: Sequence[Finding]) -> list[tuple[Finding, Finding, float]]:
        """Pairs from different papers whose NLI contradiction score (the higher of both
        directions) reaches the threshold, highest first, at most `contradiction_max_pairs`."""
        pairs = [(a, b) for a, b in combinations(findings, 2) if a.document_id != b.document_id]
        if not pairs:
            return []
        scores = await self._nli.classify(
            [
                NLIPair(premise=premise.text, hypothesis=hypothesis.text)
                for a, b in pairs
                for premise, hypothesis in ((a, b), (b, a))
            ]
        )
        scored = [
            (a, b, max(scores[2 * n].contradiction, scores[2 * n + 1].contradiction))
            for n, (a, b) in enumerate(pairs)
        ]
        kept = [p for p in scored if p[2] >= self._contradiction_nli_score]
        kept.sort(key=lambda p: p[2], reverse=True)
        return kept[: self._contradiction_max_pairs]

    async def _topic_evidence(
        self, user_id: UUID, workspace_id: UUID, topic: str, document_ids: Sequence[UUID]
    ) -> tuple[dict[str, UUID], EvidenceSet]:
        """Paper labels `P1`, `P2`, ... and each paper's best chunks for `topic`."""
        chunks: list[RetrievedChunk] = []
        seen: set[UUID] = set()
        for document_id in document_ids:
            result = await self._retrieval.retrieve(
                user_id,
                workspace_id,
                topic,
                top_k=self._synthesis_top_k,
                document_ids=[document_id],
            )
            # As in `_paper_evidence`: no evidence means the paper is not in the workspace.
            if not result.evidence:
                raise NotFoundError("Document not found.")
            chunks += [c for c in result.evidence if c.chunk_id not in seen]
            seen.update(c.chunk_id for c in result.evidence)
        papers = {f"{PAPER_LABEL_PREFIX}{n}": d for n, d in enumerate(document_ids, start=1)}
        return papers, EvidenceSet(chunks, {})

    def _claim(
        self, draft: ClaimDraft, papers: dict[str, UUID], evidence: EvidenceSet
    ) -> SynthesisClaim | None:
        """The cited claim, or None if it is empty, uncited, or misses a paper it names."""
        text = draft.text.strip()
        labels = evidence.check(draft.citations).valid
        cited = list(dict.fromkeys(evidence.chunk(label).document_id for label in labels))
        named = {papers.get(p.strip()) for p in draft.papers}
        if not text or not cited or not named <= set(cited):
            return None
        return SynthesisClaim(
            text=text,
            document_ids=cited,
            citations=self._citations.citations_for(text, labels, evidence),
        )

    def _check_paper_count(self, document_ids: Sequence[UUID]) -> None:
        if len(document_ids) > self._compare_max_papers:
            raise InvalidInputError(f"Select at most {self._compare_max_papers} papers.")

    async def _paper_evidence(
        self, user_id: UUID, workspace_id: UUID, document_id: UUID
    ) -> EvidenceSet:
        """One paper's chunks per attribute, labelled `E1`, `E2`, ... (shared chunks once)."""
        chunks: list[RetrievedChunk] = []
        labels: dict[UUID, str] = {}
        by_attribute: dict[str, list[str]] = {}
        for attribute, query in ATTRIBUTE_QUERIES.items():
            result = await self._retrieval.retrieve(
                user_id, workspace_id, query, top_k=self._compare_top_k, document_ids=[document_id]
            )
            for chunk in result.evidence:
                if chunk.chunk_id not in labels:
                    chunks.append(chunk)
                    labels[chunk.chunk_id] = f"{LABEL_PREFIX}{len(chunks)}"
                by_attribute.setdefault(attribute, []).append(labels[chunk.chunk_id])
        # Retrieval only returns ready documents linked to the user's workspace, and a ready
        # document always has chunks, so no evidence means the paper is not in the workspace.
        if not chunks:
            raise NotFoundError("Document not found.")
        return EvidenceSet(chunks, by_attribute)

    async def _compare_paper(self, document_id: UUID, evidence: EvidenceSet) -> PaperColumn:
        title = evidence.items[0].chunk.document_title
        messages = [
            ChatMessage(
                role="system",
                content=load_prompt("agents", "comparison", COMPARISON_PROMPT_VERSION),
            ),
            ChatMessage(role="user", content=_request(title, evidence)),
        ]
        result = await self._llm.generate_structured(messages, PaperCells, temperature=0)
        drafts: dict[str, CellDraft] = {}
        for draft in result.output.cells:
            drafts.setdefault(draft.attribute, draft)
        return PaperColumn(
            document_id=document_id,
            document_title=title,
            cells=[self._cell(a, drafts.get(a), evidence) for a in ATTRIBUTE_QUERIES],
        )

    def _cell(
        self, attribute: Attribute, draft: CellDraft | None, evidence: EvidenceSet
    ) -> ComparisonCell:
        """The cited cell, or "Not reported" when the draft has no text or no valid label."""
        text = (draft.text or "").strip() if draft else ""
        labels = evidence.check(draft.citations).valid if draft and text else []
        if not labels:
            return ComparisonCell(
                attribute=attribute, text=NOT_REPORTED, reported=False, citations=[]
            )
        return ComparisonCell(
            attribute=attribute,
            text=text,
            reported=True,
            citations=self._citations.citations_for(text, labels, evidence),
        )


def _request(title: str | None, evidence: EvidenceSet) -> str:
    lines = [data_block("paper_title", title or "Untitled"), "", "Attributes:"]
    for attribute in ATTRIBUTE_QUERIES:
        labels = evidence.labels_for(attribute)
        lines.append(f"{attribute}: {', '.join(labels) if labels else 'no passages'}")
    lines += ["", data_block("evidence", _passages(evidence))]
    return "\n".join(lines)


def _synthesis_request(topic: str, papers: dict[str, UUID], evidence: EvidenceSet) -> str:
    label_of = {document_id: label for label, document_id in papers.items()}
    titles = {item.chunk.document_id: item.chunk.document_title for item in evidence.items}
    paper_list = "\n".join(
        f"[{label}] {titles.get(document_id) or 'Untitled'}"
        for label, document_id in papers.items()
    )
    return "\n\n".join(
        [
            data_block("topic", topic),
            data_block("papers", paper_list),
            data_block("evidence", _passages(evidence, label_of)),
        ]
    )


def _check_request(
    topic: str,
    pairs: dict[str, tuple[Finding, Finding, float]],
    papers: dict[str, UUID],
    evidence: EvidenceSet,
) -> str:
    """The topic, each candidate pair with its findings' paper and passage labels, and the
    passages of those findings."""
    paper_of = {document_id: label for label, document_id in papers.items()}
    label_of = {item.chunk.chunk_id: item.label for item in evidence.items}

    def finding(f: Finding) -> str:
        labels = ", ".join(label_of[c.chunk_id] for c in f.citations if c.chunk_id in label_of)
        return f"{paper_of[f.document_id]}: {f.text} (passages: {labels})"

    pair_list = "\n\n".join(
        f"[{label}]\nA) {finding(a)}\nB) {finding(b)}" for label, (a, b, _) in pairs.items()
    )
    return "\n\n".join(
        [
            data_block("topic", topic),
            data_block("pairs", pair_list),
            data_block("evidence", _passages(evidence, paper_of)),
        ]
    )


def _passages(evidence: EvidenceSet, paper_labels: dict[UUID, str] | None = None) -> str:
    """Each passage as `[E1] P1, p. 3, Methods` (paper label only when given) and its text."""
    return "\n\n".join(
        f"[{item.label}] "
        + (f"{paper_labels[item.chunk.document_id]}, " if paper_labels else "")
        + (
            f"p. {item.chunk.page_start}"
            if item.chunk.page_start == item.chunk.page_end
            else f"pp. {item.chunk.page_start}-{item.chunk.page_end}"
        )
        + (f", {item.chunk.section}" if item.chunk.section else "")
        + f"\n{item.chunk.text}"
        for item in evidence.items
    )
