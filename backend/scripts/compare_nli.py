"""Choose A3's NLI model and score bands (D-067) on the verifier pairs of the calibration split.

Run from `backend/` (needs the tissue and scaffold PDFs, see `eval/data/corpora_v1.json`):
    uv run python -m scripts.compare_nli
    uv run python -m scripts.compare_nli --models cross-encoder/nli-deberta-v3-small --threads 2

Each pair in `eval/data/verifier_pairs_v1.jsonl` is a claim written against one answerable
calibration question and labelled supported, partial, or unsupported. Its premise is the chunk
holding the question's gold snippet (the chunking of `scripts.compare_embeddings`). Each model
scores every claim twice, against the whole chunk (truncated at `NLI_MAX_LENGTH` tokens) and
against A3's sentence windows (best window counts). Reported per model and premise mode: ROC AUC
of entailment for supported vs. the rest, the decisions under the configured bands, bands
calibrated so that no partial or unsupported claim is accepted without the judge, and CPU time
per claim at `--threads` torch threads (the Space has 2).
"""

import argparse
import asyncio
import json
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.agents.verification import premise_windows
from app.core.config import Settings, get_settings
from app.providers.local import CrossEncoderNLI, LocalInference
from app.providers.nli import NLIPair
from eval.dataset import BACKEND, load_corpora, load_items
from scripts.compare_embeddings import chunk_paper, normalize, page_words
from scripts.experiment_log import write_experiment

PAIRS = BACKEND / "eval/data/verifier_pairs_v1.jsonl"
DEFAULT_MODELS = (
    "cross-encoder/nli-deberta-v3-base",
    "cross-encoder/nli-deberta-v3-small",
    "cross-encoder/nli-deberta-v3-xsmall",
    "cross-encoder/nli-MiniLM2-L6-H768",
)
Label = Literal["supported", "partial", "unsupported"]
PremiseMode = Literal["chunk", "windows"]
# Calibrated bands are rounded to this step, away from the errors they guard against.
BAND_STEP = 0.01


@dataclass(frozen=True)
class VerifierPair:
    """A claim written against one calibration question, with its gold label."""

    id: str
    split: str
    item: str
    claim: str
    label: Label
    drafted_by: str
    verified_by: str


@dataclass(frozen=True)
class Scored:
    """A pair's best entailment and highest contradiction over its premises."""

    label: Label
    entailment: float
    contradiction: float


def load_pairs(path: Path = PAIRS) -> list[VerifierPair]:
    """The verifier pairs file."""
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return [VerifierPair(**row) for row in rows]


def decide(row: Scored, supported: float, unsupported: float, contradiction: float) -> str:
    """A3's NLI decision for one claim: supported, unsupported, or judge."""
    if row.entailment >= supported and row.contradiction < contradiction:
        return "supported"
    if row.entailment < unsupported:
        return "unsupported"
    return "judge"


def band_outcome(
    rows: Sequence[Scored], supported: float, unsupported: float, contradiction: float
) -> dict[str, Any]:
    """How the bands treat each label; `false_supported` must stay 0."""
    decisions = [(row.label, decide(row, supported, unsupported, contradiction)) for row in rows]
    n_supported = sum(row.label == "supported" for row in rows)
    return {
        "supported_score": supported,
        "unsupported_score": unsupported,
        "auto_supported": sum(d == ("supported", "supported") for d in decisions),
        "false_supported": sum(lab != "supported" and dec == "supported" for lab, dec in decisions),
        "false_unsupported": sum(d == ("supported", "unsupported") for d in decisions),
        "auto_rejected": sum(lab != "supported" and dec == "unsupported" for lab, dec in decisions),
        "judged": sum(dec == "judge" for _, dec in decisions),
        "supported_total": n_supported,
        "other_total": len(rows) - n_supported,
    }


