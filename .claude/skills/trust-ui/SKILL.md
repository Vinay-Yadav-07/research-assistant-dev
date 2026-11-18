---
name: trust-ui
description: Rules for the knowledge-boundary and evidence UI (claim status, citation chips, mode badge, approval card, source highlight). Load before building chat, citation, approval or source-viewer components.
---

# Trust UI

The UI must never blur where an answer came from (SRS §2 knowledge boundary, FR-13). Visual
style comes from the `ui-design` skill. Values below come from the API types in
`src/lib/api/schema.d.ts`; never invent statuses or modes.

## Claim status (`ClaimStatus`)

Each status shows an **icon + label + color**, never color alone (WCAG 1.4.1).

| Status | Token | Icon (lucide) | Label |
|---|---|---|---|
| `supported` | `status-supported` | `CircleCheck` | Supported |
| `partially_supported` | `status-partial` | `CircleDot` | Partly supported |
| `unsupported` | `status-unsupported` | `CircleX` | Not supported |
| `uncertain` | `status-uncertain` | `CircleQuestionMark` | Uncertain |

## Source of a claim (`CitationSourceType`)

- `workspace`: a citation chip in mono, `Author Year · p.N` (`p.N–M` for ranges). Clicking it opens the
  source viewer at the page with the quote highlighted in `mark`.
- `external`: the same chip with an `ExternalLink` icon and the label "External" (Phase 5).
- `general`: no chip. Show the label "General knowledge — not from your papers" in `status-uncertain`.
  It is never shown as supported.

## Mode badge (`MessageMode`)

Always visible in the chat header and stored per message: "Corpus only", "Corpus + Web",
"General knowledge". An existing `corpus_web` conversation shows its true mode. Selecting Corpus +
Web is disabled with a "Phase 5" tooltip.

## Approval card (`approval_required` event)

- Show which sub-questions lack evidence and what the corpus does cover, in plain words.
- Options: "Stay corpus-only" (default focus), "Use general knowledge", and "Search external
  sources" disabled until Phase 5. Never pre-select or auto-continue.
- An abstention is a normal answer: "Your papers don't cover this", not an error style.

## Progress

Stream `status` events as one quiet line (e.g. "Retrieving · Verifying 3 claims"). Do not use spinners
on every claim, fake typing, or percentages the backend does not send.
