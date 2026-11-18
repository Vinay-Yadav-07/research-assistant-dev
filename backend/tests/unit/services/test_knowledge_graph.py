"""S10 extraction and evidence validation with the fake LLM and fake NLI (SRS §9.1, D-081)."""

from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest

from app.core.errors import CallBudgetExceededError, LLMOutputError, LLMQuotaExceededError
from app.providers.fakes import FakeLLM, FakeNLI
from app.providers.nli import NLIPair, NLIScores
from app.repositories.chunks import ChunkRecord
from app.services.citations import CitationService
from app.services.knowledge_graph import (
    EXTRACTOR_VERSION,
    AttributionContext,
    KGBatchExtraction,
    KGExtractionOptions,
    KnowledgeGraphExtractor,
    attribution_context,
    attribution_problem,
    batch_request,
    batches,
    inside_phrase,
    is_reference_list,
    is_review,
    names_as_identity,
    names_in,
    normalize_key,
    select_chunks,
    verbatim_span,
)
from app.services.knowledge_graph_jobs import CallBudget

PAPER = uuid4()
OPTIONS = KGExtractionOptions(
    min_chunk_words=5,
    max_chunks_per_paper=60,
    chunks_per_call=2,
    max_output_tokens=500,
    entailment_score=0.9,
    contradiction_score=0.5,
)
EVALUATED = "We evaluated LSTM on the M4 dataset and report results below."
COMPARED = "We compared LSTM with Random Forest on every series. Both ran on a laptop."
MENTIONED = "This work describes LSTM and Random Forest, two common forecasting methods."
FOUND = "LSTM reduced the forecasting error by 12% on the M4 dataset."


def chunk(text: str, *, section: str | None = "Results", index: int = 0) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=uuid4(),
        document_id=PAPER,
        document_title="Forecasting with neural networks",
        chunk_index=index,
        page_start=index + 1,
        page_end=index + 1,
        section=section,
        text=text,
    )


def entity(id: str, type: str, name: str, passage: str = "E1") -> dict[str, str]:
    return {"id": id, "type": type, "name": name, "passage": passage}


def relation(
    source: str,
    target: str,
    type: str,
    quote: str,
    *,
    passage: str = "E1",
    stance: str = "own_work",
) -> dict[str, str]:
    return {
        "source": source,
        "target": target,
        "type": type,
        "passage": passage,
        "quote": quote,
        "stance": stance,
    }


def extractor(llm: FakeLLM | None = None, nli: Any = None) -> KnowledgeGraphExtractor:
    return KnowledgeGraphExtractor(
        llm or FakeLLM(), nli or FakeNLI(), CitationService(300), OPTIONS
    )


async def validate(
    passages: list[ChunkRecord], entities: list[dict[str, str]], relations: list[dict[str, str]]
) -> Any:
    output = KGBatchExtraction.model_validate({"entities": entities, "relations": relations})
    return await extractor().validate(PAPER, passages, output, prefix="b0")


# --- chunk selection and batching --------------------------------------------------------------


def test_short_passages_reference_lists_and_back_matter_are_skipped() -> None:
    references = "\n".join(
        f"[{n}] Smith J, et al. Deep forecasting. J Forecast. 2021;{n}:1-10. doi:10.1/x{n}"
        for n in range(1, 6)
    )
    kept = chunk(EVALUATED, section="Results")
    mislabelled = chunk(COMPARED, section="References")
    chunks = [
        chunk("Too short.", section="Intro"),
        kept,
        chunk(references, section="References"),
        chunk(references, section="Discussion"),
        chunk(EVALUATED, section="Acknowledgements"),
        chunk(EVALUATED, section="Conflict of interest"),
        mislabelled,
    ]

    assert select_chunks(chunks, OPTIONS) == [kept, mislabelled]


