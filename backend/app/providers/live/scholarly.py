"""Scholarly metadata over HTTP: DOI lookup (FR-04, D-045) and Discover search (D-077)."""

import asyncio
import html
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
from defusedxml import ElementTree

from app.core.errors import ExternalServiceError, ProviderConfigurationError
from app.providers.rate_limit import RateLimiter
from app.providers.search import DiscoverySource, PaperRecord, ScholarlySearchProvider

CROSSREF_URL = "https://api.crossref.org"
OPENALEX_URL = "https://api.openalex.org"
ARXIV_URL = "https://export.arxiv.org/api/query"
OPENALEX_FIELDS = (
    "id,doi,title,display_name,publication_year,authorships,primary_location,"
    "best_oa_location,locations,abstract_inverted_index,cited_by_count"
)
# arXiv's API rejects long boolean queries; more words rarely help a relevance search.
ARXIV_MAX_TERMS = 12
_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"
# New-style (2301.01234v2) and old-style (hep-th/9901001) arXiv ids.
ARXIV_ID = re.compile(r"(\d{4}\.\d{4,5}|[a-z][a-z.-]*/\d{7})(v\d+)?", re.IGNORECASE)
OPENALEX_ID = re.compile(r"(?:https://openalex\.org/)?(W\d+)", re.IGNORECASE)
_WORDS = re.compile(r"\w+")
# arXiv ANDs every term and indexes no stopwords, so one of these empties the result list.
ARXIV_STOPWORDS = frozenset(
    [
        "a",
        "all",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "how",
        "in",
        "is",
        "it",
        "not",
        "of",
        "on",
        "or",
        "than",
        "that",
        "the",
        "this",
        "to",
        "was",
        "what",
        "when",
        "which",
        "with",
        "you",
        "your",
    ]
)
USER_AGENT = "research-assistant/0.1"
# Preprint servers whose Crossref records have no container title.
PREPRINT_SERVERS = {
    "10.26434": "ChemRxiv",
    "10.1101": "bioRxiv",
    "10.48550": "arXiv",
    "10.21203": "Research Square",
    "10.20944": "Preprints.org",
    "10.31219": "OSF Preprints",
}
# Answers worth one more try (SRS §10.1: at most 2 retries); others fail at once.
TRANSIENT_STATUSES = {429, 500, 502, 503, 504}
# A 429 asking to wait longer than this is a used-up quota (OpenAlex sends hours): not retried.
MAX_RETRY_AFTER_SECONDS = 5.0
_TAGS = re.compile(r"<[^>]+>")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Retry:
    """Bounded retries for transient failures; `before` runs ahead of every attempt."""

    attempts: int = 3
    backoff_seconds: float = 0.5
    before: Callable[[], Awaitable[object]] | None = None


# DOI lookups during ingestion fall back to the LLM, so they are not retried.
NO_RETRY = Retry(attempts=1)
_SPACES = re.compile(r"\s+")


def user_agent(contact_email: str | None) -> str:
    """The polite-pool User-Agent (Crossref, OpenAlex and arXiv ask for a contact)."""
    return f"{USER_AGENT} (mailto:{contact_email})" if contact_email else USER_AGENT


