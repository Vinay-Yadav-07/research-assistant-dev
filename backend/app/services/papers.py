"""Discover: search free scholarly sources and import open-access PDFs (FR-17, S9, D-077).

A search or import is started by the user on the Discover page, which is their consent for
that external call. It is separate from a QA run's knowledge mode: an imported paper becomes
an ordinary corpus document, uploaded through `DocumentService` with the usual ownership,
duplicate, compatibility, and ingestion rules.
"""

import asyncio
import logging
import re
import time
from typing import get_args
from uuid import UUID, uuid4

import httpx

from app.core.errors import (
    CompatibilityWarningError,
    ExternalServiceError,
    NotFoundError,
    NotOpenAccessError,
    PdfUnavailableError,
    SourceUnavailableError,
)
from app.providers.fetch import PdfFetcher, failure_reason, is_transient
from app.providers.search import DiscoverySource, PaperRecord, ScholarlySearchProvider
from app.schemas.documents import DocumentUploadResult
from app.schemas.papers import PaperSearchResponse, SearchScope
from app.services.compatibility import CompatibilityService
from app.services.documents import DocumentService

logger = logging.getLogger(__name__)

SOURCES: tuple[DiscoverySource, ...] = get_args(DiscoverySource)
# Locations tried per search check and per import; more rarely help.
MAX_PDF_ATTEMPTS = 5
_NON_WORD = re.compile(r"\W+")


async def search_papers(
    search: ScholarlySearchProvider,
    fetcher: PdfFetcher,
    query: str,
    *,
    scope: SearchScope,
    limit: int,
    pdf_check_seconds: float,
    importable_only: bool = False,
) -> PaperSearchResponse:
    """Search the chosen sources concurrently; a failing source leaves partial results.

    With every chosen source down, `ExternalServiceError` is raised. PDF locations are
    checked before results are returned (`verify_pdfs`). With `importable_only`, sources are
    asked for open-access works and papers without a PDF link are left out.
    """
    sources = SOURCES if scope == "all" else (scope,)
    outcomes = await asyncio.gather(
        *(
            search.search(query, limit=limit, source=source, open_access_only=importable_only)
            for source in sources
        ),
        return_exceptions=True,
    )
    found: list[list[PaperRecord]] = []
    unavailable: list[DiscoverySource] = []
    exhausted: list[DiscoverySource] = []
    for source, outcome in zip(sources, outcomes, strict=True):
        if isinstance(outcome, ExternalServiceError):
            logger.warning("Paper search failed at %s: %s", source, outcome.message)
            unavailable.append(source)
            if outcome.details.get("reason") == "quota_exhausted":
                exhausted.append(source)
        elif isinstance(outcome, BaseException):
            raise outcome
        else:
            found.append(outcome)
    if not found:
        raise ExternalServiceError(
            "Paper search is unavailable right now.",
            details={"unavailable": unavailable, "quota_exhausted": exhausted},
        )
    results = await verify_pdfs(merge_results(found), fetcher, budget_seconds=pdf_check_seconds)
    if importable_only:
        results = [paper for paper in results if paper.importable]
    return PaperSearchResponse(results=results, unavailable=unavailable, quota_exhausted=exhausted)


async def verify_pdfs(
    papers: list[PaperRecord], fetcher: PdfFetcher, *, budget_seconds: float
) -> list[PaperRecord]:
    """Check each paper's PDF locations with a ~1 KB request: the first that answers with a
    PDF moves to the front and marks the paper `verified`.

    Many listed open-access PDFs sit behind publisher bot protection, so a listing alone does
    not make a paper importable: locations that permanently fail (403, not a PDF) are dropped,
    and a paper with none left is link only. Locations whose check was inconclusive (timeout,
    5xx) are kept, so the paper stays `unverified`, as does a paper whose check does not finish
    within the shared time budget. arXiv's own PDF links are not checked (`unverified`), to
    keep within arXiv's request limits; arXiv serves them reliably.
    """

    async def check(paper: PaperRecord) -> PaperRecord:
        if paper.source == "arxiv":
            return paper
        kept: list[str] = []
        for url in paper.pdf_urls[:MAX_PDF_ATTEMPTS]:
            result = await fetcher.probe(url)
            if result == "pdf":
                rest = [other for other in paper.pdf_urls if other != url]
                return paper.model_copy(update={"pdf_urls": [url, *rest], "pdf_verified": True})
            if result == "unknown":
                kept.append(url)
        return paper.model_copy(update={"pdf_urls": kept})

    tasks = [asyncio.create_task(check(paper)) for paper in papers]
    if not tasks:
        return []
    done, pending = await asyncio.wait(tasks, timeout=budget_seconds)
    for task in pending:
        task.cancel()
    return [
        task.result() if task in done else paper for task, paper in zip(tasks, papers, strict=True)
    ]