def test_body_text_with_years_is_not_a_reference_list() -> None:
    body = (
        "In 2020, forecasting competitions grew. In 2021, LSTM models won.\n"
        "Results from 2022 confirm the trend across many series."
    )
    assert not is_reference_list(body)
    assert is_reference_list("1. Lee K, et al. Models. 2019.\n2. Kim J. Data. doi:10.2/y (2020)")


def test_at_most_max_chunks_per_paper_are_read_in_batches() -> None:
    chunks = [chunk(EVALUATED, index=n) for n in range(7)]
    options = KGExtractionOptions(**{**OPTIONS.__dict__, "max_chunks_per_paper": 5})

    selected = select_chunks(chunks, options)
    groups = batches(selected, 2)

    assert selected == chunks[:5]
    assert [len(g) for g in groups] == [2, 2, 1]


def test_batch_request_labels_passages_and_marks_them_as_data() -> None:
    request = batch_request([chunk(EVALUATED, index=0), chunk(COMPARED, section=None, index=2)])

    assert "<paper_title>\nForecasting with neural networks\n</paper_title>" in request
    assert "[E1] p. 1, Results\n" + EVALUATED in request
    assert "[E2] p. 3\n" + COMPARED in request
    assert request.count("<passages>") == 1


# --- text matching and normalization -----------------------------------------------------------


def test_verbatim_span_ignores_case_spacing_and_typography_and_returns_the_original() -> None:
    text = "Results:  We used the “M4” dataset—all series. Next."

    assert verbatim_span('we used the "m4" dataset-all   series.', text) == (
        "We used the “M4” dataset—all series."
    )
    assert verbatim_span("we used the M5 dataset", text) is None
    assert verbatim_span("   ", text) is None


def test_names_match_whole_words_with_plurals() -> None:
    assert names_in("LSTM", "Two LSTMs were trained.")
    assert names_in("random forest", "A Random  Forest baseline.")
    assert not names_in("LSTM", "A BiLSTM was trained.")
    assert not names_in("", "anything")


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Long Short-Term Memory", "long short term memory"),
        ("CNNs", "cnn"),
        ("Random Forests", "random forest"),
        ("analysis", "analysis"),
        ("corpus", "corpus"),
        ("Mass", "mass"),
        ("F1-score", "f1 score"),
        ("  R² ", "r2"),
        ("...", ""),
    ],
)
def test_normalize_key(name: str, key: str) -> None:
    assert normalize_key(name) == key


# --- evidence validation -----------------------------------------------------------------------


async def test_a_relationship_stated_by_its_quote_is_kept_with_the_exact_span() -> None:
    passage = chunk(EVALUATED)
    result = await validate(
        [passage],
        [entity("n1", "method", "LSTM"), entity("n2", "dataset", "M4 dataset")],
        [relation("n1", "n2", "evaluated_on", "we evaluated LSTM on the m4 dataset")],
    )

    (kept,) = result.relations
    assert kept.relation_type == "evaluated_on"
    assert kept.quote == "We evaluated LSTM on the M4 dataset"
    assert kept.chunk_id == passage.chunk_id
    assert kept.entailment_score >= 0.9
    keys = {m.key: m for m in result.entities}
    assert (keys[kept.source_key].normalized_key, keys[kept.target_key].normalized_key) == (
        "lstm",
        "m4 dataset",
    )
    assert not result.rejected


async def test_co_mentioned_entities_without_a_stated_comparison_are_rejected() -> None:
    result = await validate(
        [chunk(MENTIONED)],
        [entity("a", "method", "LSTM"), entity("b", "method", "Random Forest")],
        [relation("a", "b", "compared_with", MENTIONED)],
    )

    assert result.relations == []
    assert result.rejected["not_entailed"] == 1
    # The entities themselves are named in their passage, so they stay.
    assert {m.normalized_key for m in result.entities} == {"lstm", "random forest"}


async def test_a_stated_comparison_is_kept_in_canonical_order() -> None:
    result = await validate(
        [chunk(COMPARED)],
        [entity("rf", "method", "Random Forest"), entity("l", "method", "LSTM")],
        [
            relation(
                "rf", "l", "compared_with", "We compared LSTM with Random Forest on every series."
            )
        ],
    )

    (kept,) = result.relations
    keys = {m.key: m.normalized_key for m in result.entities}
    assert (keys[kept.source_key], keys[kept.target_key]) == ("lstm", "random forest")


