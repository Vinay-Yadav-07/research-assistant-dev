---
title: "Software Requirements Specification"
subtitle: "Multi-Agent, Evidence-Grounded AI Research Assistant — SRS Version 1.29"
---

| Document Item | Value |
|---|---|
| Project Type | Final-Year B.Tech Project |
| Primary Domain | AI-assisted scientific literature research |
| Document Status | Implementation baseline (supersedes v1.7) |
| Prepared For | Project development (including AI coding agents) and academic review |
| Date | 20 October 2026 |
| Project Team | To be completed by project team |
| Guide | To be completed by project team |

# 0. Revision Summary

## v1.28 → v1.29 (20 October 2026)

D-088. No functional requirement changed.

1. **Phases** (Section 22): the single UI polish pass between Phase 7 and Phase 8 becomes a stepwise UI redesign to the direction in `docs/DESIGN.md`, starting with the foundation and app shell; it may run alongside other phases.

## v1.27 → v1.28 (20 October 2026)

D-087. The Semantic Research Knowledge Graph is frozen as an **experimental, initial-phase** feature. Status lines now say what is implemented; nothing is removed and no requirement is weakened.

1. **Status** (Sections 3.1, 5.3, 6, 9, 9.1, 16, 19.1): implemented end to end (jobs, extraction with evidence validation, build, read API, graph page) and labelled experimental.
2. **Limitations and future scope** (Section 9.1): measured quality, sparse graphs, conservative entity merging, filters not built, and generation off unless the graph tier is configured.

## v1.26 → v1.27 (20 October 2026)

D-086. Knowledge graph validation is stricter; no requirement is weakened.

1. **Review papers** (Section 9.1, rule 5): in a paper that calls itself a review (title or opening passages), only a quote in the review's own voice ("we", "our", "this review") counts as the paper's own work. In any paper, "the authors" right after a sentence reporting a cited study is that study's authors.
2. **Relationship shape** (Section 9.1, rule 4): a quote that names one entity as the other ("which we call ...") states identity, not a relationship; a `uses` target concept that appears only inside a longer phrase is rejected.

## v1.25 → v1.26 (20 October 2026)

D-085. Knowledge graph validation rule 5 gains a deterministic attribution check, and the graph tier gets its own retry settings. No requirement is weakened.

1. **Attribution check** (Section 9.1, rule 5): a relationship is also rejected when its quote, read with the sentence before it, clearly credits cited or background research. The check is conservative: own-work markers always keep it.
2. **Graph-tier retries** (Section 9.1): `LLM_GRAPH_MAX_RETRIES` (4) and `LLM_GRAPH_RETRY_BASE_SECONDS` (10) replace the shared retry settings for the graph tier only.

## v1.24 → v1.25 (18 October 2026)

D-081. The Semantic Research Knowledge Graph is specified; nothing is implemented yet, and no requirement is weakened.

1. **Knowledge graph specified** (Sections 3.1, 5.3, 6, 9, 9.1, 14.1, 15.1, 16.1, 19.1, 26): S10 Knowledge Graph Service; FR-33; a closed vocabulary of 7 entity types and 6 relationship types; validation that each kept relationship is stated by its cited passage (verbatim quote, both entities in the quote, own-work and non-hedged, local NLI entailment); per-paper extraction checkpoints reused across the user's workspaces; an atomic per-workspace build; one active job per workspace, heartbeat-based stale detection, no automatic resume; a separate graph LLM tier with its own limits and a per-job budget.

## v1.23 → v1.24 (15 October 2026)

D-077, D-078. FR-17 is brought forward from Phase 5 in part; no requirement is weakened.

1. **Discover search and import** (Sections 10, 16.1, 19, 22): a Discover page searches arXiv and OpenAlex (`GET /papers/search`) and imports a paper's open-access PDF into a chosen workspace (`POST /workspaces/{id}/import`) through the upload pipeline and compatibility check. The search is started by the user, so it needs no run approval; QA knowledge modes are unchanged. Related-paper recommendation (FR-16), metadata-only save, response caching, Semantic Scholar, Europe PMC and Unpaywall remain Phase 5 work.
2. **Evidence graph retired** (Sections 3, 9, 11.1, 15, 16.1, 19, 22, 26): the evidence-provenance graph and `GET /workspaces/{id}/graph` are removed. A **Semantic Research Knowledge Graph** is planned as the next major feature; it is not specified or implemented yet.
3. **Discover reliability** (Section 10.1, D-079): Discover requests use a 15 s timeout with one retry for transient failures; PDF downloads retry transient failures once within per-download and per-import time limits; results report a PDF status (verified / unverified / link only), with an "Importable PDFs only" filter.
4. **OpenAlex key and quota** (Sections 10.1, 15, D-080): an optional OpenAlex API key; a used-up quota pauses OpenAlex searches and is reported to the user while arXiv results continue. The PDF check budget is 4 s; "All papers" is the default view.

## v1.22 → v1.23 (8 October 2026)

D-075. No functional requirement changed.

1. **Phases** (Section 22): a UI polish pass is added between Phase 7 and Phase 8; Phase 3–7 screens are built functional first.

## v1.21 → v1.22 (8 October 2026)

Phase 3 task #2b (D-074). No functional requirement changed.

1. **Technology stack** (Section 15): the frontend adds `motion` for landing-page animation; the design rules move to `docs/DESIGN.md`.

## v1.20 → v1.21 (8 October 2026)

Phase 3 task #2 (D-073). No functional requirement changed.

1. **Phase 3 scope** (Section 22): adds a landing page at `/` in the Paper & ink design system.

## v1.19 → v1.20 (8 October 2026)

Phase 3 task #1 (D-072). No functional requirement changed.

1. **Chat API** (Section 16.1): the message history includes each answer's claims and citations; `GET /runs/{run_id}` returns a run's state and, while paused, its approval request, so a reloaded conversation can resume it (Section 20). `GET /chunks/{id}` is deferred.

## v1.18 → v1.19 (6 October 2026)

Phase 2 task #10 (D-069, D-070). No functional requirement changed.

1. **Benchmark format** (Section 17.4): items carry a `type` (single, multi, comparison, unanswerable); multi-paper and comparison items list their gold passages in `evidence`. Benchmark v1 has a 53-item calibration split and a 54-item test split.
2. **Evaluation harness** (Sections 15.1, 17.3, 21.1): baseline prompts live in `backend/eval/prompts/`; the Ragas judge is set by `EVAL_JUDGE_*` and must differ from A3's model; the CLI runs with the `eval` dependency group.
3. **Cost** (NFR-13, D-070): paid LLM credit may be used for the Phase 8 benchmark runs and the demonstration, with demo-only API keys; full benchmark runs move to Phase 8, after recalibrating on the final model.

## v1.17 → v1.18 (6 October 2026)

Phase 2 task #9 (D-068). No functional requirement changed.

1. **Metadata** (FR-04, Section 8.1): the first-page LLM extraction runs only when no DOI is confirmed; it fills title, authors, year, and venue and never supplies a DOI.
2. **S7 keyword summary** (Sections 5.3, 11.2, 16.1): refreshed in the background after a document becomes ready, is linked, or is removed, from the titles and first chunks of up to `TOPIC_SUMMARY_MAX_DOCUMENTS` ready documents; workspace responses include `keywords` and `summary`.

## v1.16 → v1.17 (6 October 2026)

Phase 2 task #8 (D-036 confirmed). No functional requirement changed.

1. **Streaming** (Sections 5.4, 16.2): no `token` event. The answer is sent whole once verification and citation checks finish; progress is streamed as `status` events.

## v1.15 → v1.16 (5 October 2026)

Phase 2 task #6 (D-067). No functional requirement changed.

1. **A3 / verification loop** (Sections 5.2, 7.3): each A2 sentence that cites passages is one claim (no extraction call); NLI scores claims against short sentence windows of the cited chunks and only accepts, the batched LLM judge decides every other claim.
2. **NLI model** (Section 15): default `cross-encoder/nli-deberta-v3-xsmall`.

## v1.14 → v1.15 (5 October 2026)

Phase 2 task #5 (D-066). No functional requirement changed.

1. **A2 / S5** (Sections 5.2, 5.3): A2 cites short evidence labels (`E1`, `E2`, …) that S5 assigns to the run's evidence set and maps back to chunk IDs; labels outside the set never become citations.

## v1.13 → v1.14 (4 October 2026)

Phase 2 task #4 (D-065). No functional requirement changed.

1. **S3 Sufficiency Gate** (Section 5.3): a reranker-score fast pass plus one batched LLM answerability check (covered / partial / insufficient) for the remaining sub-questions.

## v1.12 → v1.13 (4 October 2026)

Phase 2 task #2 (D-064). No functional requirement changed.

1. **Data model** (Section 14.1): ownership and mode columns on `conversations` and `agent_runs`; citations keep a snapshot of their source (title, page range, section, quote) and a `chunk_id`; `external_source_id` arrives with `external_sources` in Phase 5.

## v1.11 → v1.12 (4 October 2026)

Changes from Phase 2 planning and task #1 (D-062, D-063). No functional requirement changed.

1. **LLM access** (Section 15.1): default models Groq `openai/gpt-oss-20b` (fast) and Gemini `gemini-3.5-flash-lite` (strong); client-side retries and per-model rate limits with a daily cap; a `demo` provider for key-free local runs, refused in production.
2. **Benchmark** (Section 17.4): fixed calibration and test splits; per-item `drafted_by`/`verified_by`; results count verified test items only.

## v1.10 → v1.11 (3 October 2026)

Changes from Phase 1 task #8 (recorded in `docs/DECISIONS.md`, D-060). No functional requirement changed.

1. **Compatibility check** (Section 11.2): the document vector is the normalized mean of its first `COMPATIBILITY_CHUNKS` chunks; the pre-upload check parses only the first `COMPATIBILITY_MAX_PAGES` pages; the threshold (0.83) is calibrated on the benchmark papers; linking a ready document with `PUT` is checked too (409 `compatibility_warning` unless `override=true`).

## v1.9 → v1.10 (3 October 2026)

Changes from Phase 1 task #7 (recorded in `docs/DECISIONS.md`, D-059). No functional requirement changed.

1. **Dense retrieval** (Section 8.2): exact cosine search over the workspace's chunks instead of the HNSW index; full-text search matches any query term.
2. **Retrieval debug endpoint** (Section 16): `POST /workspaces/{id}/retrieval/debug`.

## v1.8 → v1.9 (3 October 2026)

Changes from Phase 1 task #6 (recorded in `docs/DECISIONS.md`, D-057 and D-058). No functional requirement removed.

1. **Duplicate uploads** (Sections 14.1, 16, 20): `documents` is unique on `(user_id, content_hash)`; a duplicate is linked with the new `PUT /workspaces/{id}/documents/{doc_id}`.
2. **Stale sweep** (Section 8.1): at startup and periodically, in-progress documents not updated for `INGESTION_STALE_MINUTES` (and not being processed) are marked `failed`; ingestions run behind `INGESTION_CONCURRENCY`.

## v1.7 → v1.8 (3 October 2026)

Clarifications from Phase 1 task #4 (recorded in `docs/DECISIONS.md`, D-054 and D-055). No functional requirement changed.

1. **Page numbers** (Section 8.3): `page_start`/`page_end` are 1-based PDF page indexes, not printed page numbers.
2. **Token counting** (FR-06, Section 15.1): the embedding provider interface counts tokens with the model's tokenizer.

## v1.6 → v1.7 (2 October 2026)

Model decisions after the Phase 1 CPU measurements (recorded in `docs/DECISIONS.md`, D-050 and D-051). No functional requirement was removed.

1. **Embedding model** (Sections 14.1, 15.1): back to BAAI/bge-small-en-v1.5 (384-dim); `chunks.embedding` is `vector(384)`.
2. **Reranker** (Sections 8.2, 15.1): cross-encoder/ms-marco-MiniLM-L-6-v2 replaces bge-reranker-base; the top 20 fused candidates are reranked.

