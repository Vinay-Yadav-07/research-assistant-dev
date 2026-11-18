# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Primary:** students and researchers in any field who work from a set of papers they chose themselves: a thesis topic, a literature survey, a methods comparison. Their job: ask questions of those papers, compare and synthesize them, and get answers they can check and cite, without the model quietly filling gaps from elsewhere.
- **Secondary:** the project's academic reviewers and guide, who see the product mostly through the deployed demo and the evaluation results.

The product is domain-general. The benchmark corpora (tissue engineering, bioceramic scaffolds) and the dev test papers (biomaterials, finance, mathematical modelling, computer science) are test data, not the target audience. Features are checked on papers from more than one field.

## Product Purpose

A research workspace where every answer can be checked. Users collect papers into an isolated workspace, ask questions, and get answers whose every claim is verified against a passage and cited to its page. When the papers don't cover a question, it abstains and asks before using anything beyond them. Success means fewer unsupported claims than conventional RAG, measured on the project's benchmark (SRS §3.3).

## Core Workflows

1. **Collect:** create a workspace, upload PDFs or find and import open-access papers (Discover). Each upload is checked for fit with the workspace topic and for duplicates.
2. **Ask:** ask a question; watch the run's real stages; read an answer whose claims each carry a status and a citation; open the cited page with the passage highlighted.
3. **Decide at the boundary:** when the papers don't cover a question, see what is missing and choose whether to stay corpus-only or approve general knowledge for that request.
4. **Analyse:** compare papers attribute by attribute, synthesize themes, look for contradictions and corpus gaps, each result cited.
5. **Keep:** save answers and analysis results as findings; export them as Markdown and their citations as BibTeX.

## Feature Status

Availability follows `docs/PROGRESS.md` and SRS §6 and §22. A feature listed as planned must never be presented as available in the UI or in copy.

**Implemented**

- Accounts (Supabase email/password; prod sign-up is invite-only) and workspaces (create, rename, archive, delete) with per-user, per-workspace isolation.
- Document library: PDF upload with ingestion status, compatibility and duplicate warnings; scanned PDFs rejected.
- Research chat (Corpus Only by default): streamed stages, claims with status, citation chips, approval card, mode badge, conversation history.
- Source viewer: the cited PDF page with the quoted passage highlighted.
- Analysis: comparison table, theme synthesis, contradiction report, corpus gap analysis (Phase 4; exit criteria not yet measured). The Gaps tab lists gaps the papers themselves state (limitations, future work), each with its evidence.
- Saved findings with Markdown and BibTeX export.
- Discover: search arXiv and OpenAlex, import open-access PDFs into a workspace.
- Public landing page.

**Experimental**

- Semantic Research Knowledge Graph (`/workspaces/[id]/graph`, D-081–D-087): implemented end to end and frozen as an initial phase. Every kept relationship links to a verbatim, verified passage, but measured quality and density are below the finished-feature bar (SRS §9.1). It must be labelled "Experimental" wherever it appears; today the page only asks users to check each passage, and the label arrives with the app shell (Known issues, `docs/PROGRESS.md`). No further graph work until it is reopened.

**Planned (not available)**

- **Research Gap Discovery** (next planned feature): evidence-grounded discovery of candidate research gaps across the user's existing papers. Where the Analysis Gaps tab reports what each paper says about its own limits, this synthesizes across papers: unresolved questions, conflicting findings, methodological limitations shared or left open, and possible research directions, each explained and cited to the passages behind it. It needs no external sources. Candidate gaps are hypotheses for the researcher to judge, not verified claims of scientific novelty, and are labelled that way.
  - Future enhancements, not required for the first version: field-level gaps and novelty checks against external literature (with approval, FR-21 Phase 5), and automated related-paper retrieval.
- Corpus + Web mode and external research (FR-15, Phase 5): shown disabled in the mode selector and approval card.
- Related-paper recommendations from the workspace topic profile (FR-16, Phase 5).
- Workspace merge analysis (FR-23–24, Phase 6).
- Literature review mode and the MCP interface (FR-29–30, Phase 7).

## Positioning

**Knowledge-boundary enforcement.** Most research chat tools answer fluently and cite loosely. This one answers only from the user's papers by default, checks each claim against its cited passage and removes it if the passage doesn't support it, and abstains or asks permission instead of guessing. It never silently crosses into web results or general model knowledge (SRS §1.1, §2.2–2.3). The value is time saved on verification: every sentence the user keeps can be traced to a page they can open.

## Operating Context

- Three knowledge modes, always visible and stored per message: Corpus Only (default), Corpus + Web (Phase 5), General Knowledge (explicit approval per request, never shown as supported).
- A paused run shows an approval request listing what the papers don't cover; the user chooses how to continue.
- Answers stream in stages (`analyzing`, `retrieving`, `assessing`, `writing`, `verifying`, `citing`), then claims with status and citations.
- Hosted on free/low tiers (Hugging Face Space CPU, demo LLM quotas); answers take seconds, and graph jobs take minutes.

## Capabilities and Constraints

- Claim statuses: supported, partially supported, unsupported, uncertain. Citation sources: workspace, external (Phase 5), general.
- Analysis, gaps and contradictions are potential findings that need expert judgement, and are labelled that way. No feature claims a gap is novel in the wider literature.
- Built in phases (SRS §22); cross-phase features need explicit approval (CLAUDE.md §2).

## Brand Commitments

- Name: Research Assistant.
- Public pages say plainly that this is a final-year B.Tech project, invite-only, with provisional results. No product-launch framing.
- Copy is plain and specific about what it does with papers; no "AI-powered", "unlock", "supercharge", "magic".
- The interface should feel like a precise, professional research tool, not a chatbot and not a student template (visual direction in `docs/DESIGN.md`).

## Evidence on Hand

- Benchmark v1: `backend/eval/data/benchmark_v1.jsonl` (questions with paper, page and verbatim snippet), corpora in `backend/eval/data/corpora_v1.json`; arXiv papers 2303.11051 (Pang et al. 2023), 2602.00146, 1804.02375.
- Measurements in `docs/PROGRESS.md` (Phase 2, 2026-10-07, 12 test items): provisional until the benchmark is verified.
- Team: Tejas Sonawane, Vinay Yadav, Punit Jadhav, Shreyas Desai.
- Absent, never to be fabricated: users, testimonials, institutions, adoption numbers, invented papers, quotes or citations.

## Product Principles

1. The evidence boundary is visible everywhere: mode, source and status of every claim.
2. Show the evidence, not a promise about it: real passages, real pages.
3. Abstaining is a correct answer, presented as normal, not as an error.
4. Never pre-select or auto-continue across a boundary; the user decides.
5. Be honest about status: implemented, experimental or planned; provisional numbers; student project.
6. Progress shown is progress the backend reports: no invented percentages, results or verification states.
7. Domain-general by default: no field-specific wording, examples or assumptions in the product UI.

## Accessibility & Inclusion

WCAG 2.1 AA text contrast in both light and dark themes; claim status never by colour alone (icon + word); full keyboard access with visible focus; layouts work from 375 px; motion respects `prefers-reduced-motion`, and looping demos can be paused.

## Design System

The visual and motion source of truth is `docs/DESIGN.md`. There is no root DESIGN.md.
