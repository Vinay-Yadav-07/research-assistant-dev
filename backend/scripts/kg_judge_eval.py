"""Evaluate the relationship judge prototype on `eval/data/kg_judge_v1.jsonl` (D-081 follow-up).

Each row is a candidate relationship with its verbatim quote, the sentence before it, and a
human label: `stated`, `not_stated`, or `other_work`. The judge makes one call per paper.

Offline (no API calls):
    uv run python -m scripts.kg_judge_eval --fake gold       # replays the labels: must score 1.0
    uv run python -m scripts.kg_judge_eval --fake keep-all   # no judge: today's pipeline

Real calls only after approval (one per paper, retries included in `--max-requests`); writes one
experiment JSON to `docs/experiments/`:
    uv run python -m scripts.kg_judge_eval --provider groq --model openai/gpt-oss-120b

`--provisional` runs real calls against the Claude-drafted labels before anyone has checked
them. Its results are marked unverified everywhere: engineering guidance only, never evidence
that the judge meets the accuracy bar. Official runs still require the verified labels.
"""

import argparse
import asyncio
import json
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.providers.factory import build_graph_llm
from app.providers.fakes import FakeLLM
from app.providers.llm import LLMProvider
from app.providers.usage import track_usage
from app.services.knowledge_graph_judge import (
    JudgeCandidate,
    JudgeOutcome,
    JudgeReply,
    RelationshipJudge,
)
from scripts.experiment_log import snippet, write_experiment

DATASET = Path(__file__).resolve().parents[1] / "eval/data/kg_judge_v1.jsonl"
# Written by `scripts.kg_judge_labels apply` once a person has checked every draft label.
VERIFIED = DATASET.with_name("kg_judge_v1_verified.jsonl")


@dataclass(frozen=True)
class LabelledCandidate:
    """A dataset row: the candidate, its paper, and the human verdict."""

    candidate: JudgeCandidate
    document_id: str
    paper_title: str | None
    label: str
    borderline: bool
    constructed: bool


