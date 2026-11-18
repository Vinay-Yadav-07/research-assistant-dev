import type { Schemas } from "@/lib/api/client";

type Draft = Schemas["CitationDraft"];
type Citation = Schemas["CitationRead"];

/**
 * An analysis citation snapshot in the shape the chat's chips and source viewer take. Analysis
 * results are not stored as citation rows, so `key` stands in for the row id.
 */
export function asCitation(c: Draft, key: string): Citation {
  return {
    id: key,
    source_type: c.source_type,
    document_id: c.document_id ?? null,
    chunk_id: c.chunk_id ?? null,
    document_title: c.document_title ?? null,
    page_start: c.page_start ?? null,
    page_end: c.page_end ?? null,
    section: c.section ?? null,
    quote: c.quote ?? null,
  };
}