@pytest.mark.parametrize(
    ("relations", "reason"),
    [
        ([relation("n1", "n2", "evaluated_on", EVALUATED, passage="E9")], "label_invalid"),
        ([relation("n1", "n2", "evaluated_on", "We evaluated GRU on M4")], "quote_not_verbatim"),
        (
            [relation("n1", "n2", "evaluated_on", "LSTM. Was. Evaluated. On the M4 dataset.")],
            "quote_not_verbatim",
        ),
        ([relation("n1", "zz", "evaluated_on", EVALUATED)], "entity_unknown"),
        ([relation("n1", "n1", "evaluated_on", EVALUATED)], "entity_unknown"),
        ([relation("n2", "n1", "evaluated_on", EVALUATED)], "type_not_allowed"),
        ([relation("n1", "n2", "uses", EVALUATED)], "not_entailed"),
        ([relation("n1", "n2", "evaluated_on", "We evaluated LSTM")], "entity_not_in_quote"),
        ([relation("n1", "n2", "evaluated_on", EVALUATED, stance="hedged")], "not_own_work"),
        ([relation("n1", "n2", "evaluated_on", EVALUATED, stance="other_work")], "not_own_work"),
    ],
)
async def test_each_rule_rejects_and_is_counted(
    relations: list[dict[str, str]], reason: str
) -> None:
    result = await validate(
        [chunk(EVALUATED)],
        [entity("n1", "method", "LSTM"), entity("n2", "dataset", "M4 dataset")],
        relations,
    )

    assert result.relations == []
    assert result.rejected[reason] == 1


async def test_quotes_longer_than_two_sentences_are_rejected() -> None:
    text = "LSTM ran first. LSTM ran again. We evaluated LSTM on the M4 dataset."
    result = await validate(
        [chunk(text)],
        [entity("n1", "method", "LSTM"), entity("n2", "dataset", "M4 dataset")],
        [relation("n1", "n2", "evaluated_on", text)],
    )

    assert result.rejected["quote_too_long"] == 1


async def test_future_work_quotes_are_rejected_even_when_marked_own_work() -> None:
    text = "In future work we plan to evaluate LSTM on the M4 dataset."
    result = await validate(
        [chunk(text)],
        [entity("n1", "method", "LSTM"), entity("n2", "dataset", "M4 dataset")],
        [relation("n1", "n2", "evaluated_on", text)],
    )

    assert result.rejected["not_own_work"] == 1


class ScoredNLI:
    """Returns the same scores for every pair."""

    def __init__(self, scores: NLIScores) -> None:
        self.scores = scores
        self.pairs: list[NLIPair] = []

    @property
    def model_name(self) -> str:
        return "scored-nli"

    async def classify(self, pairs: Any) -> list[NLIScores]:
        self.pairs += list(pairs)
        return [self.scores for _ in pairs]


@pytest.mark.parametrize(
    ("scores", "reason"),
    [
        (NLIScores(entailment=0.89, neutral=0.11, contradiction=0.0), "not_entailed"),
        (NLIScores(entailment=0.95, neutral=0.0, contradiction=0.5), "contradicted"),
    ],
)
async def test_nli_thresholds(scores: NLIScores, reason: str) -> None:
    nli = ScoredNLI(scores)
    output = KGBatchExtraction.model_validate(
        {
            "entities": [entity("n1", "method", "LSTM"), entity("n2", "dataset", "M4 dataset")],
            "relations": [relation("n1", "n2", "evaluated_on", EVALUATED)],
        }
    )

    result = await extractor(nli=nli).validate(PAPER, [chunk(EVALUATED)], output, prefix="b0")

    assert result.rejected[reason] == 1
    assert nli.pairs == [NLIPair(premise=EVALUATED, hypothesis="LSTM is evaluated on M4 dataset.")]


