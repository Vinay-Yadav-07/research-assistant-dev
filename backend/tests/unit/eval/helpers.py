"""Builders shared by the eval unit tests."""

from uuid import UUID, uuid4

from app.services.retrieval import RetrievedChunk
from eval.dataset import BenchmarkItem, GoldPassage, ItemType


def item(
    id_: str = "test-001",
    *,
    corpus: str = "tissue",
    type_: ItemType = "single",
    gold: tuple[GoldPassage, ...] = (GoldPassage("a.pdf", 3, "porosity was 84%"),),
    verified_by: str = "",
) -> BenchmarkItem:
    answerable = type_ != "unanswerable"
    return BenchmarkItem(
        id=id_,
        split="test",
        corpus=corpus,
        question=f"Question {id_}?",
        answerable=answerable,
        paper=None,
        page=None,
        snippet=None,
        drafted_by="claude",
        verified_by=verified_by,
        type=type_,
        evidence=gold if answerable else (),
    )


def chunk(
    text: str, *, document_id: UUID | None = None, page: int = 1, end: int | None = None
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=document_id or uuid4(),
        document_title="Paper",
        chunk_index=0,
        page_start=page,
        page_end=end or page,
        section=None,
        text=text,
        dense_rank=1,
        lexical_rank=None,
        rrf_score=0.0,
        rerank_score=None,
    )