class LiveScholarlySearch(ScholarlySearchProvider):
    """Crossref first, OpenAlex as fallback.

    `get_by_doi` returns None only when every source answered "not found"; if a source failed and
    none found the DOI, it raises `ExternalServiceError`, so callers can tell "wrong DOI" from
    "lookup unavailable".
    """

    def __init__(
        self,
        *,
        contact_email: str | None,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
        arxiv_limiter: RateLimiter | None = None,
        discover_timeout_seconds: float | None = None,
        retry_backoff_seconds: float = 0.5,
        openalex_api_key: str | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """`timeout_seconds` is for DOI lookups during ingestion; Discover's search and paper
        lookups use `discover_timeout_seconds` (OpenAlex searches sometimes take over 5 s) and
        retry a timeout, network error, 429 or 5xx once. `arxiv_limiter` spaces arXiv calls as
        its API terms ask (one every 3 s), retries included.

        `openalex_api_key` (free, 10x the keyless daily budget) is sent to OpenAlex only, in the
        `Authorization` header so it never appears in URLs or logs. When OpenAlex answers a
        search with a used-up quota, searches there are paused until its `Retry-After`; single
        paper lookups cost no credits and continue."""
        self._contact_email = contact_email
        self._timeout_seconds = timeout_seconds
        self._discover_timeout = discover_timeout_seconds or timeout_seconds
        self._transport = transport
        self._arxiv_limiter = arxiv_limiter
        self._retry = Retry(attempts=2, backoff_seconds=retry_backoff_seconds)
        self._openalex_api_key = openalex_api_key
        self._clock = clock
        self._openalex_search_paused_until = 0.0

    async def get_by_doi(self, doi: str) -> PaperRecord | None:
        doi = doi.strip().lower()
        failures: list[str] = []
        async with self._client() as client:
            for source, lookup in (("crossref", self._crossref), ("openalex", self._openalex)):
                try:
                    record = await lookup(client, doi)
                except ExternalServiceError as error:
                    failures.append(f"{source}: {error.message}")
                    continue
                if record is not None:
                    return record
        if failures:
            raise ExternalServiceError(
                "DOI lookup is unavailable.", details={"doi": doi, "failures": failures}
            )
        return None

    async def search(
        self, query: str, *, limit: int, source: DiscoverySource, open_access_only: bool = False
    ) -> list[PaperRecord]:
        """Raises `ExternalServiceError` when the source fails; malformed records are skipped."""
        async with self._client(self._discover_timeout) as client:
            if source == "arxiv":
                words = [
                    word for word in _WORDS.findall(query) if word.lower() not in ARXIV_STOPWORDS
                ]
                terms = words[:ARXIV_MAX_TERMS]
                if not terms:
                    return []
                params = {
                    "search_query": " AND ".join(f"all:{term}" for term in terms),
                    "max_results": str(limit),
                    "sortBy": "relevance",
                }
                return (await self._arxiv(client, params))[:limit]
            params = {
                **self._params(),
                "search": query,
                "per-page": str(limit),
                "select": OPENALEX_FIELDS,
            }
            if open_access_only:
                params["filter"] = "open_access.is_oa:true"
            wait = self._openalex_search_paused_until - self._clock()
            if wait > 0:
                raise quota_exhausted(wait)
            try:
                data = (
                    await _get_json(
                        client,
                        f"{OPENALEX_URL}/works",
                        params,
                        self._retry,
                        headers=self._openalex_headers(),
                    )
                    or {}
                )
            except ExternalServiceError as error:
                if error.details.get("reason") == "quota_exhausted":
                    pause = float(error.details.get("retry_after_seconds") or 0)
                    self._openalex_search_paused_until = self._clock() + pause
                raise
            results = data.get("results")
            works = results if isinstance(results, list) else []
            records = (_openalex_record(work) for work in works if isinstance(work, dict))
            return [record for record in records if record is not None][:limit]

    async def get_paper(self, source: DiscoverySource, external_id: str) -> PaperRecord | None:
        """None for an unknown or malformed id; ids are validated before any request."""
        async with self._client(self._discover_timeout) as client:
            if source == "arxiv":
                match = ARXIV_ID.fullmatch(external_id.strip())
                if match is None:
                    return None
                records = await self._arxiv(client, {"id_list": match.group(0)})
                return records[0] if records else None
            match = OPENALEX_ID.fullmatch(external_id.strip())
            if match is None:
                return None
            work = await _get_json(
                client,
                f"{OPENALEX_URL}/works/{match.group(1).upper()}",
                self._params(),
                self._retry,
                headers=self._openalex_headers(),
            )
            return None if work is None else _openalex_record(work)

    async def related(self, doi: str, *, limit: int) -> list[PaperRecord]:
        raise _later("related papers")

    def _client(self, timeout: float | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers={"User-Agent": user_agent(self._contact_email)},
            timeout=timeout or self._timeout_seconds,
            transport=self._transport,
            follow_redirects=True,
        )

    def _openalex_headers(self) -> dict[str, str]:
        if self._openalex_api_key is None:
            return {}
        return {"Authorization": f"Bearer {self._openalex_api_key}"}

    def _params(self) -> dict[str, str]:
        return {"mailto": self._contact_email} if self._contact_email else {}

    async def _crossref(self, client: httpx.AsyncClient, doi: str) -> PaperRecord | None:
        data = await _get_json(
            client, f"{CROSSREF_URL}/works/{quote(doi, safe='/')}", self._params()
        )
        if data is None:
            return None
        message = data.get("message")
        if not isinstance(message, dict):
            raise ExternalServiceError("Crossref returned an unexpected response.")
        return _from_crossref(message, doi)

    async def _openalex(self, client: httpx.AsyncClient, doi: str) -> PaperRecord | None:
        url = f"{OPENALEX_URL}/works/doi:{quote(doi, safe='/')}"
        data = await _get_json(client, url, self._params(), headers=self._openalex_headers())
        return None if data is None else _from_openalex(data, doi)

    async def _arxiv(self, client: httpx.AsyncClient, params: dict[str, str]) -> list[PaperRecord]:
        limiter = self._arxiv_limiter
        retry = Retry(
            attempts=self._retry.attempts,
            backoff_seconds=self._retry.backoff_seconds,
            before=(lambda: limiter.acquire(0)) if limiter is not None else None,
        )
        response = await _get(client, ARXIV_URL, params, retry)
        if response is None:
            return []
        try:
            root = ElementTree.fromstring(response.content)
        except Exception as error:  # defusedxml raises several parse and safety errors
            raise ExternalServiceError("arXiv returned invalid XML.") from error
        records = (_arxiv_record(entry) for entry in root.iter(f"{_ATOM}entry"))
        return [record for record in records if record is not None]


def quota_exhausted(retry_after: float | None) -> ExternalServiceError:
    """A used-up daily quota; `retry_after_seconds` is how long the source asked us to wait."""
    return ExternalServiceError(
        "The source's request quota is used up.",
        details={"reason": "quota_exhausted", "retry_after_seconds": retry_after},
    )


def _retry_after(response: httpx.Response) -> float | None:
    """`Retry-After` in seconds; None when absent, an HTTP date counts as long."""
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        return float("inf")


async def _get(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, str],
    retry: Retry = NO_RETRY,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response | None:
    """The 200 response, None on 404, or ExternalServiceError for anything else.

    Timeouts, network errors, 429 and 5xx are tried again up to `retry.attempts` in total;
    other statuses fail at once. A 429 waits for a short `Retry-After`; a long one (a used-up
    quota) fails at once with reason `quota_exhausted`.
    """
    delay = 0.0
    for attempt in range(retry.attempts):
        if attempt:
            await asyncio.sleep(max(retry.backoff_seconds * 2 ** (attempt - 1), delay))
        if retry.before is not None:
            await retry.before()
        try:
            response = await client.get(url, params=params, headers=headers)
        except httpx.TimeoutException as error:
            failure = ExternalServiceError("Timed out.", details={"reason": "timeout"})
            failure.__cause__ = error
        except httpx.HTTPError as error:
            failure = ExternalServiceError(
                f"Request failed: {type(error).__name__}.", details={"reason": "network"}
            )
            failure.__cause__ = error
        else:
            if response.status_code == httpx.codes.NOT_FOUND:
                return None
            if response.status_code == httpx.codes.OK:
                return response
            if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                wait = _retry_after(response)
                if wait is not None and wait > MAX_RETRY_AFTER_SECONDS:
                    raise quota_exhausted(wait)
                delay = wait or 0.0
            failure = ExternalServiceError(
                f"HTTP {response.status_code}.", details={"status": response.status_code}
            )
            if response.status_code not in TRANSIENT_STATUSES:
                raise failure
        logger.info(
            "Scholarly request to %s failed (attempt %d/%d): %s",
            httpx.URL(url).host,
            attempt + 1,
            retry.attempts,
            failure.message,
        )
    raise failure


async def _get_json(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, str],
    retry: Retry = NO_RETRY,
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """The JSON body, None on 404, or ExternalServiceError for anything else."""
    response = await _get(client, url, params, retry, headers=headers)
    if response is None:
        return None
    try:
        data = response.json()
    except ValueError as error:
        raise ExternalServiceError("Invalid JSON.") from error
    if not isinstance(data, dict):
        raise ExternalServiceError("Unexpected JSON.")
    return data


def _from_crossref(message: dict[str, Any], doi: str) -> PaperRecord:
    authors = []
    for author in message.get("author") or []:
        name = author.get("name") or " ".join(
            part for part in (author.get("given"), author.get("family")) if part
        )
        if name:
            authors.append(_text(name))
    year = None
    for field in ("issued", "published", "posted", "created"):
        parts = (message.get(field) or {}).get("date-parts") or [[None]]
        if parts and parts[0] and isinstance(parts[0][0], int):
            year = parts[0][0]
            break
    record_doi = str(message.get("DOI") or doi).lower()
    institutions = [
        item.get("name") for item in message.get("institution") or [] if item.get("name")
    ]
    venue = (
        _first(message.get("container-title"))
        or _first(institutions)
        or _preprint_server(record_doi)
    )
    return PaperRecord(
        source="crossref",
        external_id=record_doi,
        doi=record_doi,
        title=_text(_first(message.get("title")) or ""),
        authors=authors,
        year=year,
        venue=_text(venue) if venue else None,
        url=message.get("URL"),
    )


def _from_openalex(work: dict[str, Any], doi: str) -> PaperRecord:
    authors = [
        _text(item["author"]["display_name"])
        for item in work.get("authorships") or []
        if (item.get("author") or {}).get("display_name")
    ]
    source = ((work.get("primary_location") or {}).get("source") or {}).get("display_name")
    record_doi = str(work.get("doi") or doi).lower().removeprefix("https://doi.org/")
    year = work.get("publication_year")
    return PaperRecord(
        source="openalex",
        external_id=str(work.get("id") or record_doi),
        doi=record_doi,
        title=_text(work.get("title") or work.get("display_name") or ""),
        authors=authors,
        year=year if isinstance(year, int) else None,
        venue=_text(source) if source else _preprint_server(record_doi),
        url=work.get("doi"),
    )


def _openalex_record(work: dict[str, Any]) -> PaperRecord | None:
    """A Discover result from an OpenAlex work; None without an id or a title."""
    match = OPENALEX_ID.fullmatch(str(work.get("id") or ""))
    title = work.get("title") or work.get("display_name")
    if match is None or not isinstance(title, str) or not _text(title):
        return None
    doi = work.get("doi")
    doi = doi.lower().removeprefix("https://doi.org/") if isinstance(doi, str) else None
    authors = [
        _text(name)
        for item in _list(work.get("authorships"))
        if isinstance(name := (_dict(_dict(item).get("author"))).get("display_name"), str)
    ]
    primary = _dict(work.get("primary_location"))
    venue = _dict(primary.get("source")).get("display_name")
    year = work.get("publication_year")
    citations = work.get("cited_by_count")
    landing = primary.get("landing_page_url")
    return PaperRecord(
        source="openalex",
        external_id=match.group(1).upper(),
        doi=doi,
        title=_text(title),
        authors=[name for name in authors if name],
        year=year if isinstance(year, int) else None,
        venue=_text(venue) if isinstance(venue, str) else (_preprint_server(doi) if doi else None),
        abstract=_abstract(work.get("abstract_inverted_index")),
        url=_http_url(work.get("doi"))
        or _http_url(landing)
        or f"https://openalex.org/{match.group(1)}",
        pdf_urls=_openalex_pdfs(work),
        citation_count=citations if isinstance(citations, int) else None,
    )


def _openalex_pdfs(work: dict[str, Any]) -> list[str]:
    """PDF URLs of open-access locations, best location first, without duplicates.

    Every location is examined, not only `best_oa_location`; a location without `is_oa` or
    with only a landing page gives no PDF.
    """
    locations = [work.get("best_oa_location"), *_list(work.get("locations"))]
    urls: list[str] = []
    for location in map(_dict, locations):
        url = _http_url(location.get("pdf_url"))
        if location.get("is_oa") is True and url and url not in urls:
            urls.append(url)
    return urls


def _abstract(index: object) -> str | None:
    """Plain text from OpenAlex's inverted index ({word: [positions]})."""
    if not isinstance(index, dict):
        return None
    words: dict[int, str] = {}
    for word, positions in index.items():
        for position in _list(positions):
            if isinstance(word, str) and isinstance(position, int):
                words[position] = word
    return _text(" ".join(words[key] for key in sorted(words))) or None


def _arxiv_record(entry: Any) -> PaperRecord | None:
    """A Discover result from an arXiv Atom entry; None for error entries or bad ids."""
    entry_id = (entry.findtext(f"{_ATOM}id") or "").strip()
    match = ARXIV_ID.fullmatch(entry_id.rpartition("/abs/")[2])
    title = _text(entry.findtext(f"{_ATOM}title") or "")
    if match is None or not title:
        return None
    arxiv_id = match.group(0)
    published = (entry.findtext(f"{_ATOM}published") or "")[:4]
    doi = (entry.findtext(f"{_ARXIV}doi") or "").strip().lower() or None
    journal = _text(entry.findtext(f"{_ARXIV}journal_ref") or "")
    authors = [
        _text(author.findtext(f"{_ATOM}name") or "") for author in entry.findall(f"{_ATOM}author")
    ]
    return PaperRecord(
        source="arxiv",
        external_id=arxiv_id,
        doi=doi,
        title=title,
        authors=[name for name in authors if name],
        year=int(published) if published.isdigit() else None,
        venue=journal or "arXiv",
        abstract=_text(entry.findtext(f"{_ATOM}summary") or "") or None,
        url=f"https://arxiv.org/abs/{arxiv_id}",
        pdf_urls=[f"https://arxiv.org/pdf/{arxiv_id}"],
    )


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _http_url(value: object) -> str | None:
    if isinstance(value, str) and value.startswith(("https://", "http://")):
        return value.strip()
    return None


def _first(values: object) -> str | None:
    if isinstance(values, list) and values and isinstance(values[0], str):
        return values[0]
    return None


def _text(value: str) -> str:
    """Plain text: HTML tags and entities removed (Crossref titles may contain <i>…</i>)."""
    return _SPACES.sub(" ", html.unescape(_TAGS.sub("", value))).strip()


def _preprint_server(doi: str) -> str | None:
    return PREPRINT_SERVERS.get(doi.split("/", 1)[0])


def _later(feature: str) -> ProviderConfigurationError:
    return ProviderConfigurationError(f"Scholarly {feature} is not implemented yet (Phase 5).")