async def test_findings_are_checked_by_entailment_and_scoped_to_their_paper() -> None:
    result = await validate(
        [chunk(FOUND)],
        [
            entity("n1", "method", "LSTM"),
            entity("f1", "finding", "LSTM reduced the forecasting error by 12%."),
            entity("f2", "finding", "LSTM doubled the training cost."),
        ],
        [
            relation("n1", "f1", "reports", FOUND),
            relation("n1", "f2", "reports", FOUND),
        ],
    )

    (kept,) = result.relations
    finding = next(m for m in result.entities if m.key == kept.target_key)
    assert finding.normalized_key.startswith(f"{PAPER}:")
    assert result.rejected["not_entailed"] == 1
    # A finding never stands alone: f2 is not stored.
    assert sum(1 for m in result.entities if m.entity_type == "finding") == 1


async def test_entities_not_named_in_their_passage_are_dropped() -> None:
    result = await validate(
        [chunk(EVALUATED)],
        [entity("n1", "method", "GRU"), entity("n2", "dataset", "M4 dataset", passage="E7")],
        [],
    )

    assert result.entities == []
    assert result.rejected["entity_not_in_passage"] == 2


async def test_empty_and_too_long_names_are_rejected() -> None:
    result = await validate(
        [chunk(EVALUATED)],
        [entity("n1", "method", " ... "), entity("n2", "method", "x" * 121)],
        [],
    )

    assert result.rejected == {"name_empty": 1, "name_too_long": 1}


async def test_two_drafts_for_one_name_in_one_passage_are_one_mention() -> None:
    result = await validate(
        [chunk(COMPARED)],
        [entity("a", "method", "LSTM"), entity("b", "method", "lstm")],
        [
            relation(
                "a", "b", "compared_with", "We compared LSTM with Random Forest on every series."
            )
        ],
    )

    assert result.relations == []
    assert len(result.entities) == 1


# --- the extractor over a whole paper ----------------------------------------------------------


def batch_reply(passage: str = "E1") -> dict[str, Any]:
    return {
        "entities": [
            entity("n1", "method", "LSTM", passage),
            entity("n2", "dataset", "M4 dataset", passage),
        ],
        "relations": [
            relation(
                "n1", "n2", "evaluated_on", "We evaluated LSTM on the M4 dataset", passage=passage
            )
        ],
    }


async def test_extract_reads_every_batch_and_takes_one_budget_call_each() -> None:
    chunks = [chunk(EVALUATED, index=n) for n in range(3)]
    llm = FakeLLM(structured={KGBatchExtraction: [batch_reply(), batch_reply("E1")]})
    budget = CallBudget(10)

    extraction = await extractor(llm).extract(PAPER, chunks, budget)

    assert extraction.status == "completed"
    assert extraction.chunks_considered == 3
    assert len(extraction.relations) == 2
    assert len({m.key for m in extraction.entities}) == len(extraction.entities) == 4
    assert budget.used == 2
    (first, _) = llm.calls
    assert first.temperature == 0 and first.max_output_tokens == 500
    assert "<passages>" in first.messages[1].content
    assert EXTRACTOR_VERSION == "kg-extraction.v2+rules.v3"


async def test_invalid_output_is_retried_once_then_counted() -> None:
    chunks = [chunk(EVALUATED, index=n) for n in range(4)]
    llm = FakeLLM(
        structured={
            KGBatchExtraction: [
                LLMOutputError(),
                batch_reply(),
                LLMOutputError(),
                LLMOutputError(),
            ]
        }
    )
    budget = CallBudget(10)

    extraction = await extractor(llm).extract(PAPER, chunks, budget)

    assert extraction.status == "completed"
    assert extraction.rejected_counts["invalid_output"] == 1
    assert len(extraction.relations) == 1
    assert budget.used == 4


