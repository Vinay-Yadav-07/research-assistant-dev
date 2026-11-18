"""Benchmark v1 (SRS §17.4, D-063): questions with gold passages, and the corpora they ask about.

Each line of `benchmark_v1.jsonl` is one item. A single-paper item gives its gold passage in
`paper`/`page`/`snippet`; a multi-paper or comparison item lists its passages in `evidence`.
Unanswerable items have no gold passage. Items without `type` (the calibration split, written
before task #10) are `single` if answerable and `unanswerable` otherwise.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

BACKEND = Path(__file__).resolve().parents[1]
BENCHMARK = BACKEND / "eval/data/benchmark_v1.jsonl"
CORPORA = BACKEND / "eval/data/corpora_v1.json"
DATASET_VERSION = "benchmark_v1"

Split = Literal["calibration", "test"]
ItemType = Literal["single", "multi", "comparison", "unanswerable"]


@dataclass(frozen=True)
class GoldPassage:
    """A passage that answers (part of) a question: a paper file, its 1-based page, a quote."""

    paper: str
    page: int
    snippet: str


@dataclass(frozen=True)
class BenchmarkItem:
    """One benchmark question (SRS §17.4); gold fields are None for unanswerable ones."""

    id: str
    split: Split
    corpus: str
    question: str
    answerable: bool
    paper: str | None
    page: int | None
    snippet: str | None
    drafted_by: str
    verified_by: str
    type: ItemType = "single"
    evidence: tuple[GoldPassage, ...] = ()

    @property
    def gold(self) -> tuple[GoldPassage, ...]:
        """Every gold passage: `evidence`, or the single `paper`/`page`/`snippet` passage."""
        if self.evidence:
            return self.evidence
        if self.paper is None or self.page is None or self.snippet is None:
            return ()
        return (GoldPassage(self.paper, self.page, self.snippet),)

    @property
    def verified(self) -> bool:
        """True once a team member has reviewed the item."""
        return bool(self.verified_by)


def load_items(path: Path = BENCHMARK, *, split: Split | None = None) -> list[BenchmarkItem]:
    """Benchmark items, optionally only one split."""
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    items = [_item(row) for row in rows]
    return [item for item in items if split is None or item.split == split]


def load_corpora(path: Path = CORPORA) -> dict[str, list[Path]]:
    """PDF paths per corpus name (they are git-ignored and may be missing)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        name: [BACKEND / corpus["dir"] / paper["file"] for paper in corpus["papers"]]
        for name, corpus in data["corpora"].items()
    }


def _item(row: dict[str, Any]) -> BenchmarkItem:
    default_type: ItemType = "single" if row["answerable"] else "unanswerable"
    return BenchmarkItem(
        id=row["id"],
        split=row["split"],
        corpus=row["corpus"],
        question=row["question"],
        answerable=row["answerable"],
        paper=row["paper"],
        page=row["page"],
        snippet=row["snippet"],
        drafted_by=row["drafted_by"],
        verified_by=row["verified_by"],
        type=row.get("type", default_type),
        evidence=tuple(
            GoldPassage(e["paper"], e["page"], e["snippet"]) for e in row.get("evidence", ())
        ),
    )
