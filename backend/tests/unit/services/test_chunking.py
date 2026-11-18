import hashlib

import pytest
from pydantic import ValidationError

from app.providers.parser import ParsedPage
from app.services.chunking import ChunkDraft, chunk_pages

MIN, MAX = 35, 45  # word-count tokens; the real defaults are 350-450 model tokens
MERGE_BELOW, HARD_MAX = 8, 51  # real defaults: 80 and 510


def words(text: str) -> int:
    return len(text.split())


def sentence(tag: str, n: int = 6) -> str:
    """A sentence of `n` words."""
    return " ".join([tag.capitalize()] + [f"{tag}{i}" for i in range(1, n - 1)] + [f"{tag}end."])


def paragraph(tag: str, sentences: int) -> str:
    return " ".join(sentence(f"{tag}s{i}") for i in range(sentences))


def chunk(
    *markdown: str, overlap: float = 0.12, merge_below: int = 0, hard_max: int = HARD_MAX
) -> list[ChunkDraft]:
    pages = [ParsedPage(page_number=i, markdown=m) for i, m in enumerate(markdown, start=1)]
    return chunk_pages(
        pages,
        count_tokens=words,
        min_tokens=MIN,
        max_tokens=MAX,
        overlap_ratio=overlap,
        merge_below_tokens=merge_below,
        hard_max_tokens=hard_max,
    )


def test_chunks_stay_within_bounds_and_overlap() -> None:
    chunks = chunk("# Results\n\n" + paragraph("a", 30))

    assert len(chunks) > 3
    assert all(c.token_count <= MAX for c in chunks)
    assert all(c.token_count >= MIN for c in chunks[:-1])
    for previous, current in zip(chunks, chunks[1:], strict=False):
        first_sentence = current.text.split(". ")[0] + "."
        assert first_sentence in previous.text  # ~12% overlap = one 6-word sentence here
        assert words(first_sentence) <= int(0.12 * (MIN + MAX) / 2)


def test_no_overlap_when_ratio_is_zero() -> None:
    chunks = chunk("# Results\n\n" + paragraph("a", 30), overlap=0)

    text = " ".join(c.text for c in chunks)
    assert words(text) == 30 * 6


def test_overlap_falls_back_to_tail_words_of_a_long_sentence() -> None:
    long = sentence("b", 40)
    chunks = chunk(long + " " + sentence("c", 20))

    assert len(chunks) == 2
    tail = chunks[1].text[: chunks[1].text.index(" C c1")]
    assert long.endswith(tail)
    assert 0 < words(tail) <= int(0.12 * (MIN + MAX) / 2)


def test_sections_come_from_headings_and_carry_across_pages() -> None:
    chunks = chunk(
        "Preamble text here.\n\n# Introduction\n\n" + paragraph("i", 2),
        paragraph("j", 2) + "\n\n## Methods\n\n" + paragraph("m", 2),
    )

    assert [(c.section, c.page_start, c.page_end) for c in chunks] == [
        (None, 1, 1),
        ("Introduction", 1, 2),
        ("Methods", 2, 2),
    ]


def test_chunks_never_span_sections() -> None:
    chunks = chunk("# A\n\n" + paragraph("a", 3) + "\n\n# B\n\n" + paragraph("b", 3))

    assert [c.section for c in chunks] == ["A", "B"]
    assert "As0" not in chunks[1].text


def test_split_title_lines_are_joined_and_markup_stripped() -> None:
    chunks = chunk(
        "## **Engineering Polymeric Hydrogels for**\n## **Tissue Regeneration**\n\nBody text."
    )

    assert chunks[0].section == "Engineering Polymeric Hydrogels for Tissue Regeneration"


def test_overlong_heading_is_treated_as_text() -> None:
    heading = "# " + "word " * 60
    chunks = chunk(heading + "\n\nBody text.")

    assert chunks[0].section is None
    assert chunks[0].text.startswith("# word")


def test_paragraphs_keep_breaks_and_lines_are_joined() -> None:
    chunks = chunk("First line\nwraps here.\n\nSecond paragraph.")

    assert chunks[0].text == "First line wraps here.\n\nSecond paragraph."


def test_sentence_longer_than_max_is_split() -> None:
    chunks = chunk(sentence("z", 100), overlap=0)

    assert [c.token_count for c in chunks] == [45, 45, 10]


def test_hash_index_and_determinism() -> None:
    first = chunk("# A\n\n" + paragraph("a", 20))
    second = chunk("# A\n\n" + paragraph("a", 20))

    assert first == second
    assert [c.chunk_index for c in first] == list(range(len(first)))
    for c in first:
        assert c.content_hash == hashlib.sha256(c.text.encode()).hexdigest()


def test_empty_pages_produce_no_chunks() -> None:
    assert chunk("", "   ", "# Only a heading") == []


def test_page_range_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        ChunkDraft(
            chunk_index=0,
            page_start=3,
            page_end=2,
            section=None,
            text="x",
            token_count=1,
            content_hash="h",
        )


# --- merging short chunks ---


def test_short_last_chunk_merges_into_the_previous_without_duplicating_overlap() -> None:
    # 8 six-word sentences = 48 words: 7 sentences (42), then 4 overlap words + 1 sentence.
    without = chunk("# A\n\n" + paragraph("a", 8))
    assert [c.token_count for c in without] == [42, 10]

    merged = chunk("# A\n\n" + paragraph("a", 8), merge_below=MERGE_BELOW + 5)

    assert len(merged) == 1
    assert merged[0].text == paragraph("a", 8)  # the overlap words are not repeated


def test_short_chunk_merges_into_the_next_in_its_section() -> None:
    # A 4-word sentence, then a 44-word one that cannot join it within MAX.
    text = "Tiny w2 w3 w4. " + sentence("b", 44)
    without = chunk(text, overlap=0)
    assert [c.token_count for c in without] == [4, 44]

    merged = chunk(text, overlap=0, merge_below=MERGE_BELOW)

    assert [c.token_count for c in merged] == [48]
    assert merged[0].text.startswith("Tiny w2 w3 w4. B ")


def test_merge_never_crosses_sections() -> None:
    chunks = chunk(
        "# A\n\nShort a.\n\n# B\n\n" + paragraph("b", 3) + "\n\n# C\n\nShort c.",
        merge_below=MERGE_BELOW,
    )

    assert [(c.section, c.token_count) for c in chunks] == [("A", 2), ("B", 18), ("C", 2)]


def test_merge_respects_the_hard_maximum() -> None:
    text = "Tiny w2 w3 w4. " + sentence("b", 44)

    chunks = chunk(text, overlap=0, merge_below=MERGE_BELOW, hard_max=47)

    assert [c.token_count for c in chunks] == [4, 44]


def test_falls_back_to_previous_when_next_is_too_long() -> None:
    # 40 words, then a 4-word sentence, then a 44-word sentence (same section, no overlap).
    text = sentence("a", 40) + " Tiny w2 w3 w4. " + sentence("b", 44)
    assert [c.token_count for c in chunk(text, overlap=0)] == [44, 44]  # tiny packs with a

    text = sentence("a", 42) + " Tiny w2 w3 w4. " + sentence("b", 44)
    assert [c.token_count for c in chunk(text, overlap=0)] == [42, 4, 44]

    chunks = chunk(text, overlap=0, merge_below=MERGE_BELOW, hard_max=47)

    assert [c.token_count for c in chunks] == [46, 44]
    assert chunks[0].text.endswith("Tiny w2 w3 w4.")


def test_zero_threshold_disables_merging() -> None:
    assert [c.token_count for c in chunk("# A\n\n" + paragraph("a", 8))] == [42, 10]
