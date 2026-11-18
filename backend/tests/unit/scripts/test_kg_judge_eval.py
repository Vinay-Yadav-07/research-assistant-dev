"""The judge evaluation set and its scoring (no API calls)."""

from collections import Counter

from app.services.knowledge_graph import ALLOWED_TYPES
from app.services.knowledge_graph_judge import REASONS, JudgeOutcome
from scripts.kg_judge_eval import evaluate, fake_llm, load, score


def test_the_dataset_is_well_formed_and_covers_every_verdict() -> None:
    rows = load()

    assert len({r.candidate.id for r in rows}) == len(rows) >= 30
    assert Counter(r.label for r in rows).keys() == {"stated", "not_stated", "other_work"}
    for row in rows:
        c = row.candidate
        assert c.quote.strip() and c.relation_type in ALLOWED_TYPES
        assert c.context_source in ("same_passage", "previous_passage", "none")
        assert bool(c.context) == (c.context_source != "none")
    assert sum(r.constructed for r in rows) >= 5
    assert {r.candidate.relation_type for r in rows if r.label == "not_stated"} >= {
        "uses",
        "compared_with",
    }


def test_dataset_reasons_match_their_verdicts() -> None:
    import json

    from scripts.kg_judge_eval import DATASET

    for line in DATASET.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        assert row["reason"] in REASONS[row["label"]], row["id"]
        assert row["drafted_by"] == "claude"


def test_score_counts_precision_recall_and_caught_other_work() -> None:
    rows = load()[:4]
    labels = [r.label for r in rows]
    outcomes = {r.candidate.id: JudgeOutcome(r.candidate.id, "stated", "stated") for r in rows}

    result = score(rows, outcomes)

    assert result["kept"] == 4
    assert result["precision"] == round(labels.count("stated") / 4, 3)
    assert result["recall"] == 1.0
    assert result["other_work_caught"] == (0.0 if "other_work" in labels else None)


async def test_gold_replies_score_perfectly_and_keep_all_matches_the_label_share() -> None:
    rows = load()

    gold, gold_calls = await evaluate(rows, fake_llm(rows, "gold"), 1000)
    keep_all, _ = await evaluate(rows, fake_llm(rows, "keep-all"), 1000)

    perfect = score(rows, gold)
    assert (perfect["precision"], perfect["recall"], perfect["verdict_accuracy"]) == (1.0, 1.0, 1.0)
    assert len(gold_calls) == len({r.document_id for r in rows})
    baseline = score(rows, keep_all)
    assert baseline["precision"] == round(sum(r.label == "stated" for r in rows) / len(rows), 3)
    assert baseline["other_work_caught"] == 0.0


def test_real_runs_still_need_verified_labels_unless_provisional() -> None:
    import pytest

    from scripts.kg_judge_eval import DATASET, VERIFIED, labels_to_score

    with pytest.raises(SystemExit):
        labels_to_score(fake=False, draft=False, provisional=False, verified_exists=False)
    assert labels_to_score(fake=False, draft=False, provisional=False, verified_exists=True) == (
        VERIFIED,
        "verified",
    )
    for verified_exists in (False, True):
        path, status = labels_to_score(
            fake=False, draft=False, provisional=True, verified_exists=verified_exists
        )
        assert path == DATASET and "unverified" in status


async def test_request_budget_skips_papers_that_could_overrun_it() -> None:
    rows = load()
    papers = len({r.document_id for r in rows})

    outcomes, calls = await evaluate(
        rows, fake_llm(rows, "gold"), 1000, max_requests=papers, worst_per_paper=2
    )

    assert len(calls) == papers - 1
    judged = score([r for r in rows if r.candidate.id in outcomes], outcomes)
    assert judged["disagreements"] == []