## v1.5 → v1.6 (2 October 2026)

Phase 1 decisions made before implementation (recorded in `docs/DECISIONS.md`, D-044 to D-049). No functional requirement was removed; two LLM sub-steps moved to Phase 2.

1. **Chunk size** (FR-06): ~350–450 tokens measured with the embedding model's tokenizer, ~12% overlap, to fit 512-token model limits.
2. **Metadata split** (FR-04, Sections 5.3, 8.1, 22): Phase 1 uses PDF metadata, DOI regex, DOI lookup (Crossref/OpenAlex), and a title fallback; LLM first-page extraction and the S7 LLM keyword summary move to Phase 2. Phase 1 makes no LLM calls.
3. **Workspace deletion** (FR-02, Section 16.1): deleting a workspace permanently deletes documents that no other workspace uses.
4. **Non-owned resources** (Section 16.1) return 404.
5. **Embedding model** (Sections 14.1, 15.1): BAAI/bge-base-en-v1.5 (768-dim) replaces bge-small-en-v1.5 (384-dim) as the default.
6. **Accepted risks** (Section 23): CPU-only torch, stale-ingestion sweep at startup, server-side Supabase secret key for Storage, JWT verification via JWKS.

## v1.4 → v1.5 (1 October 2026)

Hosting decision made during the Phase 0 deploy (recorded in `docs/DECISIONS.md`, D-043). No functional requirement was removed.

1. **Backend hosting cost** (NFR-13, Section 15.3): Docker Spaces require Hugging Face PRO since July 2026. The backend Space runs on PRO (about ₹800/month) with Protected visibility; every other service stays on free tiers.

## v1.3 → v1.4 (30 September 2026)

Database decisions made while initializing Alembic in Phase 0 (recorded in `docs/DECISIONS.md`, D-040 and D-041). No functional requirement was removed.

1. **Database access model** (Sections 14.1, 18): the Supabase Data API (PostgREST) is disabled and automatic RLS is enabled for new tables in `public`. The backend is the only database client; the frontend uses Supabase only for Auth.
2. **Alembic scope and naming** (Section 14.1): autogenerate reflects only the `public` schema and skips the LangGraph checkpoint tables. Constraints and indexes follow a fixed naming convention. Migrations are run explicitly, never at application startup.

## v1.2 → v1.3 (30 September 2026)

Provider-layer decisions made while implementing the Phase 0 provider interfaces (recorded in `docs/DECISIONS.md`, D-031 to D-035). No functional requirement was removed.

1. **Two LLM tiers** (Section 15.1): a "fast" and a "strong" chat model, each with its own provider and model setting, so they may come from different vendors.
2. **Search split** (Section 10.1): scholarly APIs use a `ScholarlySearchProvider`; Tavily uses a separate `WebSearchProvider`, which is only given to code holding a Corpus + Web approval.
3. **Reranker scores** (Section 8.2) are normalized to [0, 1] so sufficiency thresholds are model-independent.
4. **Startup and model loading** (Section 15.3): provider configuration is validated at startup; a `PRELOAD_MODELS` setting controls whether local model weights load at startup (production) or on first use (local development).

## v1.1 → v1.2 (29 September 2026)

Clarifications agreed by the team before Phase 0 implementation (recorded in `docs/DECISIONS.md`, D-001 to D-024). No functional requirement was removed.

1. **Layering clarified** (Section 5.1): agents and services may call providers; repositories may not. Routers may call services directly for plain CRUD; graphs are only for agentic workflows.
2. **Prompts and schemas** (Sections 5.2, 21.1): all prompts live in `app/prompts/agents/` and `app/prompts/services/`, versioned; output schemas live next to their owner. A6 subagents are part of A6.
3. **Fake providers** live in `app/providers/fakes/` and are selectable through configuration (Sections 21.1, 21.2).
4. **Knowledge modes** (Sections 2.3, 10.3): workspace `default_mode` may be Corpus Only or Corpus + Web; General Knowledge always needs per-request confirmation.
5. **Workspace archive vs delete** separated (FR-02, Section 16.1).
6. **Verification cost** (Section 7.3, NFR-13): borderline judge checks are batched; LLM-call budget raised to an average of ≤ 10.
7. **NFR-10** now states that changing the embedding dimension needs a migration and re-indexing.
8. **Alembic scope** (Section 14.1): Supabase `auth`/`storage` schemas and LangGraph checkpoint tables are excluded; pgvector is enabled in the first Phase 1 migration.
9. **New entity and endpoints:** `api_tokens` (hashed) for MCP authentication, scheduled for Phase 7 (Sections 14.1, 16.1, 16.3).
10. **Evaluation moved** to `backend/eval/` with Ragas in an `eval` dependency group (Sections 15.1, 16.1, 17.4, 21.1).
11. **Health readiness:** `GET /health/ready` checks the database (Section 16.1, Phase 0).
12. **Phase changes** (Section 22): Phase 0 scope and exit criteria made explicit (tests, CI contents, `gen:api`, CORS, setup instructions); Phase 1 adds a CPU inference benchmark.
13. **Process aligned with CLAUDE.md** (Sections 15, 21.3): task-branch workflow through `dev`; the stack is a default that can change through an approved proposal; `docs/PROGRESS.md` tracks a backend phase and a frontend track.

## v1.0 → v1.1

This version turns the v1.0 requirements baseline into an implementation baseline. The main changes are:

1. **Agent architecture consolidated.** The components listed as agents in v1.0 are reorganized into 6 LLM agents and 9 deterministic services. Components that do not need LLM reasoning (citation mapping, compatibility scoring, merge analysis, workspace isolation) are now services. The LLM supervisor is replaced by a fixed LangGraph graph with conditional edges for the main question-answering workflow (Section 5).
2. **Technology stack finalized** (Section 15). Supabase (Postgres + pgvector + Storage + Auth) replaces separate PostgreSQL, Chroma, and AWS S3. PyMuPDF4LLM replaces plain PyMuPDF for section-aware parsing. Embedding, reranking, and NLI models run locally in the backend.
3. **Deployment simplified** (Section 15.3): Vercel (frontend) + Docker container on Hugging Face Spaces (backend) + Supabase (all persistent data). Local development requires no Docker.
4. **New requirements added:** FR-29 (MCP server interface), FR-30 (deep-agent literature review mode), FR-31 (prompt-injection handling), FR-32 (BibTeX/Markdown export).
5. **Non-functional requirements made measurable** (Section 13) and the NFR table repaired.
6. **Acceptance criteria given quantitative targets** (Section 24).
7. **Evaluation plan extended** with verifier accuracy evaluation, gold-evidence labeling, benchmark sizes, and judge/verifier model separation (Section 17).
8. **Data model extended** (Section 14): many-to-many workspace–document relation, embedding model versioning, approval log, evaluation records.
9. **Phases reorganized into 9 dependency-ordered implementation phases** with deliverables and exit criteria, designed for incremental implementation with AI coding agents (Section 22).
10. **Security extended** with prompt-injection handling and data-layer enforcement of workspace isolation (Section 18).

All functional requirements from v1.0 remain in scope for the release.

# 1. Introduction

## 1.1 Purpose

This Software Requirements Specification (SRS) defines the requirements, architecture, and implementation plan for a multi-agent, evidence-grounded AI Research Assistant that helps users study and analyze a controlled collection of scientific research papers. The system combines Retrieval-Augmented Generation (RAG), agentic workflows, claim-level evidence verification, citation tracing, research discovery, contradiction detection, research-gap analysis, and human-in-the-loop controls.

The central design principle is **knowledge-boundary enforcement**: the system must distinguish between information supported by the active research workspace, information obtained from external sources, and general model knowledge. It must never silently cross this boundary.

## 1.2 Problem Statement

Large language models have broad pretrained knowledge and generate plausible answers that are not necessarily supported by a researcher's selected literature. Even when instructed to answer only from supplied context, models often blend in pretrained knowledge (parametric knowledge leakage). Conventional RAG improves grounding by retrieving relevant documents, but retrieval alone does not guarantee that every generated claim is supported by the retrieved evidence.

Researchers therefore need a system that operates over a user-defined corpus, traces every claim to evidence, abstains when evidence is insufficient, and explicitly requests permission before using external web information or general model knowledge.

## 1.3 Intended Audience

- Students and researchers studying a defined scientific topic.
- Academic project reviewers and supervisors evaluating the system.
- Developers and AI coding agents implementing the AI, backend, frontend, and data layers.
- Researchers interested in groundedness, citation reliability, and agentic RAG.

## 1.4 Definitions and Conventions

| Term | Definition |
|---|---|
| Workspace | An isolated research environment containing documents, conversations, metadata, evidence, and research outputs. |
| Corpus | The set of documents explicitly associated with a workspace. |
| Corpus-only mode | Answering mode in which factual claims must be supported by the active workspace corpus. |
| Evidence | A document passage or other retrievable source unit supporting a claim. |
| Groundedness | The degree to which generated claims are supported by available evidence. |
| Abstention | A deliberate response stating that sufficient evidence is unavailable instead of fabricating an answer. |
| LLM agent | A component that uses a language model to reason, with a defined responsibility, tools, and a Pydantic-validated structured output. |
| Service | A deterministic component (no LLM reasoning, or a single bounded LLM call) with a defined interface. |
| Human-in-the-loop (HITL) | A workflow step that pauses and requests explicit user approval before a boundary-crossing action. |
| Reranker | A model that reorders retrieved candidates using a more precise relevance score. |

Requirement keywords: **shall** = mandatory; **should** = expected unless a documented reason prevents it; **may** = optional.

# 2. Overall Description

## 2.1 Product Perspective

The product is a web-based research workspace. Users create workspaces, upload or import papers, ask questions, compare literature, identify potential contradictions and research gaps, discover related open-access papers, and generate evidence-backed research outputs. An orchestration layer built on LangGraph coordinates retrieval, analysis, verification, citation, and external research. The same capabilities are exposed to external AI clients through an MCP server.

## 2.2 Core Product Principle

Know the evidence boundary → retrieve evidence → reason over evidence → verify claims → cite evidence → abstain or ask permission when evidence is insufficient.

## 2.3 Knowledge Modes

| Mode | Allowed Knowledge | Expected Behavior |
|---|---|---|
| Corpus Only (default) | Active workspace corpus | Answer only from workspace evidence; abstain when insufficient. |
| Corpus + Web | Workspace corpus + approved external scholarly/web sources | Label every claim as workspace or external evidence and cite both. |
| General Knowledge | Workspace corpus + general model knowledge | Enabled only after explicit user confirmation per request; claims not backed by evidence are labeled "General knowledge — not verified against sources". |

The active mode shall be visible in the UI at all times and stored with every message.

A workspace's `default_mode` may be Corpus Only or Corpus + Web, never General Knowledge. Starting a conversation in Corpus + Web (whether chosen as the workspace default or for that conversation) counts as the user's approval of external search for that conversation and is recorded in the approval log. General Knowledge always requires explicit confirmation per request.

# 3. Product Scope and Objectives

## 3.1 In Scope (Release 1.0)

- Authenticated, workspace-based research management.
- PDF ingestion with section-aware parsing, metadata extraction, and DOI enrichment.
- Hybrid (dense + lexical) retrieval with reranking, strictly scoped to the active workspace.
- Corpus-grounded question answering with claim-level verification, citations, and abstention.
- Human approval before web search or general-knowledge fallback.
- Multi-paper synthesis and structured literature comparison.
- Potential contradiction detection with contextual qualification.
- Corpus-based and (when authorized) field-level research-gap analysis.
- Semantic Research Knowledge Graph: experimental, initial phase (Section 9.1, D-081–D-087; replaces the retired evidence-provenance graph, D-078).
- Open-access research-paper discovery, similar-paper recommendation, and paper import.
- Document compatibility checks and workspace merge analysis.
- Deep-agent literature review mode.
- MCP server interface.
- Saved findings and export.
- Evaluation benchmark and quantitative experiments.
- Tracing and observability.