async def test_a_paper_whose_every_batch_is_invalid_is_failed() -> None:
    llm = FakeLLM(structured={KGBatchExtraction: [LLMOutputError(), LLMOutputError()]})

    extraction = await extractor(llm).extract(PAPER, [chunk(EVALUATED)], CallBudget(5))

    assert extraction.status == "failed"
    assert extraction.entities == [] and extraction.relations == []


async def test_a_paper_that_does_not_fit_the_budget_makes_no_call() -> None:
    llm = FakeLLM()
    chunks = [chunk(EVALUATED, index=n) for n in range(5)]

    with pytest.raises(CallBudgetExceededError):
        await extractor(llm).extract(PAPER, chunks, CallBudget(2))
    assert llm.calls == []


async def test_quota_errors_reach_the_job() -> None:
    llm = FakeLLM(structured={KGBatchExtraction: [LLMQuotaExceededError()]})

    with pytest.raises(LLMQuotaExceededError):
        await extractor(llm).extract(PAPER, [chunk(EVALUATED)], CallBudget(5))


async def test_a_paper_with_nothing_to_read_makes_no_call() -> None:
    llm = FakeLLM()

    extraction = await extractor(llm).extract(PAPER, [chunk("Too short.")], CallBudget(5))

    assert (extraction.status, extraction.chunks_considered, llm.calls) == ("completed", 0, [])


# --- attribution context -----------------------------------------------------------------------


def test_context_is_the_sentence_before_the_quote_in_its_passage() -> None:
    passage = chunk("Wang studied the A-share market. He found that LSTM works. We used GRU.")

    context = attribution_context("He found that LSTM works.", passage, None)

    assert (context.text, context.source) == ("Wang studied the A-share market.", "same_passage")


def test_a_quote_starting_mid_sentence_gets_the_start_of_that_sentence() -> None:
    passage = chunk("Results are below. The report found that AI strategies outperformed others.")

    context = attribution_context("AI strategies outperformed others.", passage, None)

    assert (context.text, context.source) == ("The report found that", "same_passage")


def test_a_quote_opening_its_passage_takes_context_from_the_previous_passage() -> None:
    previous = chunk("Earlier work exists. Wang found effects. LSTM was trained on M4.", index=0)
    overlapping = chunk("LSTM was trained on M4. It converged.", index=1)
    separate = chunk("We evaluated LSTM on the M4 dataset.", index=1)

    assert attribution_context("LSTM was trained on M4.", overlapping, previous) == (
        AttributionContext("Wang found effects.", "previous_passage")
    )
    assert attribution_context(EVALUATED[:35], separate, previous) == (
        AttributionContext("LSTM was trained on M4.", "previous_passage")
    )


def test_a_quote_opening_the_paper_has_no_context() -> None:
    first = chunk(EVALUATED)

    assert attribution_context(EVALUATED, first, None) == AttributionContext("", "none")


def test_et_al_does_not_end_the_context_sentence() -> None:
    passage = chunk("Data are public. Lee et al. trained LSTM and reported that LSTM converges.")

    context = attribution_context("LSTM converges.", passage, None)

    assert context.text == "Lee et al. trained LSTM and reported that"


# --- attribution filter (rules.v2) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("context", "quote", "problem"),
    [
        ("", "Machine learning models have been developed to predict swelling.", "background"),
        ("", "Previous studies applied LSTM to the M4 dataset.", "background"),
        ("", "Smith et al. [4] found that LSTM outperforms ARIMA.", "cited_study"),
        ("The report found that", "AI strategies outperformed hedge funds.", "cited_study"),
        ("Kim et al. compared both methods and concluded that", "LSTM wins.", "cited_study"),
        (
            "Wang took market data from 2016 to 2021 and found that trading improved efficiency.",
            "It is also concluded that trading lowers volatility.",
            "cited_study",
        ),
        ("They found that LSTM converges.", "Their model also used dropout.", "cited_study"),
        # "the authors" right after a cited study is that study's authors (kgj-001).
        (
            "Chen et al. created a shear-thinning hydrogel of HA microgels.61",
            "In this study, the authors developed a composite hydrogel system.",
            "cited_study",
        ),
    ],
)
def test_clearly_cited_or_background_work_is_rejected(
    context: str, quote: str, problem: str
) -> None:
    assert attribution_problem(quote, AttributionContext(context, "same_passage")) == problem


