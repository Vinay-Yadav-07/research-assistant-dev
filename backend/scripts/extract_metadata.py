"""Extract metadata from real papers with the live DOI lookup and print a report (task #5).

Run from `backend/`:
    uv run python -m scripts.extract_metadata --papers-dir scripts/data/papers

Calls Crossref (and OpenAlex as fallback). CONTACT_EMAIL from `backend/.env` is sent for their
polite pool when set; without it the requests carry no email.
"""

import argparse
import asyncio
from pathlib import Path

from app.core.config import get_settings
from app.providers.live.scholarly import LiveScholarlySearch
from app.providers.local.pdf_parser import PyMuPDF4LLMParser
from app.services.document_metadata import MetadataService, doi_candidates

# DOIs of the benchmark papers, checked against Crossref. Advancements resolves as "...t0vm9";
# "...t0vm91" (a footnote digit run into the DOI) is not registered.
EXPECTED_DOIS = {
    "Advancements_in_Surface_Modification.pdf": "10.26434/chemrxiv-2023-t0vm9",
    "Hydrogels_for_Biomedical_Applications.pdf": "10.26434/chemrxiv.12924686.v1",
    "Tissue_Regeneration.pdf": "10.26434/chemrxiv-2025-qkt7j",
    "Architected_Hydrogels_for_Functional_Tissue.pdf": "10.26434/chemrxiv-2022-jhfgl",
    "Plasmonic_Nanomaterials.pdf": "10.1016/j.jare.2021.11.006",
    "Repurposing_biomedical_muscle_tissue_engineering.pdf": "10.1016/j.tibtech.2023.02.002",
}


async def run(papers: dict[str, bytes]) -> None:
    settings = get_settings()
    parser = PyMuPDF4LLMParser(min_text_chars_per_page=settings.pdf_min_text_chars_per_page)
    search = LiveScholarlySearch(
        contact_email=settings.contact_email, timeout_seconds=settings.scholarly_timeout_seconds
    )
    service = MetadataService(search, max_candidates=settings.doi_max_candidates)
    for name, data in papers.items():
        parsed = await parser.parse(data)
        candidates = [c.value for c in doi_candidates(parsed.pages)]
        metadata = await service.extract(parsed)
        expected = EXPECTED_DOIS.get(name)
        check = (
            ""
            if expected is None
            else (" ✓" if metadata.doi == expected else f" ✗ expected {expected}")
        )
        authors = ", ".join(metadata.authors[:3]) + (" et al." if len(metadata.authors) > 3 else "")
        print(f"\n{name}")
        print(f"  candidates: {candidates}")
        print(f"  doi:     {metadata.doi}{check}")
        print(f"  source:  {metadata.source}")
        print(f"  title:   {metadata.title}")
        print(f"  authors: {authors or '-'} ({len(metadata.authors)})")
        print(f"  year:    {metadata.year}   venue: {metadata.venue}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--papers-dir", default="scripts/data/papers")
    args = parser.parse_args()
    papers = {path.name: path.read_bytes() for path in sorted(Path(args.papers_dir).glob("*.pdf"))}
    asyncio.run(run(papers))


if __name__ == "__main__":
    main()
