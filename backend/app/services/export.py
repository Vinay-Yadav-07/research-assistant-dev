"""Markdown and BibTeX export of saved findings (FR-32).

Findings store outputs as the API returned them. Every finding type shares one shape: claims
are objects with a `text` and a `citations` list of citation snapshots, grouped under objects
with a `title` (themes). The renderers walk that shape instead of knowing each type.
"""

import re
import unicodedata
from collections.abc import Iterator, Sequence
from typing import Any
from uuid import UUID

from app.models.document import Document
from app.models.research import SavedFinding

_CITATIONS = "citations"
# Keys whose string values are rendered as lines of the finding, in this order.
_LINES = (("topic", "**Topic:** {}"), ("question", "**Question:** {}"))
_NOTES = (("label", "_Label: {}_"), ("context_note", "_Context: {}_"))


def citations_in(content: Any) -> Iterator[dict[str, Any]]:
    """Every citation snapshot in a finding's content, in reading order."""
    if isinstance(content, dict):
        for key, value in content.items():
            if key == _CITATIONS and isinstance(value, list):
                yield from (c for c in value if isinstance(c, dict))
            else:
                yield from citations_in(value)
    elif isinstance(content, list):
        for item in content:
            yield from citations_in(item)


def cited_document_ids(findings: Sequence[SavedFinding]) -> list[UUID]:
    """The corpus documents the findings cite, first citation first, without repeats."""
    ids: dict[UUID, None] = {}
    for finding in findings:
        for citation in citations_in(finding.content_json):
            try:
                ids.setdefault(UUID(str(citation["document_id"])))
            except (KeyError, ValueError):
                continue  # external or deleted source: no document to cite
    return list(ids)


def _citation_key(citation: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(citation.get(k) for k in ("document_id", "document_title", "page_start", "quote"))


def _reference(citation: dict[str, Any]) -> str:
    parts = [citation.get("document_title") or "Untitled source"]
    start, end = citation.get("page_start"), citation.get("page_end")
    if start:
        parts.append(f"p. {start}" if not end or end == start else f"pp. {start}–{end}")
    if citation.get("section"):
        parts.append(str(citation["section"]))
    line = ", ".join(str(p) for p in parts)
    if citation.get("quote"):
        line += f' — "{citation["quote"]}"'
    return line


def _render(content: Any, depth: int, refs: dict[tuple[Any, ...], int], out: list[str]) -> None:
    """Append `content` as Markdown lines, numbering each new citation in `refs`."""
    if isinstance(content, list):
        for item in content:
            _render(item, depth, refs, out)
        return
    if not isinstance(content, dict):
        return
    for key, template in _LINES:
        if isinstance(content.get(key), str):
            out.append(template.format(content[key]))
    # Themes have a `title`; comparison columns name their paper in `document_title`.
    heading = content.get("title") or content.get("document_title")
    if isinstance(heading, str):
        out.append(f"{'#' * min(depth, 6)} {heading}")
        depth += 1
    if isinstance(content.get("text"), str):
        markers = "".join(
            f"[{refs.setdefault(_citation_key(c), len(refs) + 1)}]"
            for c in content.get(_CITATIONS, [])
            if isinstance(c, dict)
        )
        label = f"**{content['attribute']}:** " if isinstance(content.get("attribute"), str) else ""
        out.append(f"- {label}{content['text']}{' ' + markers if markers else ''}")
    for key, value in content.items():
        if key != _CITATIONS and isinstance(value, (dict, list)):
            _render(value, depth, refs, out)
    for key, template in _NOTES:
        if isinstance(content.get(key), str) and content[key]:
            out.append(f"  {template.format(content[key])}")


def to_markdown(workspace_name: str, findings: Sequence[SavedFinding]) -> str:
    """The findings as one Markdown document; each finding numbers its own references."""
    out = [f"# Saved findings — {workspace_name}", ""]
    for finding in findings:
        out += [f"## {finding.title}", "", f"_{finding.type} · {finding.created_at:%Y-%m-%d}_", ""]
        refs: dict[tuple[Any, ...], int] = {}
        snapshots = {_citation_key(c): c for c in citations_in(finding.content_json)}
        _render(finding.content_json, 3, refs, out)
        if refs:
            out += ["", "**References**", ""]
            out += [f"{n}. {_reference(snapshots[key])}" for key, n in refs.items()]
        out.append("")
    return "\n".join(out)


_BIBTEX_SPECIAL = re.compile(r"([{}&%$#_])")


def _escape(value: str) -> str:
    value = value.replace("\\", r"\textbackslash ")
    return _BIBTEX_SPECIAL.sub(r"\\\1", value)


def _key_stem(document: Document) -> str:
    first = (document.authors or [""])[0]
    # "Last, First" puts the surname first; "First Last" puts it last.
    name = first.split(",")[0] if "," in first else (first.split() or [""])[-1]
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    stem = re.sub(r"[^a-z]", "", ascii_name.lower()) or f"doc{str(document.id)[:8]}"
    return f"{stem}{document.year or ''}"


def to_bibtex(documents: Sequence[Document]) -> str:
    """One BibTeX entry per document, keyed `surnameYEAR` with a/b/… on collisions."""
    stems = [_key_stem(d) for d in documents]
    seen: dict[str, int] = {}
    entries = []
    for document, stem in zip(documents, stems, strict=True):
        count = seen.get(stem, 0)
        seen[stem] = count + 1
        key = stem if stems.count(stem) == 1 else f"{stem}{chr(ord('a') + count)}"
        fields = {
            "title": document.title or "Untitled",
            "author": " and ".join(document.authors or []),
            "year": str(document.year) if document.year else "",
            "journal": document.venue or "",
            "doi": document.doi or "",
        }
        body = ",\n".join(f"  {name} = {{{_escape(v)}}}" for name, v in fields.items() if v)
        entries.append(f"@{'article' if document.venue else 'misc'}{{{key},\n{body}\n}}\n")
    return "\n".join(entries)