## 3.2 Out of Scope for Release 1.0

- Training or fine-tuning a foundation LLM.
- Guaranteeing zero hallucinations.
- OCR of scanned PDFs (scanned files are detected and rejected with an explanation).
- Figure and image understanding (text and table text only).
- Scraping websites or restricted scholarly platforms; importing non-open-access full texts.
- Real-time collaborative editing between multiple users.
- Automatic publication submission or peer-review decisions.

## 3.3 Primary Objectives

1. Improve factual grounding over user-defined scientific corpora.
2. Provide transparent, traceable citation provenance for generated claims.
3. Reduce unsupported claims through verification and abstention, and measure the reduction.
4. Enable structured multi-document research workflows.
5. Allow controlled, user-approved expansion from corpus-only research to external literature.
6. Provide quantitative evidence that the agentic verification architecture improves on conventional RAG.

# 4. Stakeholders and User Roles

| Role | Responsibilities |
|---|---|
| Research User | Creates workspaces, uploads/imports papers, asks questions, reviews evidence, approves external searches, exports findings. |
| Project Administrator | Maintains configuration, model/provider settings, monitoring. (Implemented via environment configuration; no admin UI in Release 1.0.) |
| Developer | Implements services, agents, integrations, tests, evaluation, deployment. |
| AI Coding Agent | Implements scoped tasks under the rules in Section 21 and the repository's CLAUDE.md. |
| Academic Reviewer/Guide | Reviews requirements, architecture, experiments, results, documentation. |

# 5. System Architecture

## 5.1 High-Level Architecture

```
Frontend: Next.js + TypeScript + Tailwind + shadcn/ui   (Vercel)
        │  REST + Server-Sent Events (SSE)
        ▼
Backend: FastAPI (Python 3.11)   (Docker container, Hugging Face Spaces)
  ├── API layer (routers, auth, request validation)
  ├── Orchestration layer (LangGraph graphs, deepagents)
  │     ├── LLM agents (A1–A6)
  │     └── Deterministic services (S1–S9)
  ├── Provider layer (LLM, embeddings, reranker, NLI, parser, search APIs)
  └── Repository layer (all database / storage access)
        │
        ▼
Supabase: Postgres + pgvector + full-text search │ Storage (PDFs) │ Auth
        │
External: OpenAlex · Semantic Scholar · arXiv · Europe PMC · Unpaywall · Crossref · Tavily
Tracing: LangSmith

MCP server (FastMCP, runs on user's machine) ──► Backend REST API
```

Layering rule: API → orchestration → services → repositories. Agents shall never access the database directly; they call services.

- Agents and services may call providers; repositories shall not.
- Routers may call services directly for plain CRUD operations (for example, workspace create/rename/archive). LangGraph graphs are used only for agentic workflows.
- Routers contain no business logic.

## 5.2 LLM Agents

Each agent has one responsibility, a Pydantic output schema defined next to the agent, and a prompt stored as a versioned file in `app/prompts/agents/`.

| ID | Agent | Responsibility | Output |
|---|---|---|---|
| A1 | Query Analyzer | Classifies intent (simple QA, multi-hop, comparison, aggregation, contradiction, gap, discovery, out-of-scope); decomposes into at most 4 search-ready sub-questions with dependencies; may add search synonyms but shall not assert facts. | `QueryPlan` |
| A2 | Synthesis Agent | Writes the answer strictly from provided evidence, citing every factual sentence by the evidence label S5 gave its chunk; follows the active knowledge mode. | `DraftAnswer` |
| A3 | Verification Agent | Treats each A2 sentence that cites passages as one claim, scores each against its cited evidence (NLI model over sentence windows first, accepting only clear entailment; all other claims of a draft sent to the LLM judge in one batched call), assigns claim status, requests revision of unsupported claims (max 2 loops). | `VerificationReport` |
| A4 | Literature Analysis Agent | Structured comparison, multi-paper synthesis, contradiction analysis, and research-gap analysis over evidence sets. One agent with task-specific prompts and schemas. | `ComparisonTable`, `ContradictionReport`, `GapReport` |
| A5 | Discovery Agent | Builds search queries from the workspace topic profile, calls scholarly search tools, deduplicates, ranks, and writes a short evidence-based relevance explanation per paper. | `DiscoveryResults` |
| A6 | Literature Review Deep Agent | Built with the `deepagents` library. Plans a multi-section literature review, delegates subtopics to subagents, uses services and A2–A4 as tools, stores intermediate notes, and compiles a cited, verified review. Its subagents are part of A6, not separate agents, and may use only existing services and agents (A2–A4) as tools. | `LiteratureReview` |

## 5.3 Deterministic Services

| ID | Service | Responsibility |
|---|---|---|
| S1 | Ingestion Service | Validation, parsing, metadata + DOI enrichment (first-page LLM extraction from Phase 2), section detection, chunking, embedding, indexing, status tracking. |
| S2 | Retrieval Service | Hybrid retrieval (pgvector + Postgres full-text, fused with Reciprocal Rank Fusion), reranking, top-k selection. `workspace_id` is a mandatory parameter enforced in the SQL query. |
| S3 | Evidence Sufficiency Gate | Decides whether retrieved evidence can answer each sub-question: a best reranker score at or above a calibrated fast-pass score counts as covered; the other sub-questions with evidence are judged covered, partial, or insufficient in one batched LLM call that leans against false insufficiency. Run status follows sub-question coverage. |
| S4 | Knowledge Boundary & Approval Gate | Enforces the active knowledge mode; pauses the graph with a LangGraph `interrupt()` and records the user's decision when escalation is needed. |
| S5 | Citation Service | Labels the run's evidence set; maps cited labels to chunk, document, page, section, and text span; validates that each citation exists and was part of the evidence set. |
| S6 | Guardrail Service | Input checks (empty, oversized, out-of-scope routing), content sanitization for untrusted text, output labeling of knowledge source. |
| S7 | Topic Profile & Compatibility Service | Maintains each workspace's topic profile (centroid embedding in Phase 1; LLM-generated keyword summary from Phase 2) and scores document-to-workspace compatibility. |
| S8 | Workspace Merge Analyzer | Computes workspace-to-workspace topic similarity, per-document fit, duplicates (content hash and DOI), and produces a merge report. |
| S9 | Paper Import Service | Resolves open-access PDF locations, downloads permitted full texts, runs the compatibility check, and hands off to S1. |
| S10 | Knowledge Graph Service | Implemented, experimental (D-081–D-087, Section 9.1); provisional graph model. Runs graph jobs: extracts entities and relationships per paper with bounded graph-tier LLM calls, validates each against its cited passage, and rebuilds the workspace graph atomically. |

Services that make a bounded LLM call (for example S1 first-page metadata extraction, S7 keyword summary) store their prompts as versioned files in `app/prompts/services/` and validate the output against a Pydantic schema defined next to the service.

## 5.4 Main Question-Answering Graph (fixed graph, not supervisor-driven)

```
User message
  → S6 input guardrail
  → A1 Query Analyzer ──(out_of_scope)──► polite scoped refusal
  → S2 Retrieval (per sub-question; independent sub-questions in parallel via Send)
  → S3 Sufficiency Gate
        ├─ sufficient ─────────────────────────────┐
        └─ insufficient → S4 Approval Gate (interrupt)│
              ├─ stay corpus-only → partial answer / abstention
              ├─ search external → A5 + external retrieval (Corpus + Web)
              └─ use general knowledge → General Knowledge mode
  → A2 Synthesis ◄──────────────────────────────────┘
  → A3 Verification ──(unsupported claims, loop ≤ 2)──► A2 revise
  → S5 Citation validation
  → S6 output labeling
  → Final answer (sent whole after verification) / abstention
```

The graph state shall be persisted with the LangGraph Postgres checkpointer so that interrupted runs resume after user approval.

# 6. Functional Requirements