def load(path: Path = DATASET) -> list[LabelledCandidate]:
    """The labelled candidates, in file order; human labels where the file has them."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        rows.append(
            LabelledCandidate(
                candidate=JudgeCandidate(
                    id=row["id"],
                    relation_type=row["relation_type"],
                    source_name=row["source"]["name"],
                    source_type=row["source"]["type"],
                    target_name=row["target"]["name"],
                    target_type=row["target"]["type"],
                    quote=row["quote"],
                    context=row["context"],
                    context_source=row["context_source"],
                    section=row["section"],
                ),
                document_id=row["document_id"],
                paper_title=row["paper_title"],
                label=row.get("human_label", row["label"]),
                borderline=row.get("human_borderline", row["borderline"]),
                constructed=row["constructed"],
            )
        )
    return rows


def score(rows: Sequence[LabelledCandidate], outcomes: dict[str, JudgeOutcome]) -> dict[str, Any]:
    """Keep/drop precision and recall against `stated`, verdict accuracy, and how many cited or
    background relationships were caught."""
    kept = [r for r in rows if outcomes[r.candidate.id].kept]
    stated = [r for r in rows if r.label == "stated"]
    true_kept = [r for r in kept if r.label == "stated"]
    other = [r for r in rows if r.label == "other_work"]
    confusion: Counter[str] = Counter(
        f"{r.label}->{outcomes[r.candidate.id].verdict}" for r in rows
    )
    by_type: dict[str, Counter[str]] = defaultdict(Counter)
    for r in rows:
        right = outcomes[r.candidate.id].kept == (r.label == "stated")
        by_type[r.candidate.relation_type]["right" if right else "wrong"] += 1
    return {
        "candidates": len(rows),
        "kept": len(kept),
        "precision": round(len(true_kept) / len(kept), 3) if kept else None,
        "recall": round(len(true_kept) / len(stated), 3) if stated else None,
        "verdict_accuracy": round(
            sum(outcomes[r.candidate.id].verdict == r.label for r in rows) / len(rows), 3
        )
        if rows
        else None,
        "other_work_caught": round(
            sum(outcomes[r.candidate.id].verdict == "other_work" for r in other) / len(other), 3
        )
        if other
        else None,
        "false_positives": [r.candidate.id for r in kept if r.label != "stated"],
        "false_negatives": [r.candidate.id for r in stated if not outcomes[r.candidate.id].kept],
        "disagreements": [
            f"{r.candidate.id}: {r.label}->{outcomes[r.candidate.id].verdict}"
            for r in rows
            if outcomes[r.candidate.id].verdict != r.label
        ],
        "confusion": dict(sorted(confusion.items())),
        "by_relation_type": {t: dict(c) for t, c in sorted(by_type.items())},
    }


def by_paper(rows: Sequence[LabelledCandidate]) -> dict[str, list[LabelledCandidate]]:
    """Rows grouped by paper, papers in first-seen order (the order calls are made in)."""
    groups: dict[str, list[LabelledCandidate]] = defaultdict(list)
    for row in rows:
        groups[row.document_id].append(row)
    return groups


def fake_llm(rows: Sequence[LabelledCandidate], mode: str) -> FakeLLM:
    """One scripted reply per paper: the labels (`gold`) or `stated` for all (`keep-all`)."""
    reasons = {"stated": "stated", "not_stated": "inferred", "other_work": "cited_study"}
    replies = []
    for group in by_paper(rows).values():
        verdicts = []
        for n, row in enumerate(group, start=1):
            verdict = "stated" if mode == "keep-all" else row.label
            verdicts.append({"candidate": f"R{n}", "verdict": verdict, "reason": reasons[verdict]})
        replies.append({"verdicts": verdicts})
    return FakeLLM(structured={JudgeReply: replies})


async def evaluate(
    rows: Sequence[LabelledCandidate],
    llm: LLMProvider,
    max_output_tokens: int,
    *,
    max_requests: int | None = None,
    worst_per_paper: int = 1,
) -> tuple[dict[str, JudgeOutcome], list[dict[str, Any]]]:
    """Judge each paper's candidates in one call; per-paper timings and usage.

    With `max_requests`, a paper is skipped (left out of `outcomes`) when its worst case of
    `worst_per_paper` requests could exceed the budget, so the run never goes over it.
    """
    judge = RelationshipJudge(llm, max_output_tokens=max_output_tokens)
    outcomes: dict[str, JudgeOutcome] = {}
    calls: list[dict[str, Any]] = []
    for document_id, group in by_paper(rows).items():
        spent = sum(c["calls"] + c["failed_attempts"] for c in calls)
        if max_requests is not None and spent + worst_per_paper > max_requests:
            continue
        started = time.perf_counter()
        with track_usage() as usage:
            results = await judge.judge(group[0].paper_title, [r.candidate for r in group])
        outcomes.update({o.candidate_id: o for o in results})
        calls.append(
            {
                "document_id": document_id,
                "candidates": len(group),
                "seconds": round(time.perf_counter() - started, 2),
                "calls": usage.calls,
                "failed_attempts": usage.failed_attempts,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
            }
        )
    return outcomes, calls


def labels_to_score(
    *, fake: bool, draft: bool, provisional: bool, verified_exists: bool
) -> tuple[Path, str]:
    """The label file to score and its status. Real runs need verified labels unless
    `provisional` is set, which always scores the unverified drafts."""
    if provisional:
        return DATASET, "draft-unverified (PROVISIONAL)"
    if not fake and not verified_exists:
        sys.exit(f"{VERIFIED.name} is missing: real judge runs need human-verified labels")
    if verified_exists and not draft:
        return VERIFIED, "verified"
    return DATASET, "draft"


async def main_async(args: argparse.Namespace) -> None:
    path, status = labels_to_score(
        fake=bool(args.fake),
        draft=args.draft,
        provisional=args.provisional,
        verified_exists=VERIFIED.exists(),
    )
    rows = load(path)
    settings = Settings()
    if args.fake:
        llm: LLMProvider = fake_llm(rows, args.fake)
    else:
        settings = settings.model_copy(
            update={"llm_graph_provider": args.provider, "llm_graph_model": args.model}
        )
        llm = build_graph_llm(settings)
    # The judge tries twice, and each try may use every provider retry.
    worst = 2 * (settings.llm_graph_max_retries + 1)
    outcomes, calls = await evaluate(
        rows, llm, args.max_output_tokens, max_requests=args.max_requests, worst_per_paper=worst
    )
    skipped = [r.candidate.id for r in rows if r.candidate.id not in outcomes]
    rows = [r for r in rows if r.candidate.id in outcomes]
    summary = {
        "labels": status,
        "skipped_for_budget": skipped,
        "all": score(rows, outcomes),
        "without_borderline": score([r for r in rows if not r.borderline], outcomes),
        "borderline_only": score([r for r in rows if r.borderline], outcomes),
        "requests": sum(c["calls"] + c["failed_attempts"] for c in calls),
        "input_tokens": sum(c["input_tokens"] for c in calls),
        "output_tokens": sum(c["output_tokens"] for c in calls),
    }
    if args.provisional:
        print("PROVISIONAL: scored against UNVERIFIED Claude-drafted labels; guidance only.")
    print(json.dumps(summary, indent=1))
    if args.fake:
        return
    write_experiment(
        "kg_judge_eval_provisional" if args.provisional else "kg_judge_eval",
        settings=settings,
        models={"judge_llm": f"{args.provider}:{args.model}"},
        dataset=f"{path.name} ({len(rows)} candidates, {status} labels)",
        results=[
            {
                "id": r.candidate.id,
                "label": r.label,
                "verdict": outcomes[r.candidate.id].verdict,
                "reason": outcomes[r.candidate.id].reason,
                "borderline": r.borderline,
                "quote": snippet(r.candidate.quote),
            }
            for r in rows
        ],
        summary=summary,
        parameters={
            "max_output_tokens": args.max_output_tokens,
            "max_requests": args.max_requests,
            "calls": calls,
        },
        secrets=[
            key.get_secret_value()
            for key in (settings.llm_graph_api_key, settings.gemini_api_key, settings.groq_api_key)
            if key is not None
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fake", choices=["gold", "keep-all"])
    parser.add_argument("--provider", choices=["groq", "gemini"])
    parser.add_argument("--model")
    parser.add_argument("--max-output-tokens", type=int, default=3000)
    parser.add_argument("--max-requests", type=int, default=12, help="hard cap incl. retries")
    parser.add_argument("--draft", action="store_true", help="offline only: score draft labels")
    parser.add_argument(
        "--provisional",
        action="store_true",
        help="real calls scored against UNVERIFIED draft labels; results are guidance only",
    )
    args = parser.parse_args()
    if not args.fake and not (args.provider and args.model):
        parser.error("use --fake, or --provider and --model (real calls need approval)")
    if args.draft and not args.fake:
        parser.error("--draft is for offline runs; use --provisional for unverified real runs")
    if args.provisional and args.fake:
        parser.error("--provisional is for real runs; offline runs already accept --draft")
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