@pytest.mark.parametrize(
    ("context", "quote"),
    [
        # The paper's own work, even next to citations or "the authors".
        ("Microgels are widely used in tissue repair.", "In this study, the authors propose X."),
        ("Chen et al. created a hydrogel.61", "In this study, we developed a composite hydrogel."),
        ("Smith et al. found that LSTM converges.", "We used LSTM as proposed by Smith et al."),
        ("Wang found that trading improved efficiency.", "Our results also show lower volatility."),
        ("", "The proposed SSR filter has been shown to detect eyes."),
        ("", "A Human Computer Interface system for playing games is designed here."),
        # Own results framed by the paper itself, not by another study.
        ("The empirical results show that", "algorithmic trading improves pricing efficiency."),
        ("Table 2 shows that", "LSTM outperforms ARIMA on M4."),
        ("Simulation showed that", "the switch points move under force."),
        ("Experiments showed that", "LSTM reduces the error by 12%."),
        ("", "A decrease in pH has been observed after 20 days."),
        ("", "Although methods have been proposed, it was possible to print hybrid inks."),
        ("", "As has been shown in Figure 3, the scaffold degrades."),
        ("", "LSTM outperforms previous methods on the M4 dataset."),
        ("", "The G' modulus grew with crosslinking, which is consistent with previous reports."),
        ("", "LSTM converged faster than previous studies reported on M4."),
        # A cited study in the context but a new, unlinked statement in the quote.
        ("Wang found that trading improved efficiency.", "LSTM reduces the error on M4."),
        ("", "LSTM was evaluated on the M4 dataset."),
    ],
)
def test_own_work_statements_are_kept(context: str, quote: str) -> None:
    assert attribution_problem(quote, AttributionContext(context, "same_passage")) is None


@pytest.mark.parametrize(
    ("quote", "problem"),
    [
        # Cited studies the hydrogel review described, from the dev job (2026-10-20).
        ("In this study, the authors developed a composite hydrogel system.", "review_literature"),
        (
            "Furthermore, in a murine model, the osteogenic microgels facilitated bone repair.",
            "review_literature",
        ),
        ("The proposed microgels improved cartilage repair in vivo.", "review_literature"),
        ("In this review, we classify hydrogels by crosslinking chemistry.", None),
        ("We group nanogel synthesis methods into three families.", None),
        ("This review covers injectable microgels for bone repair.", None),
    ],
)
def test_in_a_review_only_its_own_voice_counts_as_its_work(quote: str, problem: str | None) -> None:
    context = AttributionContext("Injectability was tested successfully.", "same_passage")

    assert attribution_problem(quote, context, review=True) == problem


def test_a_review_is_recognised_by_its_title_or_opening() -> None:
    perspectives = "Microgels: Translational Perspectives"
    titled = [replace(chunk("Hydrogels heal tissue."), document_title=perspectives)]
    opening = [chunk("In this review, we summarize injectable hydrogels for repair.", index=0)]
    research = [chunk(EVALUATED, index=0), chunk(COMPARED, index=1)]

    assert is_review(titled) and is_review(opening)
    assert not is_review(research) and not is_review([])


def test_naming_one_entity_as_the_other_is_identity_not_a_relationship() -> None:
    quote = (
        "We discover singularities in the flow field of minimum points. These singularities, "
        "which we call “switch points”, are building blocks of switching behavior."
    )

    assert names_as_identity("switch points", "singularities in the flow field", quote)
    assert names_as_identity("singularities in the flow field", "switch points", quote)
    assert not names_as_identity("our model", "LSTM", "Our model uses a network called LSTM.")
    assert not names_as_identity("LSTM", "M4 dataset", EVALUATED)


