"""Human verification of the judge evaluation labels (`eval/data/kg_judge_v1.jsonl`).

    uv run python -m scripts.kg_judge_labels sheet   # writes the review sheet and a blank CSV
    uv run python -m scripts.kg_judge_labels apply   # checks the filled CSV, writes verified labels

The draft labels (drafted by Claude) are never changed. In the CSV, `verified_label` is `ok` to
confirm the draft or one of `stated`, `not_stated`, `other_work`; `verified_by` is the reviewer.
`verified_borderline` (`yes`/`no`) is optional and keeps the draft flag when empty. `apply`
refuses a CSV with any row left empty, so nothing is ever verified automatically, and writes
`kg_judge_v1_verified.jsonl` next to the draft.
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from app.services.knowledge_graph_judge import DEFINITIONS, REASONS

DATA = Path(__file__).resolve().parents[1] / "eval/data"
DRAFT = DATA / "kg_judge_v1.jsonl"
SHEET = DATA / "kg_judge_v1_review.md"
LABELS_CSV = DATA / "kg_judge_v1_labels.csv"
VERIFIED = DATA / "kg_judge_v1_verified.jsonl"
COLUMNS = (
    "id",
    "relationship",
    "draft_label",
    "draft_borderline",
    "verified_label",
    "verified_reason",
    "verified_borderline",
    "verified_by",
    "comment",
)
LABELS = tuple(REASONS)


def drafts(path: Path = DRAFT) -> list[dict[str, Any]]:
    """The draft rows, in file order."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def relationship(row: dict[str, Any]) -> str:
    """`source (type) —relation→ target (type)`, one line."""
    return (
        f"{row['source']['name']} ({row['source']['type']}) —{row['relation_type']}→ "
        f"{row['target']['name']} ({row['target']['type']})"
    )


def sheet_markdown(rows: list[dict[str, Any]]) -> str:
    """The review sheet: every candidate, borderline cases in their own section."""
    lines = [
        "# Relationship judge evaluation set v1: label review",
        "",
        "Draft labels were proposed by Claude and are **not verified**. For each candidate, decide "
        "whether the **quote**, read with its **context sentence**, says that *this paper itself* "
        "states the relationship in the direction shown:",
        "",
        "- `stated`: yes.",
        "- `not_stated`: the entities only appear together, or the quote states a different "
        "relationship, the other direction, or something that needs an inference.",
        "- `other_work`: the quote states it, but about cited or earlier studies, a cited report, "
        "or general background.",
        "",
        f"Record decisions in `{LABELS_CSV.name}`: `verified_label` = `ok` (agree) or the correct "
        "label, plus `verified_by`. Optionally fix `verified_borderline` (`yes`/`no`) and add a "
        "`comment`. Then run `uv run python -m scripts.kg_judge_labels apply`.",
        "",
        "Relationship meanings: "
        + "; ".join(f"`{name}`: {meaning}" for name, meaning in DEFINITIONS.items())
        + ".",
        "",
    ]
    for title, group in (
        ("Clear cases", [r for r in rows if not r["borderline"]]),
        ("Borderline cases (scored separately)", [r for r in rows if r["borderline"]]),
    ):
        lines += [f"## {title} ({len(group)})", ""]
        for row in group:
            context = row["context"] or "(none: the quote opens the paper)"
            origin = (
                "constructed from a real quote" if row["constructed"] else "kept by a model run"
            )
            lines += [
                f"### {row['id']}: {row['relation_type']}",
                "",
                f"- **Paper:** {row['paper_title']} ({row['field']}), section "
                f"*{row['section'] or 'unknown'}*",
                f"- **Relationship:** {relationship(row)}",
                f"- **Context sentence** ({row['context_source'].replace('_', ' ')}): {context}",
                f"- **Quote:** > {row['quote']}",
                f"- **Draft label:** `{row['label']}` ({row['reason']}), {origin}",
                f"- **Why:** {row['note']}",
                "",
            ]
    return "\n".join(lines)


def write_sheet() -> None:
    """Write the review sheet and a CSV with every decision column empty."""
    rows = drafts()
    SHEET.write_text(sheet_markdown(rows), encoding="utf-8")
    if LABELS_CSV.exists():
        sys.exit(f"{LABELS_CSV.name} exists; delete it first to start the review again")
    with LABELS_CSV.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "id": row["id"],
                    "relationship": relationship(row),
                    "draft_label": row["label"],
                    "draft_borderline": "yes" if row["borderline"] else "no",
                }
            )
    print(f"wrote {SHEET} and {LABELS_CSV} ({len(rows)} candidates)")


def verified_rows(
    rows: list[dict[str, Any]], decisions: list[dict[str, str]]
) -> list[dict[str, Any]]:
    """The draft rows with the human decisions added; raises ValueError on any gap or error."""
    by_id = {d["id"].strip(): d for d in decisions}
    if set(by_id) != {r["id"] for r in rows}:
        raise ValueError("the CSV must have exactly one row per candidate")
    problems, out = [], []
    for row in rows:
        decision = {k: (v or "").strip() for k, v in by_id[row["id"]].items()}
        label = decision["verified_label"].lower()
        if label == "ok":
            label = row["label"]
        if label not in LABELS:
            problems.append(f"{row['id']}: verified_label must be ok, {', '.join(LABELS)}")
            continue
        if not decision["verified_by"]:
            problems.append(f"{row['id']}: verified_by is empty")
            continue
        reason = decision["verified_reason"] or (row["reason"] if label == row["label"] else "")
        if reason and reason not in REASONS[label]:
            problems.append(f"{row['id']}: reason {reason!r} does not fit {label}")
            continue
        borderline = decision["verified_borderline"].lower()
        if borderline not in ("", "yes", "no"):
            problems.append(f"{row['id']}: verified_borderline must be yes, no, or empty")
            continue
        out.append(
            {
                **row,
                "human_label": label,
                "human_reason": reason or None,
                "human_borderline": row["borderline"] if not borderline else borderline == "yes",
                "verified_by": decision["verified_by"],
                "human_comment": decision["comment"] or None,
            }
        )
    if problems:
        raise ValueError("\n".join(problems))
    return out


def apply() -> None:
    """Check the filled CSV and write the verified labels next to the drafts."""
    with LABELS_CSV.open(newline="", encoding="utf-8") as file:
        decisions = list(csv.DictReader(file))
    try:
        rows = verified_rows(drafts(), decisions)
    except ValueError as error:
        sys.exit(f"not applied:\n{error}")
    with VERIFIED.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    changed = sum(r["human_label"] != r["label"] for r in rows)
    print(f"wrote {VERIFIED}: {len(rows)} verified, {changed} labels changed from the draft")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["sheet", "apply"])
    if parser.parse_args().action == "sheet":
        write_sheet()
    else:
        apply()


if __name__ == "__main__":
    main()
