"""Human verification of the judge evaluation labels (no files written)."""

import pytest

from scripts.kg_judge_labels import drafts, sheet_markdown, verified_rows

ROWS = drafts()


def decisions(**overrides: dict[str, str]) -> list[dict[str, str]]:
    """A complete set of decisions confirming every draft, with per-id overrides."""
    out = []
    for row in ROWS:
        decision = {
            "id": row["id"],
            "verified_label": "ok",
            "verified_reason": "",
            "verified_borderline": "",
            "verified_by": "reviewer",
            "comment": "",
        }
        decision.update(overrides.get(row["id"], {}))
        out.append(decision)
    return out


def test_confirming_keeps_the_draft_label_beside_the_human_one() -> None:
    rows = verified_rows(ROWS, decisions())

    assert [(r["label"], r["human_label"]) for r in rows] == [
        (r["label"], r["label"]) for r in ROWS
    ]
    assert all(r["verified_by"] == "reviewer" for r in rows)
    assert [r["human_borderline"] for r in rows] == [r["borderline"] for r in ROWS]


def test_corrections_override_only_the_human_fields() -> None:
    first = ROWS[0]["id"]
    rows = verified_rows(
        ROWS,
        decisions(
            **{
                first: {
                    "verified_label": "not_stated",
                    "verified_reason": "inferred",
                    "verified_borderline": "yes",
                    "comment": "unclear",
                }
            }
        ),
    )

    assert (rows[0]["label"], rows[0]["human_label"], rows[0]["human_reason"]) == (
        ROWS[0]["label"],
        "not_stated",
        "inferred",
    )
    assert (rows[0]["human_borderline"], rows[0]["human_comment"]) == (True, "unclear")


@pytest.mark.parametrize(
    "override",
    [
        {"verified_label": ""},
        {"verified_label": "maybe"},
        {"verified_by": ""},
        {"verified_label": "stated", "verified_reason": "cited_study"},
        {"verified_borderline": "perhaps"},
    ],
)
def test_empty_or_invalid_decisions_are_refused(override: dict[str, str]) -> None:
    with pytest.raises(ValueError, match=ROWS[0]["id"]):
        verified_rows(ROWS, decisions(**{ROWS[0]["id"]: override}))


def test_every_candidate_needs_exactly_one_decision() -> None:
    with pytest.raises(ValueError, match="exactly one row"):
        verified_rows(ROWS, decisions()[1:])


def test_the_sheet_lists_every_candidate_with_borderline_cases_apart() -> None:
    sheet = sheet_markdown(ROWS)

    assert all(f"### {row['id']}:" in sheet for row in ROWS)
    assert sheet.index("## Borderline cases") > max(
        sheet.index(f"### {r['id']}:") for r in ROWS if not r["borderline"]
    )
    assert "**not verified**" in sheet
