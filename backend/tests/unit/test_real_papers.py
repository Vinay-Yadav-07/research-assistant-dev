"""Parser + cleanup + chunker on the real papers in `scripts/data/papers/` (git-ignored).

Skipped when the folder is absent (CI). Token counts use whitespace words so the test needs no
model download; `scripts/parse_papers.py` reports real tokenizer numbers.
"""

import asyncio
from pathlib import Path

import pymupdf
import pytest

from app.providers.local.pdf_parser import PyMuPDF4LLMParser
from app.services.chunking import chunk_pages
from app.services.page_cleanup import remove_repeated_lines

PAPERS_DIR = Path(__file__).resolve().parents[2] / "scripts" / "data" / "papers"
PAPERS = sorted(PAPERS_DIR.glob("*.pdf")) if PAPERS_DIR.is_dir() else []

pytestmark = pytest.mark.skipif(not PAPERS, reason=f"no papers in {PAPERS_DIR}")


@pytest.mark.parametrize("path", PAPERS, ids=[path.name for path in PAPERS])
def test_real_paper_parses_and_chunks(path: Path) -> None:
    data = path.read_bytes()
    with pymupdf.open(stream=data, filetype="pdf") as document:  # type: ignore[no-untyped-call]
        expected_pages = document.page_count

    parsed = asyncio.run(PyMuPDF4LLMParser(min_text_chars_per_page=100).parse(data))
    cleaned = remove_repeated_lines(
        parsed.pages, min_pages=3, min_page_fraction=0.5, max_line_chars=200
    )
    chunks = chunk_pages(
        cleaned.pages,
        count_tokens=lambda text: len(text.split()),
        min_tokens=250,
        max_tokens=320,
        overlap_ratio=0.12,
        merge_below_tokens=60,
        hard_max_tokens=360,
    )

    assert [page.page_number for page in parsed.pages] == list(range(1, expected_pages + 1))
    assert len(chunks) >= expected_pages
    assert len({chunk.section for chunk in chunks}) > 3
    for chunk in chunks:
        assert 1 <= chunk.page_start <= chunk.page_end <= expected_pages
        assert chunk.token_count <= 360
    # The NIH per-page footer ("... Author manuscript; available in PMC ...") is boilerplate.
    assert not any("available in pmc" in chunk.text.lower() for chunk in chunks)
