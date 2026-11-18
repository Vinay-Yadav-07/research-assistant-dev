"""Markdown and BibTeX rendering of saved findings (FR-32)."""

from datetime import UTC, datetime
from typing import Any, get_args
from uuid import UUID, uuid4

from app.models.document import Document
from app.models.research import FINDING_TYPES, SavedFinding
from app.schemas.research import FindingType
from app.services.export import cited_document_ids, to_bibtex, to_markdown

DOC_A = uuid4()
DOC_B = uuid4()


def cite(document_id: UUID | None, page: int, quote: str, title: str = "Paper A") -> dict[str, Any]:
    return {
        "source_type": "corpus" if document_id else "web",
        "document_id": str(document_id) if document_id else None,
        "document_title": title,
        "page_start": page,
        "page_end": page,
        "section": "Results",
        "quote": quote,
    }


def finding(type: str, title: str, content: dict[str, Any]) -> SavedFinding:
    return SavedFinding(
        id=uuid4(),
        type=type,
        title=title,
        content_json=content,
        created_at=datetime(2026, 10, 10, tzinfo=UTC),
    )


COMPARISON = {
    "attributes": ["material"],
    "papers": [
        {
            "document_id": str(DOC_A),
            "document_title": "Paper A",
            "cells": [
                {
                    "attribute": "material",
                    "text": "PCL",
                    "reported": True,
                    "citations": [cite(DOC_A, 2, "PCL scaffolds")],
                }
            ],
        },
        {
            "document_id": str(DOC_B),
            "document_title": "Paper B",
            "cells": [
                {
                    "attribute": "material",
                    "text": "Not reported",
                    "reported": False,
                    "citations": [],
                }
            ],
        },
    ],
}

SYNTHESIS = {
    "topic": "porosity",
    "themes": [
        {
            "title": "Pore size",
            "claims": [
                {
                    "text": "Both report large pores.",
                    "document_ids": [str(DOC_A), str(DOC_B)],
                    "citations": [
                        cite(DOC_A, 3, "pores of 300 µm"),
                        cite(DOC_B, 5, "400 µm pores", "Paper B"),
                    ],
                },
                {
                    "text": "Paper A repeats it.",
                    "document_ids": [str(DOC_A)],
                    "citations": [cite(DOC_A, 3, "pores of 300 µm")],
                },
            ],
        }
    ],
}

CONTRADICTION = {
    "topic": "stiffness",
    "contradictions": [
        {
            "finding_a": {"text": "Stiffer helps.", "citations": [cite(DOC_A, 4, "stiffer")]},
            "finding_b": {"text": "Softer helps.", "citations": [cite(DOC_B, 6, "softer")]},
            "label": "context_dependent",
            "context_note": "Different cell types.",
            "nli_score": 0.9,
        }
    ],
}


def document(**fields: Any) -> Document:
    return Document(**{"id": uuid4(), "title": "A study", **fields})


def test_finding_type_matches_the_database_constraint() -> None:
    assert set(get_args(FindingType)) == set(FINDING_TYPES)


def test_comparison_lists_each_paper_with_cited_cells() -> None:
    text = to_markdown("Scaffolds", [finding("comparison", "Materials", COMPARISON)])

    assert text.startswith("# Saved findings — Scaffolds\n")
    assert "## Materials" in text
    assert "_comparison · 2026-10-10_" in text
    assert "### Paper A\n- **material:** PCL [1]" in text
    assert "### Paper B\n- **material:** Not reported\n" in text
    assert '1. Paper A, p. 2, Results — "PCL scaffolds"' in text


def test_synthesis_reuses_the_number_of_a_repeated_citation() -> None:
    text = to_markdown("W", [finding("answer", "Porosity", SYNTHESIS)])

    assert "**Topic:** porosity" in text
    assert "### Pore size" in text
    assert "- Both report large pores. [1][2]" in text
    assert "- Paper A repeats it. [1]" in text
    assert "3." not in text


def test_contradiction_shows_both_findings_then_the_context() -> None:
    text = to_markdown("W", [finding("contradiction", "Stiffness", CONTRADICTION)])

    a, b = text.index("- Stiffer helps. [1]"), text.index("- Softer helps. [2]")
    assert a < b < text.index("_Label: context_dependent_") < text.index("Different cell types.")


def test_each_finding_numbers_its_own_references() -> None:
    text = to_markdown(
        "W", [finding("comparison", "One", COMPARISON), finding("answer", "Two", SYNTHESIS)]
    )

    second = text[text.index("## Two") :]
    assert "- Both report large pores. [1][2]" in second


def test_no_findings_is_just_the_heading() -> None:
    assert to_markdown("W", []).strip() == "# Saved findings — W"


def test_cited_documents_are_unique_in_order_and_skip_external_sources() -> None:
    web = {"text": "From the web.", "citations": [cite(None, 1, "web", "Blog")]}
    findings = [finding("answer", "T", SYNTHESIS), finding("answer", "W", web)]

    assert cited_document_ids(findings) == [DOC_A, DOC_B]


def test_bibtex_entry_has_all_known_fields_escaped() -> None:
    doc = document(
        title="Gels {and} 50% more & co_polymers",
        authors=["Jane Smith", "Li Wei"],
        year=2023,
        venue="Biomaterials",
        doi="10.1/x_y",
    )

    assert to_bibtex([doc]) == (
        "@article{smith2023,\n"
        "  title = {Gels \\{and\\} 50\\% more \\& co\\_polymers},\n"
        "  author = {Jane Smith and Li Wei},\n"
        "  year = {2023},\n"
        "  journal = {Biomaterials},\n"
        "  doi = {10.1/x\\_y}\n"
        "}\n"
    )


def test_bibtex_without_metadata_is_a_misc_entry_keyed_by_id() -> None:
    doc = document(title=None, authors=None, year=None, venue=None, doi=None)

    assert to_bibtex([doc]) == f"@misc{{doc{str(doc.id)[:8]},\n  title = {{Untitled}}\n}}\n"


def test_bibtex_keys_handle_surname_forms_and_collisions() -> None:
    docs = [
        document(authors=["Müller, Anna"], year=2020),
        document(authors=["Anna Müller"], year=2020),
        document(authors=["Ng"], year=None),
    ]

    keys = [entry.split("{")[1].split(",")[0] for entry in to_bibtex(docs).split("\n\n")]
    assert keys == ["muller2020a", "muller2020b", "ng"]
