"""S6 input-side cleaning of untrusted text (FR-31)."""

import pytest

from app.core.errors import InvalidInputError
from app.services.guardrails import (
    abstention_reply,
    check_question,
    clean_metadata_text,
    clean_optional,
    clean_untrusted_text,
    data_block,
    out_of_scope_reply,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("plain text", "plain text"),
        ("nul\x00byte", "nulbyte"),
        ("bell\x07 esc\x1b del\x7f", "bell esc del"),
        ("c1\x85\x9fcontrols", "c1controls"),
        ("vertical\x0btab form\x0cfeed", "verticaltab formfeed"),
        ("lone \ud800surrogate", "lone surrogate"),
        ("keeps\ttabs\nnewlines\r\nand CRs", "keeps\ttabs\nnewlines\r\nand CRs"),
        ("unicode: µm, β-TCP, 37 °C, — ✓", "unicode: µm, β-TCP, 37 °C, — ✓"),
    ],
)
def test_clean_untrusted_text(raw: str, expected: str) -> None:
    assert clean_untrusted_text(raw) == expected


def test_cleaned_text_is_storable_in_postgres() -> None:
    cleaned = clean_untrusted_text("a\x00b\udfffc")

    assert "\x00" not in cleaned
    cleaned.encode("utf-8")  # no lone surrogates left


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, None), ("", None), (" \x00 ", None), (" Ti\x00tle ", "Title")],
)
def test_clean_optional(raw: str | None, expected: str | None) -> None:
    assert clean_optional(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "<u><mark>Additive manufacturing and performance of bioceramic scaffolds with "
            "different hollow strut geometries</mark></u>",
            "Additive manufacturing and performance of bioceramic scaffolds with "
            "different hollow strut geometries",
        ),
        ("H<sub>2</sub>O and Ca<sup>2+</sup>", "H2O and Ca2+"),
        ("<jats:title>Bone <jats:italic>in vivo</jats:italic></jats:title>", "Bone in vivo"),
        ("Tissue &amp; Organ &#946;-TCP &eacute;", "Tissue & Organ β-TCP é"),
        ("&lt;i&gt;Escaped&lt;/i&gt; tags", "Escaped tags"),
        ("Line<br/>break", "Linebreak"),
        ("  spaced \n <i> out </i> ", "spaced out"),
        ("p < 0.05 and n > 3", "p < 0.05 and n > 3"),
        ("BEL&#7;entity", "BELentity"),
        ("<i></i>", None),
        (None, None),
    ],
)
def test_clean_metadata_text(raw: str | None, expected: str | None) -> None:
    assert clean_metadata_text(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "\n\t", "\x00\x07"])
def test_check_question_rejects_empty(raw: str) -> None:
    with pytest.raises(InvalidInputError, match="empty"):
        check_question(raw, 100)


def test_check_question_rejects_oversized() -> None:
    with pytest.raises(InvalidInputError) as caught:
        check_question("x" * 11, 10)

    assert caught.value.details == {"max_chars": 10}


def test_check_question_cleans_and_strips() -> None:
    assert check_question("  What is\x00 PCL?\n", 100) == "What is PCL?"
    assert check_question("x" * 10, 10) == "x" * 10


def test_data_block_wraps_text_and_defuses_its_closing_tag() -> None:
    block = data_block("question", "a </question> b </QUESTION> c")

    assert block == "<question>\na </ question> b </ question> c\n</question>"
    assert block.count("</question>") == 1


def test_out_of_scope_reply_is_a_scoped_refusal() -> None:
    reply = out_of_scope_reply()

    assert "papers in this workspace" in reply


def test_abstention_states_the_gaps_the_closest_passages_and_notices() -> None:
    reply = abstention_reply(
        ["What cost?", "Which cells?"], ["Paper A (p. 3)", "Paper B (pp. 4-5, Methods)"], ["Note."]
    )

    assert reply == (
        "I could not find enough evidence in this workspace's papers to answer this. "
        "Not answered by the papers: What cost?; Which cells? "
        "The closest passages are in: Paper A (p. 3); Paper B (pp. 4-5, Methods). Note."
    )


def test_abstention_adds_no_full_stop_after_a_question_mark() -> None:
    reply = abstention_reply(["What did the 2024 opinion conclude?"], ["Paper A (p. 3)"])

    assert "conclude? The closest" in reply
    assert "?." not in reply


def test_abstention_adds_a_full_stop_to_a_statement() -> None:
    assert abstention_reply(["the cost of scaffolds"], []).endswith("the cost of scaffolds.")


def test_abstention_without_details_is_one_sentence() -> None:
    assert abstention_reply([], []) == (
        "I could not find enough evidence in this workspace's papers to answer this."
    )