| ID | Requirement | Description | Phase |
|---|---|---|---|
| FR-01 | User Account and Access | The system shall provide email/password authentication (Supabase Auth) and restrict all data access to the owning user. | P1 |
| FR-02 | Workspace Management | The system shall allow a user to create, rename, archive, open, and delete isolated workspaces. Archiving (`archived = true`) is reversible; deletion is permanent and requires confirmation in the UI. Deletion removes the workspace's document links and permanently deletes (chunks and stored file) every document no other workspace uses. | P1 |
| FR-03 | Document Upload | The system shall accept PDF uploads up to 25 MB per file and reject other types with guidance. | P1 |
| FR-04 | Document Metadata | The system shall extract title, authors, year, venue, DOI, page count, and source; where a DOI is found, metadata shall be enriched from OpenAlex/Crossref. Phase 1: PDF metadata, DOI regex, DOI lookup (short timeout; on failure the PDF metadata is kept), title fallback to the first top-level heading. Phase 2: first-page LLM extraction (fast tier) when no DOI is confirmed; it fills title, authors, year, and venue, never the DOI, and on failure the PDF metadata is kept (D-068). | P1/P2 |
| FR-05 | Document Parsing | The system shall extract text with page-level provenance and section structure (headings); PDFs without a text layer shall be rejected as scanned. | P1 |
| FR-06 | Chunking | The system shall produce section-aware chunks (target ~350–450 tokens measured with the embedding model's tokenizer, ~12% overlap) carrying document, page range, section, and content-hash metadata. | P1 |
| FR-07 | Embedding | The system shall embed chunks with the configured embedding model and record the model name and version per chunk. | P1 |
| FR-08 | Workspace Isolation | The Retrieval Service shall only return chunks from documents linked to the active workspace; the filter shall be enforced in the data-access query, not by agent instructions. | P1 |
| FR-09 | Corpus-Only Q&A | The system shall answer questions using only workspace evidence in Corpus Only mode. | P2 |
| FR-10 | Evidence Sufficiency | The system shall assess whether retrieved evidence is sufficient per sub-question. | P2 |
| FR-11 | Abstention | The system shall abstain, fully or per sub-question, when evidence is insufficient, and state what the corpus does cover. | P2 |
| FR-12 | Claim Verification | The system shall extract claims from each answer and assign each a status: supported, partially supported, unsupported, or uncertain. | P2 |
| FR-13 | Citation Traceability | Every factual claim shall cite evidence traceable to document, page, section, and chunk; the UI shall open the source passage highlighted. | P2/P3 |
| FR-14 | Human Approval | The system shall request explicit approval before using external sources or general knowledge, explaining why the corpus is insufficient. | P2 |
| FR-15 | External Research | After approval, the system shall search permitted scholarly APIs and web search, and label external evidence distinctly. | P5 |
| FR-16 | Related Paper Discovery | The system shall recommend papers related to the workspace topic profile or a selected paper, with a relevance explanation and similarity score. | P5 |
| FR-17 | Paper Import | The system shall import discovered papers that have a legally accessible open-access PDF; otherwise it shall save metadata and link only. | P5 |
| FR-18 | Multi-Paper Synthesis | The system shall synthesize findings across papers while preserving per-claim provenance and avoiding unsupported generalization. | P4 |
| FR-19 | Literature Comparison | The system shall produce structured comparison tables (objective, methodology, materials, setup, findings, limitations) for selected papers, each cell cited. | P4 |
| FR-20 | Contradiction Detection | The system shall flag potential contradictions between papers, showing both passages and the contextual conditions that may explain them. | P4 |
| FR-21 | Research Gap Analysis | The system shall support corpus-based gap analysis (P4) and, with approval, field-level gap analysis using external literature (P5), clearly separated and labeled as potential findings. | P4/P5 |
| FR-22 | Document Compatibility | The system shall score each upload against the workspace topic profile and warn before ingestion when compatibility is below threshold ([Import anyway] [Move to another workspace] [Cancel]). | P1 |
| FR-23 | Workspace Merge Analysis | The system shall analyze topic compatibility, duplicates, and per-document fit before merging two workspaces. | P6 |
| FR-24 | Merge Override | The user shall be able to proceed with a merge despite warnings; merge shall be non-destructive (creates a new combined workspace; source workspaces remain unchanged). | P6 |
| FR-25 | Chat History | The system shall store workspace-scoped conversations with messages, mode, claims, and citations. | P2 |
| FR-26 | Research Outputs | The user shall be able to save answers, comparisons, contradictions, gaps, and reviews as saved findings. | P4 |
| FR-27 | Evaluation | The system shall support repeatable benchmark evaluation via a CLI, storing configuration and results. | P2/P8 |
| FR-28 | Observability | The system shall trace agent steps, tool calls, retrieval results, and verification outcomes (LangSmith) and store a summary per run. | P2 |
| FR-29 | MCP Interface | The system shall provide an MCP server exposing workspace listing, workspace search, grounded Q&A, evidence lookup, and paper discovery as tools, subject to the same boundary rules. | P7 |
| FR-30 | Literature Review Mode | The system shall generate a multi-section, cited literature review of a workspace using the deep agent (A6), with all claims passing verification. | P7 |
| FR-31 | Prompt-Injection Handling | Document text, web results, and API content shall be treated as untrusted data and never executed as instructions. | P1/P5 |
| FR-32 | Export | The user shall be able to export saved findings as Markdown and their citations as BibTeX. | P4 |
| FR-33 | Knowledge Graph | On request, the system shall build a per-workspace graph of research entities and the relationships its papers state, in which every node and edge links to supporting passages of papers currently in the workspace, and shall update it incrementally when papers change (Section 9.1). | Implemented, experimental (D-082–D-087): jobs, extraction, validation, build, read API, and graph page; quality below the target, see Section 9.1 |

# 7. Agentic Workflow Requirements

## 7.1 Standard Corpus-Only Workflow

As defined in Section 5.4. Every run shall emit progress events (analyzing, retrieving, verifying, citing, done) over SSE, without exposing hidden chain-of-thought.

## 7.2 Insufficient Evidence Workflow

1. S3 marks one or more sub-questions insufficient.
2. S4 pauses the run and sends an `approval_required` event containing: which sub-questions lack evidence, what the corpus does cover, and the options (search external research, use general knowledge, stay corpus-only).
3. The decision is stored in the approval log and the run resumes from the checkpoint.
4. Declining keeps the run in Corpus Only mode and produces a partial answer or abstention.

## 7.3 Verification Loop

1. A2 generates a draft citing chunk IDs.
2. A3 takes each sentence of the draft that cites passages as one claim (A2 writes one or two closely related facts per sentence).
3. Each claim is scored against short sentence windows of its cited chunks with the NLI model; a claim at or above the supported threshold, with no cited chunk contradicting it, is supported. Every other claim goes to the LLM judge (NLI alone never rejects a claim). All such claims of one draft are judged in a single batched LLM call.
4. Status is assigned (Section 12.2).
5. Unsupported claims are returned to A2 for removal or revision (maximum 2 loops).
6. Remaining unsupported claims are removed; if too little content remains, the system abstains.
7. S5 generates final citations only from validated evidence.

## 7.4 Query Analyzer Rules

- Simple questions shall not be decomposed.
- Maximum 4 sub-questions; comparisons produce one sub-question per entity–attribute pair up to that limit.
- Sub-questions may include synonyms and search keywords but shall not state facts not present in the user question.
- Named papers become metadata filters on retrieval.
- A1 shall use a fast, low-cost model.

# 8. RAG and Knowledge Management Requirements

## 8.1 Ingestion Pipeline

```
Upload → type/size validation → store PDF (Supabase Storage)
  → text-layer check (reject scanned) → parse (PyMuPDF4LLM, Markdown with headings, per page)
  → metadata extraction (PDF metadata + DOI regex + title fallback)
  → DOI enrichment (OpenAlex / Crossref), or first-page LLM extraction when no DOI is confirmed
  → section detection
  → chunking → embedding → index (pgvector + tsvector)
  → topic profile update → status = ready
  → workspace keyword summary refresh (background, S7)
```

Ingestion runs as a background task; status transitions are: `uploaded → parsing → embedding → ready` or `failed` (with reason). At most `INGESTION_CONCURRENCY` documents are ingested at once; others wait in `uploaded`. At startup and every `INGESTION_SWEEP_INTERVAL_MINUTES`, in-progress documents not updated for `INGESTION_STALE_MINUTES` and not being processed by the running instance are marked `failed`; uploading the file again re-ingests it.

## 8.2 Retrieval Pipeline

```
Sub-question → dense search (pgvector exact cosine within the workspace, top 30)
             + lexical search (Postgres full-text, any query term, top 30)
             → Reciprocal Rank Fusion → top 20 candidates → reranker (cross-encoder) → top 8
             → evidence set with scores and provenance
```

All top-k values and thresholds shall be configurable. Dense search is exact: the workspace's chunks are selected first, then ordered by distance, so a small workspace always gets its full top-k (an HNSW scan filters after finding the global nearest neighbours). At the supported scale (NFR-03) this costs a few milliseconds. Lexical search ORs the lexemes of `plainto_tsquery`, so raw user text is never parsed as tsquery syntax. Reranker scores are normalized to [0, 1] (sigmoid of the cross-encoder logit), so sufficiency thresholds do not depend on a model's raw score range.

## 8.3 Chunk Metadata

`chunk_id`, `document_id`, `page_start`, `page_end`, `section`, `chunk_index`, `text`, `token_count`, `content_hash`, `embedding`, `embedding_model`, `tsv` (full-text vector). `page_start` and `page_end` are 1-based PDF page indexes, not the numbers printed on the pages, because the source viewer opens pages by index. Document-level fields (title, authors, year, DOI, source URL) are joined from the document record.

## 8.4 Retrieval Quality Requirements

- Provenance shall be preserved for every retrieved chunk.
- Retrieval quality shall be evaluable independently of generation (Recall@K, MRR).
- Cross-workspace retrieval shall be covered by automated tests (Section 21).

# 9. Research Intelligence Features

| Feature | Requirement |
|---|---|
| Literature Comparison | A4 fills a comparison table for selected papers using per-paper retrieval for each attribute; every cell cites evidence or reads "Not reported". |
| Multi-Paper Synthesis | A4 groups evidence by theme across papers; cross-paper generalizations require evidence from each cited paper. |
| Contradiction Detection | A4 extracts comparable findings per paper on a topic; candidate pairs from different papers are screened with the NLI model for contradiction; the LLM then checks for differing conditions (materials, cell types, concentrations, methods) and labels each as *potential contradiction* or *context-dependent difference*. |
| Semantic Research Knowledge Graph | Implemented as an experimental initial phase (Section 9.1, D-081–D-087). S10 extracts evidence-validated entities and relationships per paper and builds one graph per workspace on request. The earlier evidence-provenance graph was retired (D-078). |
| Corpus Research Gaps | A4 aggregates limitations and future-work sections, recurring unexplored variables, and inconsistent findings across the corpus; each gap links to its evidence. |
| Field-Level Research Gaps | With approval, A4 compares corpus gaps against recent external literature from A5 to indicate whether a gap appears addressed elsewhere; results are labeled external and potential. |

## 9.1 Semantic Research Knowledge Graph (experimental, initial phase; D-081–D-087)

Each workspace can have one knowledge graph of the research entities in its papers and the relationships the papers state between them. Every node and edge is backed by at least one passage of a paper currently in the workspace. The graph is generated only when the user asks for it. It runs as a background job of **S10 Knowledge Graph Service**, which makes bounded LLM calls; it is not an agent.

**Vocabulary (v1, closed set).** Entity types:

| Type | Meaning |
|---|---|
| `concept` | A theory, phenomenon, or idea the paper discusses |
| `method` | A technique, model, algorithm, protocol, or procedure |
| `dataset` | A named dataset, corpus, cohort, or sample collection |
| `metric` | A measure used to evaluate or quantify something |
| `task` | A problem or objective the work addresses |
| `tool` | Software, an instrument, a material, or a reagent used |
| `finding` | One result the paper states about its own work, as a short statement (at most 300 characters) |

Relationship types, with the entity types each side may have and the statement the passage must support:

| Relationship | Source → target | Statement checked |
|---|---|---|
| `uses` | method → method, tool, dataset, concept | "{source} uses {target}." |
| `evaluated_on` | method → dataset | "{source} is evaluated on {target}." |
| `measured_by` | method, task, finding → metric | "{source} is measured by {target}." |
| `addresses` | method → task | "{source} addresses {target}." |
| `compared_with` | method → method (undirected) | "{source} is compared with {target}." |
| `reports` | method, dataset, tool, task → finding | The finding's own statement. |

There are no generic edges (no `related_to`). `improves_on` is deferred until comparisons can be checked for explicit support under comparable conditions. Extraction never creates contradiction edges; contradictions remain A4 records (Section 9).

**Evidence validation.** The LLM reads batches of a paper's passages, labelled `E1`, `E2`, …, and returns entities and relationships. For each relationship it cites one label and quotes the supporting sentence or sentences. A relationship is kept only if all of these hold; otherwise it is rejected (there is no "uncertain" edge):

1. The cited label belongs to the batch.
2. The quote is a verbatim span of that passage (whitespace and case normalized), at most two sentences.
3. Both entities' names appear in the quote itself, not merely somewhere in the passage. A finding instead must be entailed by the quote (rule 6).
4. The entity types are allowed for the relationship (table above); no self-relationships. A quote that names one entity as the other ("these singularities, which we call switch points") states identity, not a relationship, and is rejected. A `uses` target of type concept must appear in the quote as a whole phrase, not cut from a longer one ("Between-the-Eyes" from "Between-the-Eyes area").
5. The LLM marks the relationship as stated by the paper about its own work. Hedged or speculative statements (may, could, future work) and statements attributed to other work are rejected. A deterministic attribution check also reads the quote together with the sentence before it (from the same passage or the end of the previous one; context only, never evidence). It rejects the relationship only on strong signs of other research: background phrasing in the quote ("have been developed", "previous studies"), a cited author's reporting verb ("Smith et al. found"), or a context sentence in which another study reports something ("Wang ... found that", "the report found that") that the quote completes or continues. A quote that marks the paper's own work ("we", "our", "this study", "here", "the proposed") is never rejected by this check, so "the authors", "et al." or a citation marker alone decide nothing; but "the authors" right after a sentence reporting a cited study refers to that study. A paper that calls itself a review (its title, e.g. "Perspectives", "A survey", or its opening passages, e.g. "In this review") keeps a relationship only when the quote is in its own voice ("we", "our", "this review"), because "this study" and "the proposed" in a review usually describe a cited study.
6. The local NLI model scores the quote (premise) against the relationship's statement (hypothesis): entailment at or above `KG_RELATION_ENTAILMENT_SCORE` and contradiction below `KG_RELATION_CONTRADICTION_SCORE`. Both thresholds are provisional until calibrated on a hand-labelled sample.

An entity without a kept relationship is kept only if its name appears in a cited passage. Validation uses no further LLM calls. The number of rejections per rule is stored with each paper's extraction; rejected text is not stored. The UI labels the graph as extracted from the papers and asks the user to check the passages.

**Normalization (conservative).** Entities merge across papers only with the same type and the same normalized name (case, Unicode form, punctuation, plural "s", whitespace). An acronym and its expansion merge only when one passage states both. Findings never merge across papers. There is no embedding or LLM merging in v1. An edge joins two nodes with one relationship type; its support is the set of papers and passages behind it.

**Extraction is per paper and reused.** A paper's extraction is stored per document and extractor version (prompt and schema version). It is reused, with no LLM calls, by every workspace of the same user that contains the paper. Passages under a minimum length and reference-list passages (identified by their content, not only by the section label) are skipped.

**Jobs.** `Generate` and `Update` create a job. A workspace has at most one active job (enforced by a database constraint); starting another returns the active one. Only one graph job calls the LLM at a time across the application.

- *Phase A, extract:* each paper in the workspace without a current extraction is read in batches. A paper's results are committed in one transaction after all its batches. A job interrupted midway through a paper reads that paper again from its start next time; papers fully read are kept, and the UI says so.
- *Phase B, build:* the workspace's nodes and edges are rebuilt from the extractions of its current papers in one transaction, without LLM calls. If it fails, the previous graph stays unchanged.

**Restarts and failures.** No job resumes automatically. A job running in this process is never marked stale. While a job runs, it records a heartbeat every minute, including while it waits for rate-limit capacity or retry backoff. The startup sweep and the periodic sweep fail only queued or running jobs that this process is not running and whose heartbeat is older than `KG_JOB_STALE_MINUTES` (reason `interrupted`). A job also fails with `llm_quota_exhausted` or `budget_exceeded` (the per-job call cap); completed paper extractions are always kept, so Retry or Update continues from them.

**States shown to the user:** empty, queued, generating (paper *k* of *n*, then building), ready, update available, updating, and failed. In the last three, the previous graph stays visible.

**Changes to papers.** The graph records which papers it was built from. When the workspace's ready papers differ, the graph shows "update available". A removed paper's evidence is hidden at once: only passages of papers currently linked to the workspace are shown, and a node or edge left without such evidence is hidden. Relationships still supported by other papers stay, with their remaining evidence. A revised PDF is a new document.

**LLM tier and quota isolation.** Extraction uses a third tier, "graph" (`LLM_GRAPH_PROVIDER`, `LLM_GRAPH_MODEL`, optional `LLM_GRAPH_API_KEY`, its own request and token limits, and its own retries: `LLM_GRAPH_MAX_RETRIES`, default 4, with exponential backoff from `LLM_GRAPH_RETRY_BASE_SECONDS`, default 10 s, because hosted overloads last minutes and no user is waiting). It has its own rate limiter, never shared with the fast or strong tier, and a per-job call budget, so a graph job cannot use up the quota interactive Q&A needs. The tier defaults to `fake`, so the feature is off until it is configured. The model is chosen in a structured-output test against these criteria:

1. Structured output: at least 19 of 20 sample batches, from papers in at least three fields, validate on the first attempt.
2. A provider quota separate from the fast and strong tiers (a different model, or the same model under another key).
3. Free-tier capacity for at least three full builds of a 10-paper workspace a day, and enough tokens per minute for one batch.
4. An existing provider (Groq or Gemini); any other provider needs approval, because it would receive document text.
5. Quality target: at least 0.8 precision of kept relationships on a hand-checked sample (measured in the quality phase).

**Interface.** A dedicated, wide graph page per workspace (`/workspaces/{id}/graph`, React Flow with a left-to-right dagre layout). It shows the job state and progress from the backend, so a refresh or a return to the page resumes it. Connected entities are shown by default; entities without a relationship are kept in the data, counted, and shown on request. Clicking a node or edge (or pressing Enter on it) opens its evidence: the papers, pages, sections, and verbatim quotes, each of which opens the source viewer with the passage highlighted, and a note that relationships are extracted by a model and must be checked against their passages. A searchable, sortable relationship list is the non-visual alternative.

**Current status and limitations (experimental, 2026-10-20).** The feature works end to end and is presented as an initial phase:

- *Quality is below the target.* On one 3-paper dev workspace (rules.v3), 7 relationships were kept, about 3 clearly correct and 4 loose on hand review (one reviewer, unverified); target 5 (0.8 precision) is not met or formally measured.
- *Graphs are sparse.* Most entities have no kept relationship (116 nodes, 7 edges in that run), and review papers contribute entities but no relationships, by design.
- *Entity merging is exact-name only,* so related entities across papers rarely connect; that run had no node shared by two papers.
- *The extractor is provisional* (`gemma-4-26b-a4b-it`, prompt v2); the relationship-judge prototype was not adopted (D-085).
- *Filters by entity type and by number of supporting papers are not built;* the page offers search, sort, and the isolated-entity toggle.
- *Generation is off unless the graph tier is configured* (`LLM_GRAPH_PROVIDER` defaults to `fake`); starting a job then answers 503 and the page says so.

**Future scope (not implemented):** better semantic extraction (a chosen extraction model, recall beyond quotes that name both entities); relationship accuracy measured on a verified hand-labelled sample against target 5; entity consolidation (acronyms, aliases, embedding-assisted merges with evidence); cross-paper connections; filters by entity type and support; and the graph re-skin in the UI redesign (D-088).

# 10. External Research and Human-in-the-Loop

## 10.1 External Sources

| Source | Use |
|---|---|
| OpenAlex | Primary scholarly search, metadata, related works, concepts. No key required (polite-pool email configured). |
| Semantic Scholar | Paper recommendations for similar papers (API key optional; rate limits respected). |
| arXiv API | Preprint search and open PDFs. |
| Europe PMC | Biomedical literature search and open-access full texts. |
| Unpaywall | Legal open-access PDF location by DOI. |
| Crossref | DOI metadata fallback. |
| Tavily | General web search, used only in approved Corpus + Web mode. |

All external calls shall go through provider interfaces with timeouts, retries (max 2), and response caching: scholarly APIs through a `ScholarlySearchProvider`, and Tavily through a separate `WebSearchProvider`. The web search provider is only passed to code that holds a Corpus + Web approval, so the approval gate is enforced by construction as well as by the run state.

## 10.2 Related Paper Recommendation

```
Workspace topic profile (or selected paper)
  → A5 builds queries → OpenAlex + Semantic Scholar recommendations + arXiv/Europe PMC
  → deduplicate (DOI, normalized title) → exclude papers already in workspace
  → rank by embedding similarity (abstract vs topic profile), recency, citation count
  → relevance explanation per paper (from abstract + topic profile)
  → user options: [View] [Import (if open access)] [Open source] [Save for later]
```

## 10.3 Human-in-the-Loop Rules

- External search shall not occur in Corpus Only mode without approval.
- General knowledge shall not be used without approval.
- The approval prompt shall explain why the corpus is insufficient.
- The user may decline and remain corpus-only.
- External evidence and general-knowledge statements shall be labeled in the final response.
- Every approval decision shall be logged (who, when, run or conversation, option chosen).
- Selecting Corpus + Web as the mode of a conversation (directly or through the workspace `default_mode`) is logged as an approval for that conversation; the QA graph copies it into the run state. General Knowledge approval is never carried over and is requested per request.

# 11. Workspace Management

## 11.1 Workspace Structure

```
Workspace
 ├── Documents (linked, many-to-many)
 ├── Conversations
 ├── Topic Profile
 ├── Claims / Evidence
 ├── Saved Findings
 └── Research Gaps / Contradictions
```

## 11.2 Document Compatibility

Before a document is linked to a workspace, S7 compares the document embedding (normalized mean of its first `COMPATIBILITY_CHUNKS` chunks, i.e. abstract and first section) with the workspace topic profile (the centroid of its ready documents' embeddings, updated incrementally when a document becomes ready, is linked, or is removed). For an upload, `POST /workspaces/{id}/documents/compatibility` parses only the first `COMPATIBILITY_MAX_PAGES` pages and stores nothing; the upload then records the user's choice (`override`), and the score is stored when the document is ready. Linking an existing ready document (`PUT`) is checked in the same request and answered 409 `compatibility_warning` unless `override=true`. If cosine similarity is below the configured threshold (`COMPATIBILITY_THRESHOLD`, 0.83 for bge-small, D-060), the user sees:

> **Potentially unrelated document** — Workspace: Tissue Engineering · Document: Stock Market Prediction.
> [Import anyway] [Move to another workspace] [Cancel]

For an empty workspace (no profile yet), the check is skipped and the first documents initialize the profile.

The profile's keywords and summary (shown with the workspace) come from one strong-tier LLM call over the titles and first chunks of the `TOPIC_SUMMARY_MAX_DOCUMENTS` most recently added ready documents. They are refreshed in the background after a document becomes ready, is linked, or is removed; an empty workspace is cleared without a call, and a failed call keeps the previous summary (D-068).

## 11.3 Workspace Merge

- S8 computes profile similarity, per-document fit to the other workspace, and duplicates by content hash and DOI.
- The merge report shows overall compatibility, flagged documents, and duplicates.
- The user retains final control; merge creates a new workspace linking the union of documents (deduplicated) and a recomputed topic profile. Source workspaces and their conversations are unchanged.

# 12. Trust, Grounding and Guardrails

## 12.1 Grounding Policy

The system does not claim zero hallucination. It implements measurable controls that reduce unsupported claims and provide evidence traceability.

## 12.2 Claim-Level Verification

| Claim Status | Meaning | System Action |
|---|---|---|
| Supported | Evidence entails the claim. | Keep with citation. |
| Partially supported | Evidence supports part of the claim or needs qualification. | Qualify or rewrite; cite. |
| Unsupported | No adequate evidence. | Remove or revise; abstain if needed. |
| Uncertain | Evidence is ambiguous or conflicting. | Keep only with an explicit uncertainty note and both evidence passages. |

## 12.3 Citation Requirements

- Citations shall reference only chunks present in the run's evidence set (validated by S5).
- Page and section shall be shown when available.
- Workspace, external, and general-knowledge sources shall be visually distinct.
- Citation correctness and completeness shall be evaluated separately.

# 13. Non-Functional Requirements

| ID | Category | Requirement |
|---|---|---|
| NFR-01 | Performance | First SSE progress event within 2 s of request (excluding hosting cold start). Corpus-only answer with verification: median ≤ 25 s, 90th percentile ≤ 45 s on the deployed free tier. |
| NFR-02 | Ingestion | A 20-page text PDF shall reach `ready` within 90 s on the deployed tier. |
| NFR-03 | Capacity | Supported target: 50 documents per workspace, 20 workspaces per user. |
| NFR-04 | Reliability | Failures in any external API shall degrade gracefully (corpus-only continues) with a user-readable message. |
| NFR-05 | Traceability | Every answer shall store its run ID, mode, evidence set, claims, and citations. |
| NFR-06 | Maintainability | Layering (Section 5.1) shall be respected; agents, services, and providers shall be independently unit-testable with fake providers. |
| NFR-07 | Observability | 100% of agent runs traced in LangSmith; run summaries stored in `agent_runs`. |
| NFR-08 | Security | No user can read or modify another user's workspaces, documents, or conversations (verified by automated tests). |
| NFR-09 | Privacy | Uploaded documents are stored in a private Storage bucket, accessed only via short-lived signed URLs. |
| NFR-10 | Extensibility | LLM, embedding, reranker, NLI, parser, and search providers shall be replaceable through interfaces and configuration only. Exception: an embedding model with a different dimension requires a new migration and re-indexing of all chunks. |
| NFR-11 | Usability | Knowledge mode, source type, uncertainty, and citations shall be visible on every answer. |
| NFR-12 | Reproducibility | Every evaluation run shall record model IDs, prompt versions, configuration, and dataset version. |
| NFR-13 | Cost | The system shall run on free tiers for development, except the backend Hugging Face Space, which needs PRO (about ₹800/month, D-043). Paid LLM credit may be used for the Phase 8 benchmark runs and the demonstration, with demo-only API keys (D-070). LLM calls per corpus-only question should not exceed 10 on average (measured in Phase 2). |

# 14. Data Requirements and Data Model

## 14.1 Core Entities

| Entity | Key Fields |
|---|---|
| users | managed by Supabase Auth (`auth.users`) |
| workspaces | id, user_id, name, description, default_mode (corpus_only / corpus_web), archived, created_at |
| topic_profiles | workspace_id, centroid_embedding, keywords, summary, updated_at |
| documents | id, user_id, title, authors, year, venue, doi, source (upload/import), source_url, storage_path, page_count, content_hash, status, error, created_at |
| workspace_documents | workspace_id, document_id, added_at, compatibility_score, override (bool) |
| chunks | id, document_id, chunk_index, page_start, page_end, section, text, token_count, content_hash, embedding vector(384), embedding_model, tsv |
| conversations | id, user_id, workspace_id, title, mode (corpus_only / corpus_web), created_at, updated_at |
| messages | id, conversation_id, role, content, mode (corpus_only / corpus_web / general_knowledge), run_id, created_at |
| claims | id, message_id, position, text, status, support_score |
| evidence | id, claim_id, chunk_id (null once the document is deleted; external_source_id from Phase 5), score |
| citations | id, claim_id, source_type (workspace/external/general), document_id, chunk_id (both null once the document is deleted; external_source_id from Phase 5), snapshot: document_title, page_start, page_end, section, quote |
| external_sources | id, provider, external_id, doi, title, authors, year, abstract, url, oa_pdf_url, cached_at |
| approvals | id, run_id (nullable), conversation_id, user_id, reason, options, decision, decided_at |
| api_tokens | id, user_id, name, token_hash, created_at, last_used_at, revoked_at (plaintext token shown once at creation, never stored; Phase 7) |
| saved_findings | id, workspace_id, type (answer/comparison/contradiction/gap/review), title, content_json, created_at |
| contradictions | id, workspace_id, claim_a, claim_b, evidence_refs, context_note, label |
| research_gaps | id, workspace_id, scope (corpus/field), description, evidence_refs |
| kg_jobs (migration 0008, D-081) | id, user_id, workspace_id, kind (generate/update), status (queued/running/completed/failed), phase, documents_total, documents_done, current_document_id, llm_calls, input_tokens, output_tokens, call_budget, error_code, error_message, extractor_version, created_at, started_at, heartbeat_at, finished_at; at most one queued or running job per workspace |
| kg_document_extractions (migration 0008) | id, user_id, document_id, extractor_version, status, chunks_considered, llm_calls, tokens, rejected_counts, created_at; unique (document_id, extractor_version) |
| kg_entity_mentions (migration 0008) | id, extraction_id, document_id, chunk_id, entity_type, surface_text, normalized_key, quote |
| kg_relation_mentions (migration 0008) | id, extraction_id, document_id, chunk_id, source_mention_id, target_mention_id, relation_type, quote, entailment_score |
| kg_graphs (migration 0008) | workspace_id, user_id, built_by_job_id, built_at, source_fingerprint, node_count, edge_count |
| kg_nodes / kg_edges (migration 0008) | per workspace: entity type and label (nodes); source node, target node, relationship type (edges); supporting mentions via kg_node_mentions and kg_edge_mentions |
| merge_reports | id, source_workspace_ids, result_workspace_id, report_json, decision |
| agent_runs | id, user_id, workspace_id, conversation_id, workflow, status, latency_ms, llm_calls, tokens, trace_url, error, created_at, finished_at |
| eval_runs / eval_results | id, condition, config_json, dataset_version, metrics_json, created_at / per-question outputs and scores |

Schema changes shall be made only through Alembic migrations. Alembic (including autogenerate) shall ignore the Supabase-managed `auth` and `storage` schemas and the LangGraph checkpoint tables, which the checkpointer library creates and manages. The `vector` (pgvector) extension is enabled in the first Phase 1 migration. Autogenerate reflects only the `public` schema, so all Supabase-managed schemas (`auth`, `storage`, `realtime`, `vault`, `graphql`, `extensions`, …) are out of scope. All constraints and indexes have deterministic names from the metadata naming convention (`pk_`, `fk_`, `uq_`, `ix_`, `ck_` prefixes). Migrations are run explicitly (`alembic upgrade head`), never at application startup.

The backend is the only database client. The Supabase Data API (PostgREST) is disabled, and automatic RLS is enabled for new tables in `public`. The backend connects as the table owner, so RLS does not restrict it, and tables need no RLS policies.

## 14.2 Storage Strategy

- Supabase Postgres: all relational data, pgvector embeddings (HNSW index), full-text vectors, LangGraph checkpoints.
- Supabase Storage: uploaded and imported PDFs (private bucket).
- Local disk: model weights baked into the Docker image; no persistent state on the backend container.

# 15. Technology Stack

## 15.1 Stack

This stack is the default. Specific libraries and models are flexible defaults: an alternative may be adopted after a proposal is approved by the team, recorded in `docs/DECISIONS.md`, and reflected in this SRS in the same commit (see CLAUDE.md §1a).

| Layer | Technology | Notes |
|---|---|---|
| Frontend | Next.js (App Router) + React + TypeScript | Deployed on Vercel. |
| UI | Tailwind CSS + shadcn/ui; `motion` for animation | Consistent components; visual and motion rules in `docs/DESIGN.md` (D-074). |
| PDF viewer | react-pdf (pdf.js) | Page navigation and evidence highlighting. |
| Graph view | React Flow (`@xyflow/react`) with `@dagrejs/dagre` layout | Semantic Research Knowledge Graph page (experimental, D-081–D-087). |
| API client | openapi-typescript | Types generated from the backend OpenAPI schema. |
| Backend | FastAPI + Python 3.11, managed with uv | REST + SSE. The uv version is pinned by `[tool.uv] required-version` in `backend/pyproject.toml`; CI installs that version. |
| Validation / config | Pydantic v2, pydantic-settings | All agent outputs and settings. |
| Database access | SQLAlchemy 2 + psycopg + pgvector + Alembic | Repository layer. |
| Database / storage / auth | Supabase (Postgres + pgvector, Storage, Auth) | Single managed backend for persistence. |
| Orchestration | LangGraph (+ Postgres checkpointer) | Fixed graphs with conditional edges, `interrupt()` for HITL. |
| Deep agent | deepagents (LangChain) | Literature review mode (A6). |
| LLM access | LangChain chat model integrations behind an `LLMProvider` interface | Two tiers, each with its own provider and model setting: "fast" (default: Groq `openai/gpt-oss-20b`, for A1 and similar calls) and "strong" (default: Gemini `gemini-3.5-flash-lite`, for synthesis and judging; chosen for its free-tier daily quota). Exact model IDs live in configuration. The app retries failed calls (max 2, backoff) and rate-limits each model (requests and tokens per minute, requests per day); an exhausted daily quota fails at once with a user-readable message. A `demo` provider returns canned replies marked as demo output for key-free local runs and is refused in production (D-062). A third tier, "graph", serves knowledge graph extraction only (D-081, D-083, Section 9.1): its own model, optional key, and rate limiter, never shared with the fast and strong tiers; off (`fake`) until a model is chosen. |
| Embeddings | BAAI/bge-small-en-v1.5 (384-dim) via sentence-transformers, local (D-050) | Fixed dimension in schema; changing it needs a migration and re-indexing (NFR-10). |
| Reranker | cross-encoder/ms-marco-MiniLM-L-6-v2, local (D-051) | |
| NLI (verification) | DeBERTa-v3-based NLI cross-encoder (default `cross-encoder/nli-deberta-v3-xsmall`, D-067), local | First-pass claim checking. |
| PDF parsing | PyMuPDF4LLM (default); Docling as optional provider | Markdown with headings and page chunks. |
| Scholarly APIs | OpenAlex, Semantic Scholar, arXiv, Europe PMC, Unpaywall, Crossref | Section 10.1. |
| Web search | Tavily | Approved mode only. |
| MCP | Official MCP Python SDK (FastMCP) | Section 16.3. |
| Observability | LangSmith | Tracing. |
| Evaluation | Ragas + custom metrics scripts | Section 17. Code in `backend/eval/`; Ragas installed in the backend's `eval` dependency group. Ragas calls go through the provider interfaces; the judge model is `EVAL_JUDGE_MODEL` (D-069). |
| Testing | pytest, pytest-asyncio; Playwright for E2E | |
| Lint/format | ruff, mypy (backend); ESLint, Prettier (frontend) | Enforced in CI. |
| CI | GitHub Actions | On every push: backend `ruff check`, `ruff format --check`, `mypy`, unit tests; frontend lint and build. Integration tests are not run in CI (they need secrets). Actions are pinned to commit SHAs; Dependabot opens weekly update PRs for them into `dev`. |

## 15.2 Environments

| Environment | Backend | Frontend | Data |
|---|---|---|---|
| Local development | `uv run uvicorn` on developer machine (no Docker needed) | `npm run dev` | Supabase **dev** project |
| Production / demo | Docker container on Hugging Face Spaces | Vercel | Supabase **prod** project |

## 15.3 Deployment

- The backend Dockerfile shall download model weights at build time so the container starts without network model downloads.
- Provider configuration is validated at startup. A `PRELOAD_MODELS` setting (true in the Docker/production configuration, false by default for local development) controls whether local model weights are loaded at startup or on first use, so `uvicorn --reload` restarts stay fast locally.
- The container is stateless; all persistence is in Supabase, so restarts and redeploys lose no data.
- Secrets (API keys, Supabase keys) are configured as host environment secrets, never committed.
- Allowed CORS origins (for example the Vercel frontend URL) come from configuration, never hard-coded.
- The backend Space needs Hugging Face PRO (Docker Spaces require it since July 2026) and uses Protected visibility: the app URL is public, the Space files are private (D-043).
- The team creates all hosting and service accounts (Supabase dev/prod, Vercel, Hugging Face Spaces, GitHub secrets). Step-by-step setup instructions are written in `docs/SETUP.md` during the Phase 0 deploy task.
- A skeleton deployment (health endpoint + frontend page) shall be live by the end of Phase 0 and redeployed at the end of each phase.
- Known free-tier behaviour (container sleep after inactivity, project pausing after long inactivity) shall be documented in the README with wake-up steps before demos.

# 16. API and Integration Requirements

## 16.1 REST Endpoints (prefix `/api/v1`)

| Group | Endpoints |
|---|---|
| Health | `GET /health` (liveness, no dependencies), `GET /health/ready` (readiness, checks the database connection) |
| Workspaces | `GET/POST /workspaces`, `GET/PATCH/DELETE /workspaces/{id}` (`PATCH` with `archived=true` archives; `DELETE` permanently deletes; responses include the S7 `keywords` and `summary`), `POST /workspaces/merge/analyze`, `POST /workspaces/merge` |
| Documents | `POST /workspaces/{id}/documents` (upload), `POST /workspaces/{id}/documents/compatibility`, `GET /workspaces/{id}/documents`, `GET /documents/{id}`, `GET /documents/{id}/file` (signed URL), `PUT /workspaces/{id}/documents/{doc_id}` (link an existing document, e.g. a duplicate upload), `DELETE /workspaces/{id}/documents/{doc_id}` |
| Chat | `GET/POST /workspaces/{id}/conversations`, `GET /conversations/{id}/messages` (with each answer's claims and citations), `POST /conversations/{id}/messages` (SSE stream), `GET /runs/{run_id}` (status; a paused run's approval request), `POST /runs/{run_id}/resume` (approval decision) |
| Retrieval | `POST /workspaces/{id}/retrieval/debug` (every S2 stage with scores and timings; owner only) |
| Evidence | `GET /chunks/{id}` (deferred, D-072), `GET /messages/{id}/claims` |
| Research | `POST /workspaces/{id}/compare`, `/synthesize`, `/contradictions`, `/gaps` |
| Knowledge graph (D-081, D-082) | Implemented: `POST /workspaces/{id}/knowledge-graph/jobs` (202 starts Generate or Update; 200 returns the active job; 409 `no_ready_documents`; 503 until extraction is configured), `GET /workspaces/{id}/knowledge-graph/jobs/{job_id}`, `GET /workspaces/{id}/knowledge-graph` (state, staleness, active and last job, the most-supported nodes and the edges between them), `GET /workspaces/{id}/knowledge-graph/nodes/{node_id}/evidence`, `GET /workspaces/{id}/knowledge-graph/edges/{edge_id}/evidence` (live passages of current papers, shaped like citations for the source viewer) |
| Discovery | `GET /papers/search` and `POST /workspaces/{id}/import` (implemented, D-077); `POST /workspaces/{id}/discover`, `GET /papers/{id}/similar` (Phase 5) |
| Reviews | `POST /workspaces/{id}/reviews` (SSE stream) |
| Findings | `GET/POST /workspaces/{id}/findings`, `GET /workspaces/{id}/findings/export?format=md|bibtex` |
| API tokens | `GET/POST /api-tokens`, `DELETE /api-tokens/{id}` (Phase 7; used by the MCP server) |
| Evaluation | CLI only in Release 1.0 (from `backend/`: `uv run --group eval python -m eval.run --condition ...`) |

All endpoints except the health endpoints require a valid Supabase JWT (or, for MCP calls, a valid API token); ownership is checked in the repository layer. A resource that does not exist or belongs to another user returns 404 (never 403), so its existence is not revealed.

## 16.2 Streaming Events

SSE event types: `status` (stage name), `approval_required`, `claims`, `citations`, `error`, `done`. Each event's `data` is JSON with a `type` field naming the event. There is no `token` event: A3 may remove or revise draft claims, so the answer is sent whole after verification (D-036). A request rejected before the run starts (401, 404, 409, 422, 503) gets a JSON error response, not a stream.

## 16.3 MCP Server

A separate `mcp_server/` package using FastMCP, run locally over stdio, authenticated with a user-generated API token (stored only as a hash in `api_tokens`; revocable). Tools: `list_workspaces`, `search_workspace`, `ask_grounded` (Corpus Only), `get_evidence`, `discover_papers`. All tools call the backend REST API; boundary rules are enforced by the backend, not by the MCP server.

# 17. Evaluation and Research Methodology

## 17.1 Core Research Question

Can an agentic evidence-verification architecture improve factual grounding and citation reliability for research assistants operating over user-defined scientific corpora, compared with conventional RAG?

## 17.2 Experimental Conditions

| Condition | Description |
|---|---|
| C1 LLM-only | Question sent to the LLM with no retrieval. |
| C2 Conventional RAG | Dense retrieval (top 8) + single generation prompt with "answer only from context". |
| C3 RAG + Hybrid + Rerank | C2 with hybrid retrieval and reranking. |
| C4 Agentic RAG | C3 + Query Analyzer + sufficiency gate + abstention. |
| C5 Full system | C4 + verification loop + citation validation. |
| Ablations | C5 without A1 decomposition; C5 without reranker. |

## 17.3 Metrics

| Metric | Category | Definition |
|---|---|---|
| Recall@K, MRR | Retrieval | Against gold evidence chunks. |
| Faithfulness | Generation | Ragas faithfulness. |
| Answer relevance | Generation | Ragas answer relevancy. |
| Citation correctness | Citation | Share of citations whose chunk supports the claim (judge + human subset). |
| Citation completeness | Citation | Share of factual claims carrying a citation. |
| Unsupported claim rate | Grounding | Unsupported claims / total claims (judge + human subset). |
| Abstention accuracy | Grounding | Correct abstentions on unanswerable questions; false abstentions on answerable ones. |
| Verifier agreement | Trust layer | Accuracy and Cohen's kappa of A3 vs human labels. |
| Contradiction detection | Research | Precision/recall on the contradiction set. |
| Latency, LLM calls, tokens | System | Per question. |

The evaluation judge model shall be a different model from the one used by A3 to avoid circular evaluation.

## 17.4 Benchmark

- Corpus: 15–20 open-access tissue-engineering papers (so the benchmark can be published with the repository).
- Questions: at least 100 — about 50 single-paper answerable, 20 multi-paper, 10 comparison, 20 unanswerable (plausible but not covered by the corpus).
- Gold evidence chunk labels for at least 40 questions.
- Verifier set: at least 150 human-labeled claim–evidence pairs.
- Contradiction set: at least 10 pairs; constructed from real passages if natural contradictions are scarce, and documented as such.
- Dataset stored in `backend/eval/data/` as versioned JSONL. Each item has a `type` (single, multi, comparison, unanswerable); single-paper items give the gold passage as `paper`/`page`/`snippet`, multi-paper and comparison items list theirs in `evidence` (D-069).
- The dataset fixes a calibration split and a test split. Thresholds and any tuning use only the calibration split; results are reported on the test split only (D-063).
- Each item records `drafted_by` (claude or human) and `verified_by` (reviewer name or empty). Reports count only verified items and state the drafted/verified split. Unanswerable questions are written or reviewed by the team.

# 18. Security, Privacy and Ethical Requirements

- All data access shall be scoped to the authenticated user in the repository layer.
- The database is reachable only through the backend: the Supabase Data API is disabled, and row-level security is enabled on every table in `public` as defense in depth (Section 14.1). Authorization is the backend's job; RLS is a second layer, not a replacement.
- Workspace isolation shall be enforced in SQL (FR-08), with automated leakage tests.
- Document text, web results, and API responses are untrusted: they are wrapped in clearly delimited data blocks in prompts, agents are instructed never to follow instructions found inside them, and tool calls are never triggered by document content.
- Uploaded files are stored privately and served through signed URLs. The backend accesses Storage with the Supabase secret key, which is used server-side only.
- The backend verifies Supabase JWTs against the project's JWKS URL.
- Secrets are stored only in environment configuration.
- Only open-access or legally accessible full texts are imported; otherwise metadata and links only.
- Generated research findings, gaps, and contradictions are labeled as potential findings requiring expert judgment.
- Uncertainty and conflicting evidence are preserved rather than forced into a single conclusion.

# 19. UI/UX Requirements

## 19.1 Screens

| Screen | Purpose | Phase |
|---|---|---|
| Login / Sign-up | Supabase Auth | P3 |
| Workspace list | Create, rename, archive, merge | P3 / P6 |
| Document library | Upload, status, compatibility warnings, metadata | P3 |
| Research chat | Mode selector, streamed progress, answers with claim status and citations, approval prompts | P3 |
| Source viewer | PDF page with highlighted evidence passage | P3 |
| Analysis | Comparison tables, synthesis, contradictions, gaps | P4 |
| Knowledge graph | Generate and update the workspace graph with job progress; search and sort relationships; show isolated entities on request; select a node or edge to see its papers and passages (experimental, D-087; filters by entity type and support are future scope) | Cross-phase |
| Discover | Search and open-access import (implemented, D-077); related and similar papers | P5 |
| Literature review | Run and view deep-agent reviews | P7 |
| Saved findings | View, export | P4 |

## 19.2 Trust Indicators

- Persistent knowledge-mode badge (Corpus Only / Corpus + Web / General Knowledge).
- Source labels distinguishing workspace, external, and general-knowledge content.
- Claim status indicators (supported / partial / uncertain).
- Insufficient-evidence notices and approval prompts.
- Compatibility warnings on upload.

# 20. Error Handling and Edge Cases

| Scenario | Expected Behavior |
|---|---|
| Corrupt PDF | Status `failed` with reason; allow re-upload. |
| Scanned PDF (no text layer) | Reject with explanation (OCR is future scope). |
| Duplicate upload | Detect by content hash (unique per user, so concurrent uploads also resolve to one document); offer to link the existing document instead. |
| No relevant chunks | Abstain or trigger the approval workflow. |
| Conflicting evidence | Present as uncertain with both passages. |
| External API unavailable / rate-limited | Continue corpus-only; report which source failed. |
| Paper not open access | Show metadata and link; do not claim import succeeded. |
| Unrelated upload | Compatibility warning before linking. |
| Merge mismatch | Show merge report and require confirmation. |
| LLM provider failure | Retry up to 2 times with backoff; then user-readable error; run marked failed. |
| Approval never answered | Run stays paused; resumable from conversation history. |
| Unsupported file type | Reject with supported-format guidance. |
| Backend cold start | Frontend shows a "waking up server" state instead of an error. |

# 21. Development and Testing Strategy

## 21.1 Repository Structure

```
/
├── CLAUDE.md                 # rules for AI coding agents
├── docs/
│   ├── SRS.md                # this document
│   ├── PROGRESS.md           # backend phase + frontend track, tasks, measurements, known issues
│   ├── DECISIONS.md          # architecture decision log
│   └── SETUP.md              # account and deployment setup steps (Phase 0 deploy task)
├── backend/
│   ├── app/
│   │   ├── api/              # routers, dependencies, auth
│   │   ├── agents/           # A1–A6 and their output schemas
│   │   ├── prompts/          # versioned .md prompts: agents/, services/
│   │   ├── graphs/           # LangGraph graph definitions
│   │   ├── services/         # S1–S9 (and schemas for their bounded LLM calls)
│   │   ├── providers/        # LLM, embedding, reranker, NLI, parser, search interfaces + implementations
│   │   │   └── fakes/        # deterministic fakes, selectable via config (e.g. LLM_FAST_PROVIDER=fake)
│   │   ├── repositories/     # all DB and storage access
│   │   ├── models/           # SQLAlchemy models
│   │   ├── schemas/          # API request/response schemas
│   │   └── core/             # config, logging, errors
│   ├── alembic/
│   ├── eval/ (data/, conditions/, prompts/, run.py, reports/)
│   ├── tests/ (unit/, integration/)
│   └── Dockerfile
├── frontend/                 # Next.js app
└── mcp_server/
```

## 21.2 Testing Levels

- Unit tests with fake providers (no network) for parsing, chunking, retrieval fusion, sufficiency thresholds, citation validation, agent output parsing, graph routing. Tests use the same fakes as local development (`app/providers/fakes/`), so neither tests nor CI need API keys.
- Integration tests (marked, run against the dev Supabase project) for ingestion → retrieval → Q&A. They are run manually, not in CI, because they need secrets.
- Security tests: cross-user access and cross-workspace retrieval leakage.
- Adversarial tests: prompt injection inside a PDF, unanswerable questions, unrelated uploads.
- End-to-end tests (Playwright): upload → ask → open citation.
- Benchmark evaluation (Section 17).

## 21.3 AI Coding Agent Governance

- Work proceeds one phase at a time (Section 22); an agent implements only the current phase. `docs/PROGRESS.md` tracks two lines: the current backend phase and the frontend track (which runs in parallel from Phase 3).
- Each phase is split into task branches, each with its own short plan approved before implementation when it touches more than ~5 files or any shared interface.
- Each phase ends with passing tests, an updated `docs/PROGRESS.md`, and a deployment.
- Rules are either fixed or flexible defaults (CLAUDE.md §1a). Changes to flexible defaults (libraries, models, thresholds, etc.) and any deviation from this SRS are proposed first, then, once approved, recorded in `docs/DECISIONS.md` and reflected in this SRS in the same commit.
- Applied migrations are never edited; new migrations are created instead.
- Tests are never deleted or weakened to make a build pass.
- All AI-generated code is reviewed and understood by a team member before merging.
- Git workflow: `main` holds tested phase releases; `dev` is the integration branch; nobody commits directly to either. Each task uses a short-lived branch from `dev` named `p<phase>/<short-task-name>`, merged into `dev` through a Pull Request with passing tests. At a phase gate, `dev` is merged into `main` through a Pull Request and `main` is tagged `phase-N-done`. Small commits with conventional messages.

# 22. Implementation Phases

Phases are ordered by dependency. A phase is complete only when its exit criteria pass. Frontend work (P3) runs in parallel with backend phases once P1 API contracts exist. Day estimates assume a 12-day schedule and parallel team tracks.

## Phase 0 — Project Foundation (Day 1)

- **Scope:** `docs/PROGRESS.md` and `docs/DECISIONS.md` created (first task); monorepo structure (21.1); uv backend; Next.js frontend; pydantic-settings config (including CORS origins and provider selection) and `.env.example`; provider interfaces with fake implementations in `app/providers/fakes/`, selectable through config; logging; error model; `GET /health` and `GET /health/ready`; unit tests for `/health` and config loading; `gen:api` set up and used by the frontend health call; Alembic initialized (excluding `auth`, `storage`, and checkpoint tables; no domain tables yet); CI (Section 15.1); skeleton deployment (Vercel + Hugging Face Spaces) with setup instructions in `docs/SETUP.md`. The team creates Supabase dev and prod projects and all hosting accounts. Team starts collecting the benchmark corpus.
- **Work split:** one task branch per area, each with its own plan (listed in `docs/PROGRESS.md`).
- **Exit criteria:** deployed frontend calls deployed `/health` successfully through the generated API client; deployed `/health/ready` reports the database reachable; CI green with all checks in Section 15.1; `uv run pytest` passes, including the `/health` and config-loading tests.

## Phase 1 — Ingestion, Retrieval, Workspaces (Days 2–3)

- **Scope:** FR-01–08, FR-22, FR-31 (document side); first migration enables pgvector; schema for workspaces, documents, workspace_documents, chunks, topic_profiles; S1, S2, S6 (input side), S7; background ingestion with status; hybrid retrieval with RRF and reranker; retrieval debug endpoint; CPU inference benchmark script (embedding, reranker, NLI).
- **Exit criteria:** upload 3 real papers → status `ready`; retrieval returns correct chunks with page/section; cross-user and cross-workspace leakage tests pass; unrelated upload triggers warning; ingestion NFR-02 measured and recorded; CPU inference latency of the embedding, reranker, and NLI models measured on the deployed tier and recorded in `docs/PROGRESS.md`, with a note on the risk to NFR-01.

## Phase 2 — Grounded Q&A and Trust Layer (Days 3–5)

- **Scope:** FR-09–14, FR-04 first-page LLM metadata extraction, S7 LLM keyword summary, FR-25, FR-27 (harness), FR-28; A1, A2, A3; S3, S4, S5; QA graph (5.4) with Postgres checkpointer and `interrupt()`; knowledge modes (Corpus + Web path stubbed until P5); SSE streaming; LangSmith tracing; `agent_runs`; benchmark v1 (≥ 50 questions) and conditions C1–C2 runnable.
- **Exit criteria:** answers stream with validated citations; unanswerable questions abstain; approval prompt pauses and resumes correctly; baseline C1/C2 results recorded in `backend/eval/reports/`; average LLM calls per corpus-only question measured and recorded (NFR-13).

## Phase 3 — Frontend Core (Days 2–6, parallel track)

- **Scope:** landing page, auth screens, workspace list, document library with statuses and compatibility dialog, research chat with mode badge, progress events, claim status, citation chips, approval prompt, source viewer with highlight.
- **Exit criteria:** Playwright E2E test passes for upload → ask → open highlighted citation, on the deployed environment.

## Phase 4 — Research Intelligence (Days 6–7)

- **Scope:** FR-18, FR-19, FR-20, FR-21 (corpus), FR-26, FR-32; A4 with comparison, synthesis, contradiction, and gap schemas; contradictions and research_gaps tables; evidence graph API and UI (built, then retired in D-078); saved findings; Markdown/BibTeX export.
- **Exit criteria:** comparison table for 3 papers with every cell cited or "Not reported"; at least one known contradiction pair detected on the test corpus; gap report entries all link to evidence; export files open correctly.

## Phase 5 — External Research and Discovery (Days 7–9)

- **Status:** Discover search (arXiv, OpenAlex) and open-access import were brought forward (D-077); the rest of this phase is open.
- **Scope:** FR-15, FR-16, FR-17, FR-21 (field-level), FR-31 (external side); scholarly and web search provider implementations (Section 10.1) with caching; A5; S9; Corpus + Web mode completed in the QA graph; Discover UI.
- **Exit criteria:** related-paper recommendations with explanations for the test workspace; open-access import succeeds end-to-end and passes compatibility check; non-OA paper saved as metadata only; external evidence labeled in answers; API outage test degrades gracefully.

## Phase 6 — Workspace Intelligence (Day 9)

- **Scope:** FR-23, FR-24; S8; merge UI with report and override; topic profile recomputation.
- **Exit criteria:** merging two related workspaces produces a combined workspace with duplicates removed; merging unrelated workspaces shows a mismatch warning; source workspaces unchanged.

## Phase 7 — Deep Agent and MCP (Days 9–10)

- **Scope:** FR-29, FR-30; A6 built with deepagents using existing services and agents as tools; review generation UI with streamed progress; `api_tokens` table and endpoints (hashed tokens); `mcp_server/` with FastMCP and API-token auth.
- **Exit criteria:** a literature review of the test workspace is generated with all claims verified and cited; MCP tools work from Claude Desktop (or another MCP client) against the deployed backend.

## UI Redesign — stepwise, alongside Phases 4–7 (D-088, replaces the D-075 polish pass)

- **Scope:** restyle all screens to the direction in `docs/DESIGN.md`, in the order of its §13 (foundation and app shell first), one PR per step; DESIGN.md §0 updated to match what shipped. No new features, API or schema changes; screens added in later phases are built to the target design.
- **Exit criteria:** the `docs/DESIGN.md` §12 checks pass on every screen; the Phase 3 Playwright E2E test still passes.

## Phase 8 — Evaluation, Hardening, Delivery (Days 10–12)

- **Scope:** full benchmark (Section 17.4), conditions C1–C5 and ablations, verifier agreement study, adversarial and security tests, performance measurements against NFRs, final deployment, README (architecture diagram, results table, demo GIF, setup guide), project report and presentation.
- **Exit criteria:** all acceptance criteria (Section 24) verified and documented; results table generated from `backend/eval/reports/`.

## 22.1 Schedule Protection Rule

If the schedule slips, remaining work is reduced in this order, without removing a feature entirely: (1) merge UI polish, (2) knowledge graph interactivity, (3) field-level gap analysis depth, (4) number of discovery sources, (5) literature review length. Phase 2 and Phase 8 scope shall not be reduced.

# 23. Risks and Mitigation

| Risk | Impact | Mitigation |
|---|---|---|
| Schedule pressure (12 days, full scope) | Incomplete or unstable features | Dependency-ordered phases, parallel tracks, phase gates, schedule protection rule (22.1). |
| AI-generated code drift | Inconsistent architecture, hidden bugs | CLAUDE.md rules, one phase at a time, tests per phase, decision log, human review. |
| Poor PDF extraction | Missing sections/tables | Section-aware parser, open-access test corpus checked early, Docling fallback provider. |
| Weak retrieval | Relevant evidence missed | Hybrid search + reranking, Recall@K measured in Phase 2. |
| Verifier errors | Unsupported claims marked supported | Conservative thresholds, LLM judge for borderline cases, human-labeled agreement study. |
| False contradictions | Condition differences shown as conflicts | Context check, "potential" labeling, both passages shown. |
| Free-tier limits and cold starts | Slow or failed demo | Wake-up procedure before demos, caching, recorded demo video as backup. |
| External API rate limits | Discovery failures | Caching, retries, multiple providers, graceful degradation. |
| Workspace contamination | Wrong-topic answers | SQL-level isolation, compatibility checks, leakage tests. |
| Prompt injection via documents | Manipulated outputs | Untrusted-content handling (Section 18), adversarial tests. |
| LLM cost/latency | Slow answers | Small models for A1, local NLI/reranker, call budget (NFR-13). |
| CPU-only torch from the PyTorch CPU index (accepted) | Index outage or wheel mismatch breaks installs | Locked versions in `uv.lock`; CPU wheels keep the image small. |
| Background ingestion lost on restart (accepted) | Documents stuck in progress | Startup sweep marks stale in-progress documents `failed`; the user re-uploads. |

# 24. Acceptance Criteria

Functional:

1. A user can sign up, create isolated workspaces, and upload papers that reach `ready` status.
2. Answers in Corpus Only mode contain only claims supported by workspace evidence, or an explicit abstention.
3. Every factual claim in an answer has a citation that opens the highlighted source passage.
4. The system requests approval before external search or general-knowledge use, and labels such content.
5. Unrelated uploads trigger a compatibility warning; merges show a compatibility report.
6. Comparison, synthesis, contradiction, and corpus-gap outputs are produced with evidence links.
7. Related and similar papers are recommended with explanations; open-access papers can be imported.
8. A literature review can be generated in deep-agent mode with verified citations.
9. MCP tools work from an external MCP client.
10. Saved findings can be exported as Markdown and BibTeX.
11. Cross-user and cross-workspace leakage tests pass.

Quantitative (provisional targets, to be confirmed after the Phase 2 baseline and reported honestly whether met or not):

| Metric | Target |
|---|---|
| Unsupported claim rate (C5 vs C2) | C5 lower than C2 |
| Abstention accuracy on unanswerable questions (C5) | ≥ 0.80 |
| False abstention rate on answerable questions (C5) | ≤ 0.15 |
| Citation correctness (C5) | ≥ 0.85 |
| Citation completeness (C5) | ≥ 0.90 |
| Verifier agreement with human labels | ≥ 0.80 accuracy |
| Latency (NFR-01) | median ≤ 25 s |

# 25. Future Scope

- OCR for scanned papers; figure and table image understanding.
- Domain-specific embedding and reranker fine-tuning.
- Collaborative shared workspaces.
- Reference manager integrations (Zotero, Mendeley).
- Scheduled literature monitoring with alerts for new papers.
- Local/private deployment with self-hosted LLMs.
- Citation-aware manuscript drafting.

# 26. Glossary

| Term | Meaning |
|---|---|
| LLM | Large Language Model. |
| RAG | Retrieval-Augmented Generation. |
| Agentic AI | AI workflows in which components reason, use tools, and make controlled decisions. |
| Vector database | Store/index optimized for embedding similarity search (here: pgvector). |
| Embedding | Numerical representation used to measure semantic similarity. |
| Hybrid retrieval | Combination of semantic (vector) and lexical (keyword) retrieval. |
| RRF | Reciprocal Rank Fusion, a method to merge ranked lists. |
| Reranking | Second-stage relevance scoring of retrieved candidates. |
| NLI | Natural Language Inference: classifying whether a premise entails, contradicts, or is neutral to a hypothesis. |
| Guardrail | Control that constrains system behavior or validates inputs/outputs. |
| HITL | Human-in-the-loop approval step. |
| MCP | Model Context Protocol, an open standard for exposing tools and data to AI applications. |
| Deep agent | An agent with explicit planning, subagents, and working memory for long multi-step tasks. |
| Abstention | Declining to answer and stating that evidence is insufficient. |
| Semantic Research Knowledge Graph | A per-workspace graph of research entities (concepts, methods, datasets, metrics, tasks, tools, findings) and the relationships its papers state, each linked to supporting passages (Section 9.1). |
| Research gap | Potentially underexplored area identified from available literature. |

# Appendix A — Representative End-to-End Scenario

A user creates a workspace named "Tissue Engineering" and uploads 15 open-access papers. Each is parsed into section-aware chunks, enriched with DOI metadata, embedded, and indexed; the workspace topic profile is created.

The user asks: *"What are the main limitations of hydrogel scaffolds reported in these papers?"* The Query Analyzer classifies it as an aggregation question. Retrieval gathers limitation passages across papers; the Synthesis Agent drafts an answer citing chunks; the Verification Agent checks each claim, removes one unsupported generalization, and the Citation Service validates the remaining citations. The answer streams with page-level citations that open the highlighted passages.

The user asks: *"What are the latest advances published in 2026?"* The Sufficiency Gate finds no evidence in the corpus. The Approval Gate explains this and offers options. The user approves external research; the Discovery Agent queries OpenAlex and Europe PMC, and the answer labels those claims as external. Two open-access papers are imported after passing the compatibility check.

The user uploads a stock-market prediction paper. The compatibility check flags a strong mismatch; the user cancels.

Finally, the user runs literature-review mode. The deep agent plans sections (materials, fabrication, cell sources, limitations), delegates each to a subagent, and returns a verified, cited review, which the user saves and exports with a BibTeX file.

# Appendix B — Design Principles

1. Evidence before confidence.
2. Explicit knowledge boundaries.
3. Abstention is preferable to unsupported certainty.
4. External knowledge requires explicit authorization.
5. Use an LLM only where reasoning is needed; everything else is deterministic.
6. Users retain final control over boundary-crossing and workspace decisions.
7. Research findings remain traceable to evidence.
8. Measure the system rather than relying on demonstrations alone.
9. Build in dependency order; each phase ships working, tested software.
10. Use AI coding agents to accelerate implementation without surrendering architectural ownership.