def merge_results(lists: list[list[PaperRecord]]) -> list[PaperRecord]:
    """Interleave the sources' rankings and drop repeats (same DOI or same title).

    Of two copies of a paper, the importable one is kept.
    """
    merged: list[PaperRecord] = []
    index: dict[str, int] = {}
    for rank in range(max(map(len, lists), default=0)):
        for papers in lists:
            if rank >= len(papers):
                continue
            paper = papers[rank]
            keys = _paper_keys(paper)
            seen = next((index[key] for key in keys if key in index), None)
            if seen is None:
                for key in keys:
                    index[key] = len(merged)
                merged.append(paper)
            elif paper.importable and not merged[seen].importable:
                merged[seen] = paper
    return merged


def _paper_keys(paper: PaperRecord) -> list[str]:
    keys = [f"title:{_NON_WORD.sub(' ', paper.title.lower()).strip()}"]
    if paper.doi:
        keys.append(f"doi:{paper.doi.lower()}")
    return keys


class PaperImportService:
    """Downloads a discovered paper's open-access PDF into an owned workspace."""

    def __init__(
        self,
        search: ScholarlySearchProvider,
        fetcher: PdfFetcher,
        documents: DocumentService,
        compatibility: CompatibilityService,
        *,
        download_budget_seconds: float = 120.0,
    ) -> None:
        """`download_budget_seconds` bounds the time spent on all PDF locations together."""
        self._search = search
        self._fetcher = fetcher
        self._documents = documents
        self._compatibility = compatibility
        self._budget = download_budget_seconds

    async def import_paper(
        self,
        user_id: UUID,
        workspace_id: UUID,
        source: DiscoverySource,
        external_id: str,
        *,
        override: bool = False,
    ) -> DocumentUploadResult:
        """Import the paper as an upload would; raises before anything is stored if

        the workspace is not owned (NotFoundError), the source does not answer the paper
        lookup (SourceUnavailableError), the paper is unknown (NotFoundError) or has no PDF
        location (NotOpenAccessError), no location gives a PDF (PdfUnavailableError with
        `reason` and `retryable` in its details), or the PDF looks unrelated without
        `override` (CompatibilityWarningError, FR-22).

        Each stage is logged with an import id, the paper id, timings and outcomes; never
        tokens, user data, or document content.
        """
        log = _StageLog(source, external_id)
        await self._documents.require_workspace(user_id, workspace_id)
        try:
            paper = await self._search.get_paper(source, external_id)
        except ExternalServiceError as error:
            log.stage("lookup", f"failed: {error.message}")
            raise SourceUnavailableError(
                details={"source": source, "reason": error.details.get("reason")}
            ) from error
        log.stage("lookup", "not found" if paper is None else f"{len(paper.pdf_urls)} PDF links")
        if paper is None:
            raise NotFoundError("Paper not found at the source.")
        if not paper.pdf_urls:
            raise NotOpenAccessError(details={"url": paper.url})
        data, pdf_url = await self._download(paper.pdf_urls, log)
        if not override:
            result = await self._compatibility.check(user_id, workspace_id, data)
            log.stage("compatibility", f"compatible={result.compatible} score={result.score}")
            if not result.compatible:
                raise CompatibilityWarningError(
                    details={"score": result.score, "threshold": result.threshold}
                )
        uploaded = await self._documents.upload(
            user_id,
            workspace_id,
            data,
            override=override,
            source="import",
            source_url=paper.url or pdf_url,
        )
        log.stage("upload", f"duplicate={uploaded.duplicate} linked={uploaded.linked}")
        return uploaded

    async def _download(self, urls: list[str], log: "_StageLog") -> tuple[bytes, str]:
        """The first location that gives a PDF, tried in order within the time budget."""
        failures: list[PdfUnavailableError] = []
        attempts: list[dict[str, str]] = []
        try:
            async with asyncio.timeout(self._budget):
                for url in urls[:MAX_PDF_ATTEMPTS]:
                    host = httpx.URL(url).host
                    try:
                        data = await self._fetcher.fetch(url)
                    except PdfUnavailableError as error:
                        log.stage("download", f"{host}: {failure_reason(error)} ({error.message})")
                        failures.append(error)
                        attempts.append({"host": host, "reason": failure_reason(error)})
                        continue
                    log.stage("download", f"{host}: {len(data)} bytes")
                    return data, url
        except TimeoutError:
            log.stage("download", "time budget used up")
            failures.append(PdfUnavailableError(details={"reason": "timeout"}))
            attempts.append({"host": "", "reason": "timeout"})
        transient = next((e for e in failures if is_transient(e)), None)
        reason = failure_reason(transient or failures[0]) if failures else "not_found"
        raise PdfUnavailableError(
            details={"reason": reason, "retryable": transient is not None, "attempts": attempts}
        )


class _StageLog:
    """Logs one import's stages with elapsed milliseconds, under a short import id."""

    def __init__(self, source: str, external_id: str) -> None:
        self._prefix = f"Paper import {uuid4().hex[:8]} ({source}:{external_id[:40]})"
        self._started = time.monotonic()

    def stage(self, name: str, outcome: str) -> None:
        elapsed = round((time.monotonic() - self._started) * 1000)
        logger.info("%s %s after %d ms: %s", self._prefix, name, elapsed, outcome)