def calibrate(rows: Sequence[Scored], contradiction: float) -> tuple[float, float]:
    """Bands with no partial/unsupported claim accepted and no supported claim rejected.

    The supported score sits just above the highest entailment of an uncontradicted
    partial/unsupported claim; the unsupported score at the lowest entailment of a supported
    claim (capped at the supported score).
    """
    others = [
        row.entailment
        for row in rows
        if row.label != "supported" and row.contradiction < contradiction
    ]
    supported_scores = [row.entailment for row in rows if row.label == "supported"]
    if not supported_scores:
        raise ValueError("calibration needs supported pairs")
    upper = min(1.0, _step_up(max(others, default=0.0)))
    lower = min(_step_down(min(supported_scores)), upper)
    return upper, lower


def roc_auc(rows: Sequence[Scored]) -> float:
    """Probability that a supported claim has higher entailment than another claim."""
    positives = [row.entailment for row in rows if row.label == "supported"]
    negatives = [row.entailment for row in rows if row.label != "supported"]
    if not positives or not negatives:
        raise ValueError("ROC AUC needs supported and other pairs")
    wins = sum((p > n) + 0.5 * (p == n) for p in positives for n in negatives)
    return wins / (len(positives) * len(negatives))


def _step_up(value: float) -> float:
    """The smallest band step strictly above `value`."""
    step = round((math.floor(round(value / BAND_STEP, 6)) + 1) * BAND_STEP, 2)
    return step if step > value else round(step + BAND_STEP, 2)


def _step_down(value: float) -> float:
    """The largest band step at or below `value`."""
    step = round(math.floor(round(value / BAND_STEP, 6)) * BAND_STEP, 2)
    return step if step <= value else round(step - BAND_STEP, 2)


def gold_chunks(settings: Settings) -> dict[str, str]:
    """The chunk holding each answerable calibration question's gold snippet, by item id."""
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(settings.embedding_model)
    paths = {path.name: path for papers in load_corpora().values() for path in papers}
    chunks: dict[str, list[Any]] = {}
    gold: dict[str, str] = {}
    for item in load_items(split="calibration"):
        if not item.answerable or item.paper is None or item.snippet is None:
            continue
        if item.paper not in chunks:
            if not paths[item.paper].exists():
                raise SystemExit(f"missing {paths[item.paper]} (see eval/data/corpora_v1.json)")
            chunks[item.paper] = chunk_paper(item.paper, page_words(paths[item.paper]), tokenizer)
        snippet = normalize(item.snippet)
        gold[item.id] = next(c.text for c in chunks[item.paper] if snippet in normalize(c.text))
    return gold


async def score(
    nli: CrossEncoderNLI,
    pairs: Sequence[VerifierPair],
    gold: dict[str, str],
    mode: PremiseMode,
    window_words: int,
) -> tuple[list[Scored], float, int]:
    """Scores per pair, seconds for all pairs, and the number of NLI pairs run."""
    inputs: list[NLIPair] = []
    owners: list[int] = []
    for index, pair in enumerate(pairs):
        chunk = gold[pair.item]
        premises = [chunk] if mode == "chunk" else premise_windows(chunk, window_words)
        inputs.extend(NLIPair(premise=premise, hypothesis=pair.claim) for premise in premises)
        owners.extend([index] * len(premises))
    started = time.perf_counter()
    results = await nli.classify(inputs)
    seconds = time.perf_counter() - started
    entailment = [0.0] * len(pairs)
    contradiction = [0.0] * len(pairs)
    for owner, result in zip(owners, results, strict=True):
        entailment[owner] = max(entailment[owner], result.entailment)
        contradiction[owner] = max(contradiction[owner], result.contradiction)
    scored = [
        Scored(pair.label, round(e, 4), round(c, 4))
        for pair, e, c in zip(pairs, entailment, contradiction, strict=True)
    ]
    return scored, seconds, len(inputs)


def truncated(
    model_id: str, pairs: Sequence[VerifierPair], gold: dict[str, str], limit: int
) -> int:
    """Pairs whose whole-chunk input exceeds the model's token limit."""
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    return sum(len(tokenizer(gold[pair.item], pair.claim)["input_ids"]) > limit for pair in pairs)


