"""Schemas for Discover: paper search and one-click import (FR-17, SRS §10, D-077)."""

from typing import Literal

from pydantic import BaseModel, Field

from app.providers.search import DiscoverySource, PaperRecord

SearchScope = Literal["all", "arxiv", "openalex"]


class PaperSearchResponse(BaseModel):
    """Search results; `unavailable` names sources that failed, so results may be partial.
    `quota_exhausted` names those among them whose daily request quota is used up.

    Every field of a result comes from an external API and is untrusted text.
    """

    results: list[PaperRecord]
    unavailable: list[DiscoverySource] = Field(default_factory=list)
    quota_exhausted: list[DiscoverySource] = Field(default_factory=list)


class PaperImportRequest(BaseModel):
    """Import a search result into a workspace; the server looks the paper up again.

    `override` is true when the user chose "Import anyway" after a compatibility warning.
    """

    source: DiscoverySource
    external_id: str = Field(min_length=1, max_length=200)
    override: bool = False
