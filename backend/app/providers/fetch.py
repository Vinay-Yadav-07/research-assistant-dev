"""Downloading open-access PDFs for paper import (FR-17, SRS §10)."""

from typing import Literal, Protocol

from app.core.errors import PdfUnavailableError

# Why a PDF location failed; carried in `PdfUnavailableError.details["reason"]`.
FailureReason = Literal[
    "timeout",  # no answer within the time limit
    "network",  # connection refused, reset, DNS failure
    "incomplete",  # the connection closed before the whole body arrived
    "server_error",  # 429 or 5xx
    "access_denied",  # 401, 403, 451: the host refuses automated downloads
    "not_found",  # 404, 410
    "http_error",  # any other unexpected status
    "not_pdf",  # the body is not a PDF (e.g. a landing or bot-check page)
    "too_large",  # over the upload size limit
    "redirects",  # too many redirects or a redirect without a target
    "unsafe",  # not a public http(s) destination (SSRF guard)
]
# Failures that may succeed on another try; every other reason is permanent.
TRANSIENT_REASONS: frozenset[str] = frozenset({"timeout", "network", "incomplete", "server_error"})

# "pdf": the location answered with a PDF; "failed": it permanently did not;
# "unknown": a transient failure, so it may still work.
ProbeResult = Literal["pdf", "failed", "unknown"]


def failure_reason(error: PdfUnavailableError) -> str:
    """The error's `FailureReason`, or "http_error" when it carries none."""
    reason = error.details.get("reason")
    return reason if isinstance(reason, str) else "http_error"


def is_transient(error: PdfUnavailableError) -> bool:
    """True if trying the same location again may succeed."""
    return failure_reason(error) in TRANSIENT_REASONS


class PdfFetcher(Protocol):
    """Downloads a PDF from an untrusted URL."""

    async def fetch(self, url: str) -> bytes:
        """The PDF's bytes; raises `PdfUnavailableError` with a `reason` in its details."""
        ...

    async def probe(self, url: str) -> ProbeResult:
        """Whether the URL answers with the start of a PDF (a cheap check before import)."""
        ...