async def run(args: argparse.Namespace) -> None:
    """Score the pairs with every model and premise mode; print and log the results."""
    import torch

    torch.set_num_threads(args.threads)
    settings = get_settings()
    pairs = load_pairs()
    gold = gold_chunks(settings)
    contradiction = settings.verification_contradiction_score
    bands = (settings.verification_supported_score, settings.verification_unsupported_score)
    print(
        f"{len(pairs)} pairs over {len(gold)} gold chunks; {args.threads} torch threads; "
        f"configured bands {bands}, contradiction {contradiction}\n"
    )
    print(
        "| Model | Premise | NLI pairs | ms/claim | AUC | Truncated | Configured bands: "
        "auto ✓ / false ✓ / false ✗ / judged | Calibrated bands (upper, lower): auto ✓ / "
        "auto ✗ / judged |"
    )
    print("|---|---|---|---|---|---|---|---|")
    results: list[dict[str, Any]] = [
        {"id": pair.id, "item": pair.item, "label": pair.label, "claim": pair.claim}
        for pair in pairs
    ]
    summary: dict[str, Any] = {}
    for model_id in args.models:
        nli = CrossEncoderNLI(
            model_id=model_id,
            max_length=settings.nli_max_length,
            batch_size=settings.nli_batch_size,
            inference=LocalInference(1),
        )
        await asyncio.to_thread(nli.load)
        await nli.classify([NLIPair(premise="Warm up.", hypothesis="Warm up.")])
        too_long = truncated(model_id, pairs, gold, settings.nli_max_length)
        for mode in ("chunk", "windows"):
            scored, seconds, n_inputs = await score(nli, pairs, gold, mode, args.window_words)
            configured = band_outcome(scored, *bands, contradiction)
            upper, lower = calibrate(scored, contradiction)
            calibrated = band_outcome(scored, upper, lower, contradiction)
            key = f"{model_id}|{mode}"
            summary[key] = {
                "nli_pairs": n_inputs,
                "ms_per_claim": round(seconds * 1000 / len(pairs)),
                "ms_per_nli_pair": round(seconds * 1000 / n_inputs),
                "roc_auc": round(roc_auc(scored), 3),
                "truncated_pairs": too_long if mode == "chunk" else 0,
                "configured": configured,
                "calibrated": calibrated,
            }
            for row, item in zip(results, scored, strict=True):
                row[key] = {"entailment": item.entailment, "contradiction": item.contradiction}
            s = summary[key]
            print(
                f"| {model_id} | {mode} | {n_inputs} | {s['ms_per_claim']} | {s['roc_auc']:.3f} | "
                f"{s['truncated_pairs']} | {configured['auto_supported']} / "
                f"{configured['false_supported']} / {configured['false_unsupported']} / "
                f"{configured['judged']} | ({upper:.2f}, {lower:.2f}): "
                f"{calibrated['auto_supported']} / {calibrated['auto_rejected']} / "
                f"{calibrated['judged']} |",
                flush=True,
            )

    path = write_experiment(
        "compare_nli",
        settings=settings,
        models={"nli": list(args.models)},
        dataset=PAIRS.name,
        parameters={
            "threads": args.threads,
            "window_words": args.window_words,
            "contradiction_score": contradiction,
            "configured_bands": list(bands),
            "pairs": len(pairs),
            "labels": {lab: sum(p.label == lab for p in pairs) for lab in Label.__args__},
            "verified_pairs": sum(bool(p.verified_by) for p in pairs),
        },
        results=results,
        summary=summary,
        hardware_extra={"torch_threads_set": args.threads},
    )
    print(f"\nWrote {path}")


def main() -> None:
    """Parse arguments and run the comparison."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    parser.add_argument("--threads", type=int, default=2, help="torch threads (Space: 2)")
    parser.add_argument(
        "--window-words",
        type=int,
        default=get_settings().verification_window_words,
        help="A3 premise window size in words",
    )
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