def test_a_concept_cut_from_a_longer_phrase_is_detected() -> None:
    ssr = "The SSR filter operates by using the bright-dark relation around Between-the-Eyes area."

    assert inside_phrase("Between-the-Eyes", ssr)
    assert not inside_phrase(
        "eye's ROI", "We apply blink detection in the eye's ROI before tracking."
    )
    assert not inside_phrase(
        "eye's ROI", "To detect a blink we apply motion detection in the eye's ROI"
    )
    assert not inside_phrase("switch points", "The framework of switch points and switch lines.")
    assert not inside_phrase("template matching", "We use template matching, distance, and SSR.")


async def test_validation_rejects_identity_and_cut_concepts_but_keeps_real_uses() -> None:
    identity = "These singularities, which we call switch points, explain switching."
    cut = "The SSR filter uses the bright-dark relation around Between-the-Eyes area."
    real = "Blink detection uses the eye's ROI before tracking."
    output = KGBatchExtraction.model_validate(
        {
            "entities": [
                entity("n1", "method", "switch points", "E1"),
                entity("n2", "concept", "singularities", "E1"),
                entity("n3", "method", "SSR filter", "E2"),
                entity("n4", "concept", "Between-the-Eyes", "E2"),
                entity("n5", "method", "Blink detection", "E3"),
                entity("n6", "concept", "eye's ROI", "E3"),
            ],
            "relations": [
                relation("n1", "n2", "uses", identity, passage="E1"),
                relation("n3", "n4", "uses", cut, passage="E2"),
                relation("n5", "n6", "uses", real, passage="E3"),
            ],
        }
    )

    result = await extractor().validate(
        PAPER, [chunk(identity), chunk(cut, index=1), chunk(real, index=2)], output, prefix="b0"
    )

    assert result.rejected["identity_not_relation"] == 1
    assert result.rejected["entity_inside_phrase"] == 1
    assert [r.relation_type for r in result.relations] == ["uses"]


async def test_a_review_keeps_only_relationships_in_its_own_voice() -> None:
    cited = "The proposed model uses hyaluronic acid to improve repair."
    own = "We compared LSTM with Random Forest on every series."
    output = KGBatchExtraction.model_validate(
        {
            "entities": [
                entity("n1", "method", "model", "E1"),
                entity("n2", "method", "hyaluronic acid", "E1"),
                entity("n3", "method", "LSTM", "E2"),
                entity("n4", "method", "Random Forest", "E2"),
            ],
            "relations": [
                relation("n1", "n2", "uses", cited, passage="E1"),
                relation("n3", "n4", "compared_with", own, passage="E2"),
            ],
        }
    )
    passages = [chunk(cited), chunk(own, index=1)]

    as_review = await extractor().validate(PAPER, passages, output, prefix="b0", review=True)
    as_research = await extractor().validate(PAPER, passages, output, prefix="b0")

    assert as_review.rejected["attributed_elsewhere"] == 1
    assert [r.relation_type for r in as_review.relations] == ["compared_with"]
    assert len(as_research.relations) == 2


async def test_validation_rejects_a_quote_continuing_a_cited_study_in_the_previous_passage() -> (
    None
):
    earlier = chunk(
        "Background is given here. Lee et al. trained models and reported that", index=0
    )
    passage = chunk("LSTM reduced the forecasting error by 12% on the M4 dataset.", index=1)
    output = KGBatchExtraction.model_validate(
        {
            "entities": [entity("n1", "method", "LSTM"), entity("n2", "finding", FOUND)],
            "relations": [relation("n1", "n2", "reports", FOUND)],
        }
    )

    cited = await extractor().validate(
        PAPER, [passage], output, prefix="b0", previous={passage.chunk_id: earlier}
    )
    alone = await extractor().validate(PAPER, [passage], output, prefix="b0")

    assert (cited.rejected["attributed_elsewhere"], cited.relations) == (1, [])
    assert len(alone.relations) == 1
