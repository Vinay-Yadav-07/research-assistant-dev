# Knowledge Graph Architecture Audit

**Feature:** Semantic Research Knowledge Graph (planned, D-078)
**Date:** 2026-10-18 · **Scope:** read-only audit of the repository at `ccf900b` (Discover merged into `dev` via PR #68)
**Status:** proposal only. Nothing described as *proposed* exists in the code yet.

> **Approved with changes on 2026-10-18 (D-081).** The specification is now SRS §9.1, which wins wherever this report differs. Main differences:
>
> - **Vocabulary:** entity types are concept, method, dataset, metric, task, tool, finding (`material` folds into `tool`). Relationships are uses, evaluated_on, measured_by, addresses, compared_with, reports. There is no `related_to`, and `improves_on` is deferred.
> - **Validation:** a relationship needs a verbatim quote naming both entities, must be stated about the paper's own work without hedging, and needs local NLI entailment. Name presence alone (§14 rule 2 here) is not enough.
> - **Checkpoints:** the checkpoint unit is one paper. A paper interrupted midway is read again, and the UI says so.
> - **Heartbeat:** written every minute while a job runs, including while it waits for rate limits.
> - **Model choice:** the graph model is chosen by a structured-output test against the SRS §9.1 criteria.

Throughout this report:

- **Existing** means it is in the code today, with a file path and symbol.
- **Proposed** means it is a design suggestion that needs approval before anything is built.

File paths are relative to the repository root.

---

## 1. Executive Summary

The repository is a good base for a per-workspace knowledge graph:

- **Evidence:** chunks already carry page and section provenance.
- **Structured output:** every LLM call goes through one structured-output interface.
- **Isolation:** workspace isolation is enforced in SQL.
- **Citations:** a citation pipeline already turns cited labels into page-accurate quotes, and the frontend already has a PDF source viewer that highlights them.
- **Graph library:** React Flow (`@xyflow/react` 12.12.0) is installed but not used anywhere.

Four parts need new work, and the main risks sit in them:

1. **Durable jobs.** There is no job table. Background work (ingestion, QA runs) runs as in-process asyncio tasks. A restart sweep fails the interrupted work; it never resumes it.
2. **LLM quota isolation.** Each rate limiter is in memory and is shared by everything that calls the same `(provider, model)` pair. Its daily counter resets on restart. A caller waiting for capacity holds the limiter's lock, so a long graph job on the strong model would delay interactive chat and use up its 500-request daily quota.
3. **Cost.** A typical paper has 37–85 chunks (measured in PROGRESS.md). One call per chunk would use the whole daily strong-tier quota on about 10 papers. Extraction has to be batched, limited to selected sections, budgeted, and run on a separate model or key.
4. **Shared documents.** A document can be linked to several of a user's workspaces. Unlinking it deletes nothing while another workspace still uses it, so graph evidence has to be checked against the current workspace links, not only against deletes.

**Recommended shape (proposed):**

- **A new service, "S10 Knowledge Graph Service".** It makes bounded, batched extraction calls per document. It is a service, not a new agent (needs approval).
- **Caching:** extraction results are stored per document and reused across the user's workspaces.
- **Atomic graph build:** the workspace graph is rebuilt in one database transaction with no LLM calls, so a failed update leaves the previous graph in place.
- **Job table:** a new `kg_jobs` table, with a partial unique index that allows one active job per workspace.
- **Separate graph LLM tier:** its own model, an optional separate API key, its own rate limits, and a per-job call budget.

This is achievable for a final-year project if version 1 stays small: a fixed set of entity and relation types, deterministic normalization, no automatic resume, and no new infrastructure.

---

## 2. Current Backend Architecture (existing)

| Concern | Implementation |
|---|---|
| App factory and lifespan | `backend/app/main.py`: `create_app()` builds providers, the DB engine and sessionmaker, `IngestionService` (`build_ingestion`), `TopicSummaryService` (`build_topic_summaries`), and `QARunner` (`build_qa_runner`). It runs startup sweeps (`fail_stale`) and keeps periodic sweep tasks in `background`. |
| Dependency injection | `backend/app/api/deps.py`: request-scoped services are built on one `AsyncSession` per request (`get_session`). App-wide singletons come from `app.state` (`get_ingestion_service`, `get_qa_runner`, `get_providers`). |
| Layering | Routers (`backend/app/api/routes/*.py`) call agents and services. Services depend on Protocol stores (for example `DocumentStore` in `services/documents.py`) that repositories implement. Agents never touch repositories. |
| Auth | `backend/app/core/auth.py` `JWTVerifier`, `deps.get_current_user`. The app refuses to start in prod without `SUPABASE_URL` (`Settings._prod_requires_auth`). |
| Errors | `backend/app/core/errors.py`: domain errors (`NotFoundError`, `ConflictError`, `LLMQuotaExceededError`, ...) mapped to HTTP in `backend/app/api/errors.py`. |
| Config | `backend/app/core/config.py` `Settings`: every model ID, threshold, top-k and quota is a setting. |
| Process model | `backend/Dockerfile` `CMD`: one `uvicorn` process with no `--workers`, on port 7860. All in-process state (limiters, task sets, locks) therefore exists exactly once in production. |

**Implication for the graph:** a graph job runner fits the pattern of `IngestionService` and `QARunner`. That means an app-wide object built in `lifespan`, holding its own task set, and opening a fresh session per unit of work.

---

## 3. Current Document Ingestion and Lifecycle (existing)

**Pipeline:** `backend/app/services/ingestion.py` `IngestionService`.

- **Status flow:** `uploaded → parsing → embedding → ready`, or `failed`. Each status change is committed on its own (`_set_status`), so the frontend can poll it.
- **Atomic finish:** chunks, metadata and `ready` are written in one transaction by `DocumentRepository.complete` (`backend/app/repositories/documents.py`). A ready document therefore always has all its chunks.
- **Concurrency:** `asyncio.Semaphore(options.concurrency)`, with `INGESTION_CONCURRENCY` defaulting to 1. Queued documents wait in status `uploaded`.
- **Delete during ingestion:** `_Deleted` is raised when the row disappears. The final write takes a row lock (`store.lock`) first.

**Identity and immutability:**

- `Document` (`backend/app/models/document.py`) is owned by one user and is unique on `(user_id, content_hash)`. A *changed* paper is therefore always a *new* document; content is never updated in place.
- `DocumentRepository.complete` deletes and re-inserts chunks, but only runs while a document is being ingested. A failed document re-uploaded via `restart` had no chunks. For a ready document, chunk IDs are stable for its whole life.
- **Risk:** future FR-07 re-embedding would also recreate chunks. Graph evidence should therefore reference `chunk_id` with `ON DELETE CASCADE` and treat a missing chunk as lost evidence.

**Workspace links (many-to-many):**

- `WorkspaceDocument` (`backend/app/models/workspace.py`) links documents to workspaces.
- `DocumentService.remove` → `DocumentRepository.unlink` deletes the link. It deletes the document, and its chunks by cascade, **only if no other workspace links it**.
- `WorkspaceRepository.delete` (`backend/app/repositories/workspaces.py`) deletes the workspace plus every document no other workspace uses.
- **Consequence:** removing a paper from workspace A may leave its chunks alive for workspace B. Graph reads must therefore filter evidence by *current* links (§12). A chunk foreign key alone is not enough.

**Chunks:**

- `Chunk` (`backend/app/models/chunk.py`): `document_id`, `chunk_index`, `page_start`, `page_end`, `section`, `text`, `token_count`, `embedding vector(384)`, and the generated `tsv`.
- The section label can be wrong. PROGRESS.md records a body-text chunk labelled "References", and ingestion never drops reference-list chunks.

**Change hooks:**

- After a document becomes ready, is linked, or is removed, `TopicSummaryService.refresh` is scheduled. See `deps.get_document_service` → `schedule_summary`, `IngestionService._refresh_summaries`, and `DocumentService.link` / `remove`.
- These are the natural points to mark a graph as stale. That is *proposed*; a read-time fingerprint (§12) avoids needing hooks at all.

---

## 4. Current LLM Architecture and Quota Management (existing)

**Interface:**

- `backend/app/providers/llm.py` defines `LLMProvider.generate_structured(messages, schema)` → `LLMResult[T]` (output, model, `TokenUsage`).
- `parse_structured` validates every provider's output and raises `LLMOutputError` on failure. Free text is never parsed with regexes.

**Hosted models:**

- `backend/app/providers/live/llm.py` `LangChainLLM`: Groq and Gemini via LangChain, with `with_structured_output(..., method="json_schema", include_raw=True)`.
- `_call` estimates tokens (characters ÷ 4 plus expected output), calls `limiter.acquire`, retries retryable errors (`is_retryable`) with exponential backoff up to `LLM_MAX_RETRIES=2`, and fails at once on daily-quota 429s (`is_daily_quota` → `LLMQuotaExceededError`).
- It then settles the reservation with the real token count and records usage.

**Tiers:**

- `backend/app/providers/factory.py` `build_providers` creates `llm_fast` and `llm_strong`.
- `build_llm` shares one `RateLimiter` per `(provider, model)` key. The first tier built sets the limits (`_limiter`).
- `backend/app/providers/live/llm_factory.py` `build_hosted_llm` picks the key **per provider** (`settings.groq_api_key` or `settings.gemini_api_key`). There is no per-tier key.

**Rate limiter:** `backend/app/providers/rate_limit.py` `RateLimiter`.

- A sliding one-minute window over requests and tokens, plus a rolling 24-hour request cap.
- **Scope:** per process, per limiter instance. A limiter is shared by the tiers on the same `(provider, model)`. It is *not* per account and *not* per API key across models.
- **Restart:** the daily counter lives in memory, so a restart resets it. The provider's own 429 is the backstop.
- **Token-per-day caps** (Groq's free tier has one) are not modelled. PROGRESS.md records the Ragas judge hitting it.
- **Head-of-line blocking:** `acquire` holds `self._lock` while sleeping for capacity. Every other caller of the same limiter waits behind the sleeping one, in arrival order. A graph job sharing a limiter with chat would delay chat answers.

**Configured limits** (`Settings`, defaults copied from the free tiers on 2026-10-04):

| Tier | Model | Limits |
|---|---|---|
| Fast | Groq `openai/gpt-oss-20b` | 30 RPM, **8 000 TPM**, 1 000 RPD |
| Strong | Gemini `gemini-3.5-flash-lite` | 15 RPM, 250 000 TPM, **500 RPD** |

PROGRESS.md also lists Gemma 4 26B/31B on the same AI Studio account at 30 RPM, 16K TPM and 14.4K RPD. Provider quotas apply per model, so a different model on the same key has its own bucket.

**Usage accounting:**

- `backend/app/providers/usage.py` `track_usage()` is a contextvar scope. Every completed call is recorded into all active scopes, including tasks started inside the scope.
- `QARunner._execute` uses it to fill `agent_runs.llm_calls` and `tokens`.

**Precedent for a separate model:** `backend/eval/judge.py` `build_judge` builds the eval judge with its own `RateLimiter` from `EVAL_JUDGE_*` settings. It refuses the strong tier's model.

**Who uses which tier today:**

- **Fast:** A1 `QueryAnalyzer`, first-page metadata (`FirstPageExtractor` in `services/document_metadata.py`). Ingestion needs it.
- **Strong:** S3 `SufficiencyGate`, A2 `SynthesisAgent`, A3 `VerificationAgent` judge, S7 `TopicSummaryService`, A4 `LiteratureAnalysisAgent`.

A chat answer uses several strong calls: up to the gate, synthesis, the judge, and up to 2 revisions.

---

## 5. Current Background Jobs and Restart Recovery (existing)

| Mechanism | Where | Durable? | Restart behaviour |
|---|---|---|---|
| Ingestion | `IngestionService.run`, scheduled with FastAPI `BackgroundTasks` in `deps.get_document_service` | Status in `documents.status`; work is in memory | `fail_stale()` at startup and every `INGESTION_SWEEP_INTERVAL_MINUTES` marks in-progress documents with `updated_at` older than 15 min as `failed` (not resumed), excluding `_active` ids |
| QA runs | `QARunner._launch` → `asyncio.create_task`, kept in `_tasks` | `agent_runs` row + LangGraph Postgres checkpoints | `fail_stale` → `ConversationRepository.fail_stale_runs` fails `running` runs whose **`created_at`** is older than 15 min, for **every workflow**. Paused (`interrupted`) runs survive. |
| Topic summary | `TopicSummaryService.refresh` via `BackgroundTasks` | No job record | Lost on restart; a per-workspace `asyncio.Lock` (`weakref.WeakValueDictionary`) serializes refreshes in one process only |

**Findings relevant to the graph:**

1. **No queue or job table.** No retries across restarts and no idempotency keys. The "durable" part is always a status column plus a sweep that *fails* work.
2. **Don't store graph jobs in `agent_runs` as-is.** `fail_stale_runs` does not filter by `workflow` and measures age from `created_at`, not from a heartbeat. A graph job running longer than 15 minutes would be marked failed by the QA sweep while still working. `RUN_STATUSES` also has no `queued` state.
3. **Restarts happen.** The Hugging Face Space restarts on redeploy and on setting changes. It sleeps after 48 h without traffic (`docs/SETUP.md`, "Known free-tier behaviour"). `QARunner.aclose` cancels running tasks on shutdown. A graph job can be interrupted at any point and must be resumable by design.
4. **In-process locks only.** Duplicate-prevention locks like `TopicSummaryService._locks` work only because there is one process. A database constraint is the safe guard.

---

## 6. Existing Database Models and Reusable Evidence Structures (existing)

**Migrations** (`backend/alembic/versions/`): `0001` baseline to `0007` research tables. The next one would be `0008`.

- Every migration enables RLS explicitly (for example `20261009_0007_research_tables.py`: `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`).
- `0002` revokes client-role (`anon` / `authenticated`) privileges by default.
- The backend connects as the table owner, and repositories filter by `user_id` (SRS §14.1). Ownership is enforced in repository SQL, as in `ChunkRepository._in_workspace` and `DocumentRepository.is_linked`.

**Evidence-shaped structures** that already exist:

| Model | File | Shape | Relevance |
|---|---|---|---|
| `Chunk` | `models/chunk.py` | text + pages + section + embedding | The evidence unit for graph nodes and edges |
| `Claim` / `Evidence` / `Citation` | `models/conversation.py` | claim → evidence (`chunk_id`, `SET NULL`) and citation snapshot (title, pages, section, quote; `document_id`/`chunk_id` `SET NULL`) | Pattern for "live link + snapshot" |
| `Contradiction` | `models/research.py` | `claim_a`, `claim_b`, `evidence_refs` JSONB snapshots, `label` (`potential_contradiction` / `context_dependent`) | Can feed graph edges later; already separates contradictions from context-dependent differences |
| `ResearchGap` | `models/research.py` | description + `evidence_refs` | Possible later overlay |
| `AgentRun` | `models/agent_run.py` | workflow run with `llm_calls`, `tokens`, `status`, `error` | Cost-record pattern; not safe as the graph job table (§5) |
| `TopicProfile` | `models/topic_profile.py` | per-workspace centroid, keywords, summary | Possible extraction context ("what this workspace is about") |

There are **no** entity, concept, method, dataset or metric models anywhere. The retired evidence graph (commit `2457b37`, D-078) only re-drew documents, chunks, claims, contradictions and gaps. It had no extraction.

---

## 7. Current Frontend Architecture and Graph Integration Point (existing)

**Stack** (`frontend/package.json`): Next.js 16.3.8 (App Router), React 19.2.8, TanStack Query 5, `openapi-fetch` with types generated by `npm run gen:api`, Tailwind 4, `motion`, `react-pdf`.

**React Flow:**

- `@xyflow/react` **12.12.0 is installed**. Its peer dependencies allow React ≥ 17, so it works with React 19.
- `grep` finds no import of it in `frontend/src`. It was kept for this feature (D-078).
- The retired screen is recoverable from git (`git show 2457b37^:frontend/src/components/graph/evidence-graph.tsx` and `.../layout.ts`). It used a dependency-free column layout. No layout library (dagre, elk, d3-force) is installed.

**Routes** (`frontend/src/app/(app)/`):

- `workspaces/page.tsx` (list)
- `workspaces/[id]/page.tsx` (library: `DocumentLibrary`)
- `workspaces/[id]/chat/...`, `workspaces/[id]/analysis/page.tsx` (`Analysis`), `workspaces/[id]/findings/page.tsx`
- `discover/page.tsx`

The `workspaces/[id]/graph` route was used by the retired screen and is free.

**Workspace navigation:**

- There is no shared workspace tab bar.
- The library header in `frontend/src/components/workspaces/document-library.tsx` (around lines 85–124) holds the link buttons: "Find papers", "Saved findings", "Analysis", "Ask your papers".
- `frontend/src/components/app-nav.tsx` holds only Workspaces and Discover.

**Reusable UI patterns:**

| Pattern | Where |
|---|---|
| Status polling with `refetchInterval` while work is in progress | `useDocuments` in `document-library.tsx`, `chat.tsx` |
| PDF side panel with quote highlight | `frontend/src/components/chat/source-viewer.tsx` (`SourceViewer`) |
| Hook wrapping it | `useSourceViewer(documents)` in `frontend/src/components/analysis/results.tsx` |
| Adapter from a citation draft to the viewer's `CitationRead` shape | `asCitation` in `frontend/src/components/analysis/citations.ts` |

**Layout constraint:** `frontend/src/app/(app)/layout.tsx` wraps every page in `max-w-4xl`. A graph canvas needs a wider page, which means a small layout change or a route-level override. `docs/DESIGN.md` requires layouts to work from 375 px and touch targets of at least 40 px.

---

## 8. Reusable Components (with exact file paths)

| # | Component | File / symbol | How it works | Verdict |
|---|---|---|---|---|
| 1 | Chunks with provenance | `backend/app/models/chunk.py` `Chunk` | ~400-token, section-aware chunks with page range, section and text | **Directly reusable** as the evidence unit |
| 2 | Workspace-scoped chunk loading | `backend/app/repositories/chunks.py` `_in_workspace`, `ChunkRepository.load` | Joins `workspace_documents` + `workspaces` + `documents`, filters `user_id` and `status='ready'` | **Directly reusable** for reading a workspace's chunks. Needs one new method to list all chunks of a document in order (today's methods search or load by id) |
| 3 | Structured LLM output | `backend/app/providers/llm.py` `LLMProvider`, `parse_structured` | Pydantic schema in, validated model out, `LLMOutputError` otherwise | **Directly reusable** |
| 4 | Hosted model, retries, quota errors | `backend/app/providers/live/llm.py` `LangChainLLM` | Per-call limiter, retry and backoff, daily-quota detection | **Directly reusable** for a graph tier |
| 5 | Building a model from settings | `backend/app/providers/live/llm_factory.py` `build_hosted_llm`; `factory.build_llm` | Key per provider; tiers share limiters by `(provider, model)` | **Reusable with modifications**: accept an optional key override and a `"graph"` tier |
| 6 | Rate limiter | `backend/app/providers/rate_limit.py` `RateLimiter` | In-memory RPM, TPM and RPD | **Reusable with modifications**: own instance for the graph tier; no persistent daily count |
| 7 | Usage accounting | `backend/app/providers/usage.py` `track_usage`, `RunUsage` | Contextvar scopes count calls and tokens | **Directly reusable** for job cost fields |
| 8 | Evidence labels and citation snapshots | `backend/app/services/citations.py` `EvidenceSet`, `CitationService.citations_for`, `quote` | LLM cites `E1`, `E2`, ...; labels outside the set are rejected; the quote is a verbatim sentence of the chunk | **Directly reusable**: same anti-fabrication rule for graph evidence |
| 9 | Untrusted text handling | `backend/app/services/guardrails.py` `data_block`, `clean_untrusted_text`, `clean_metadata_text` | Delimits document text as data and cleans stored LLM text | **Directly reusable** |
| 10 | Versioned prompts | `backend/app/prompts/__init__.py` `load_prompt`; `app/prompts/services/*.v1.md` | `<kind>/<name>.<version>.md` | **Directly reusable** (new `kg_extraction.v1.md`) |
| 11 | Multi-paper extraction pattern | `backend/app/agents/literature_analysis.py` `_findings`, `_claim`, `_passages` | Per-paper evidence, cited findings kept only if they cite their own paper | **Reusable as a pattern**; the graph needs whole-document coverage, not per-topic retrieval |
| 12 | Contradiction records | `backend/app/models/research.py` `Contradiction`; `repositories/research.py` `list_contradictions` | Stored per workspace with evidence snapshots | **Reusable later** as an optional edge overlay; not needed for v1 |
| 13 | Background runner pattern | `backend/app/services/ingestion.py` (`_slots`, `_active`, `fail_stale`, `sweep_periodically`); `backend/app/graphs/qa_runner.py` (`_tasks`, `aclose`, `_fail`) | App-wide runner, fresh session per step, startup and periodic sweep | **Reusable with modifications**: needs a job table, heartbeat-based staleness, and resumable per-document steps |
| 14 | Row locks against concurrent removal | `DocumentRepository.lock`, `unlink` (`with_for_update`) | Serializes ingest, link and remove | **Directly reusable** when committing a document's extraction |
| 15 | Ownership → 404 | `DocumentService._require_workspace`, D-047 | Missing and non-owned both raise `NotFoundError` | **Directly reusable** |
| 16 | Local embedder | `providers/local/embedding.py` via `Providers.embedder` | bge-small, 384 dimensions, shared `LocalInference` semaphore (concurrency 1) | **Reusable with care** for name similarity; it competes with chat retrieval for the same CPU slot |
| 17 | NLI model | `providers/local/nli.py` via `Providers.nli` | Local cross-encoder | **Optional**: a free, local check of a relation statement against its passage |
| 18 | Frontend data, polling, source viewer | `document-library.tsx` `useDocuments`; `results.tsx` `useSourceViewer`; `citations.ts` `asCitation`; `chat/source-viewer.tsx` | Typed client, polling, PDF highlight panel | **Directly reusable** |
| 19 | React Flow | `@xyflow/react` 12.12.0 | Installed, unused | **Directly reusable** |
| 20 | Graph job table, extraction tables, graph tables, entity normalization, graph API, graph UI | — | — | **New implementation required** |

---

## 9. Proposed Knowledge Graph Architecture (proposed)

```
User clicks "Generate"  ──► POST /workspaces/{id}/knowledge-graph/jobs
                              │  (insert kg_jobs row; one active job per workspace, enforced by a DB index)
                              ▼
                     KnowledgeGraphRunner (app-wide, in-process, global concurrency 1)
                              │
          ┌───────────────────┴────────────────────────────────────┐
          │ Phase A: EXTRACT (LLM, resumable, per document)         │
          │  for each ready document linked to the workspace       │
          │  without a current extraction (document_id, version):  │
          │    select chunks (skip references, tiny chunks)        │
          │    batch N chunks → graph-tier LLM → KGExtraction      │
          │    keep only mentions/relations whose cited labels     │
          │    are in the batch and whose text appears in the chunk│
          │    commit the extraction for this document (one tx)    │
          │    update job progress + heartbeat                     │
          └───────────────────┬────────────────────────────────────┘
                              ▼
          ┌────────────────────────────────────────────────────────┐
          │ Phase B: BUILD (no LLM, one transaction)                │
          │  read the extractions of currently linked documents     │
          │  normalize/merge entity mentions → nodes                │
          │  aggregate relation mentions → edges with evidence      │
          │  replace the workspace's nodes/edges; record a          │
          │  fingerprint of the source documents; commit            │
          └────────────────────────────────────────────────────────┘
```

**Key properties:**

- **Only Phase A spends LLM quota.** Its output is stored per document, so it survives restarts and is reused by later updates. It is also reused by other workspaces of the same user that link the same document.
- **Phase B is deterministic and atomic.** If it fails, the transaction rolls back and the previous graph stays as it was.
- **Layering:**
  - `api/routes/knowledge_graph.py` → `services/knowledge_graph.py` (S10, bounded LLM calls, Pydantic schemas next to it) → `repositories/knowledge_graph.py`.
  - The runner lives in `services/`, like `IngestionService`.
  - No LangGraph graph is needed: the workflow is a fixed loop with no agentic branching. `graphs/` is reserved for agentic workflows.
- **Classification (needs approval).** It could be:
  - **(a)** a service making bounded LLM calls, like S1 metadata or S7 summary (*recommended*);
  - **(b)** a new task of A4;
  - **(c)** a new agent.

  CLAUDE.md §3 and SRS §5.2 require approval and a DECISIONS entry for (c), and an SRS update in every case.

**Entity and relation vocabulary (v1, proposed, closed set):**

- **Entity types:** `concept`, `method`, `dataset`, `metric`, `material` / `tool`, `task` / `problem`, `finding`. `finding` is a short claim text kept as a node, so results can connect to methods and metrics.
- **Relation types:**
  - `uses` (method→dataset/material/tool)
  - `evaluated_on` (method→dataset)
  - `measured_by` (finding/task→metric)
  - `improves_on` / `compared_with` (method→method)
  - `addresses` (method→task)
  - `reports` (paper-level finding→metric/value)
  - `related_to` (fallback, shown weaker)
- **No `contradicts` edge from extraction.** Contradiction needs the A4 NLI-and-context pipeline, which already distinguishes "potential contradiction" from "context-dependent" (§14).
- **Domain-general.** Types must not be biomedical-specific; test on several fields (project memory: domain-general product).

---

## 10. Recommended Database Schema (conceptual only, proposed)

Names are illustrative. Every table gets RLS enabled explicitly and is created by a new Alembic migration (`0008`) against **dev only**. Every query filters by `user_id`, and by `workspace_id` where relevant.

**`kg_jobs`**: one row per Generate or Update request.

- `id`, `user_id`, `workspace_id` (FK, cascade), `kind` (`generate` | `update`)
- `status` (`queued` | `running` | `completed` | `failed`)
- `phase` (`extracting` | `building`)
- `documents_total`, `documents_done`, `current_document_id`
- `llm_calls`, `input_tokens`, `output_tokens`, `call_budget`
- `error_code`, `error_message`
- `extractor_version` (prompt and schema version)
- `created_at`, `started_at`, `heartbeat_at`, `finished_at`
- **Partial unique index** on `(workspace_id) WHERE status IN ('queued','running')`. It guarantees one active job per workspace even under races or a second process.

**`kg_document_extractions`**: the per-document checkpoint and cache.

- `id`, `user_id`, `document_id` (FK, cascade), `extractor_version`
- `status` (`completed` | `failed`), `chunks_considered`, `llm_calls`, `tokens`, `created_at`
- Unique on `(document_id, extractor_version)`. It makes re-runs idempotent: an existing completed row is skipped.

**`kg_entity_mentions`**: what the LLM found, tied to evidence.

- `id`, `extraction_id` (cascade), `document_id`, `chunk_id` (FK `chunks`, **cascade**)
- `entity_type`, `surface_text` (cleaned), `normalized_key`, `description` (short, optional), `quote` (verbatim sentence from the chunk)

**`kg_relation_mentions`**

- `id`, `extraction_id` (cascade), `document_id`
- `chunk_id` (FK, cascade). One relation mention cites one chunk; more than one becomes several rows.
- `source_mention_id`, `target_mention_id`, `relation_type`, `statement`, `quote`

**`kg_graphs`**: the current graph per workspace (one row).

- `workspace_id` (PK, FK cascade), `user_id`, `built_by_job_id`, `built_at`
- `source_fingerprint` (hash of the sorted `document_id`s plus `extractor_version` used)
- `node_count`, `edge_count`

**`kg_nodes`**

- `id`, `workspace_id` (cascade), `user_id`, `entity_type`, `label`, `normalized_key`, `aliases text[]`
- `document_count`, `mention_count`

**`kg_edges`**

- `id`, `workspace_id` (cascade), `user_id`, `source_node_id`, `target_node_id`, `relation_type`
- `document_count`, `mention_count`

**Node and edge evidence links**

- `kg_node_mentions(node_id, mention_id)` and `kg_edge_mentions(edge_id, relation_mention_id)`.
- Evidence is never copied as free text. It always resolves to a mention, then to a chunk, then to a document and page.

**Why two layers (mentions vs. nodes and edges):**

- Mentions are per document and immutable, so they can be computed once, reused and deleted by cascade.
- Nodes and edges are per workspace and cheap to rebuild.
- Deleting a document removes its chunks, then its mentions, then the evidence links, by cascade. A rebuild then drops edges left with no support.

Optional simplification if time is short: drop `kg_nodes` and `kg_edges` and compute them in Python at read time from mentions. That works for a few hundred mentions, but it repeats normalization on every read. Persisting them is recommended.

---

## 11. Proposed API Endpoints and Job States (proposed)

All endpoints sit under `/api/v1` and require a Supabase JWT. A missing or non-owned workspace returns **404** (D-047). The OpenAPI client is regenerated with `npm run gen:api`.

| Method and path | Purpose |
|---|---|
| `POST /workspaces/{id}/knowledge-graph/jobs` | Start Generate or Update. **202** with the job. If a job is already active, **200** with that job (idempotent; the frontend can always use the returned job). **409** `no_ready_documents` if the workspace has nothing to extract. **503** if the graph tier is not configured. |
| `GET /workspaces/{id}/knowledge-graph/jobs/{job_id}` | Job progress (status, phase, `documents_done/total`, LLM calls, error). The frontend polls it every 3 s while active. |
| `GET /workspaces/{id}/knowledge-graph` | The graph state plus nodes and edges: `state` (§12), `stale`, `active_job`, `last_failed_job`, `built_at`, nodes with counts, edges with counts. Only evidence from currently linked ready documents counts. |
| `GET /workspaces/{id}/knowledge-graph/nodes/{node_id}/evidence` | Paginated live evidence: document, title, pages, section, quote, `chunk_id`. Shaped like `CitationRead` so `SourceViewer` can open it. |
| `GET /workspaces/{id}/knowledge-graph/edges/{edge_id}/evidence` | Same for an edge, plus each relation `statement`. |

**Job states:** `queued → running(extracting k/n) → running(building) → completed`, or `failed` from any state.

- **Restart:** a job interrupted by a restart is swept to `failed` with `error_code=interrupted`. Its committed per-document extractions are kept, so the next Update continues where it stopped.
- **Quota exhausted:** `failed` with `error_code=llm_quota_exhausted` and a plain message. Extractions are kept.
- **Over budget:** `failed` with `budget_exceeded`.

**Graph state shown to users** (derived, not stored):

| State | Rule |
|---|---|
| `empty` | No `kg_graphs` row and no active job |
| `queued` / `generating` | Active job and no graph yet |
| `ready` | Graph exists, fingerprint matches, no active job |
| `update_available` | Graph exists and its fingerprint differs from the current ready, linked documents |
| `updating` | Graph exists and a job is active (the old graph stays visible) |
| `failed` | Last job failed. If a graph exists, it is still shown with a banner. |

Cancel (`POST .../jobs/{id}/cancel`) is optional, after v1.

---

## 12. Incremental Generation and Refresh Strategy (proposed)

1. **Staleness without hooks.** `source_fingerprint` hashes the sorted ids of ready documents linked to the workspace when the graph was built, plus `extractor_version`. `GET /knowledge-graph` recomputes it from `workspace_documents` and compares. New papers, removed papers and a new extractor version all show as `update_available`. No change to ingestion or document services is needed.
2. **Update = extract what is missing, then rebuild.** An Update job extracts only linked ready documents without a completed `kg_document_extractions` row for the current version. A document already extracted for another workspace of the same user is reused with no LLM calls. Phase B then rebuilds the whole workspace graph, which is cheap and deterministic. That avoids fragile in-place edge edits.
3. **Removed papers.**
   - *Immediately:* the read API joins evidence → chunk → document → `workspace_documents` for this workspace, so a removed paper's evidence disappears at once, even before an Update. Edges and nodes whose live evidence count drops to 0 are hidden. Relationships still supported by other papers stay visible with smaller counts. That meets "do not destroy relationships still supported by other papers".
   - *Fully deleted documents:* chunks and mentions cascade away.
   - *Next Update:* the rebuild prunes empty nodes and edges for good.
4. **Changed papers.** Because of `(user_id, content_hash)` uniqueness, a revised PDF is a new document. The old one is removed (point 3) and the new one extracted (point 2).
5. **Failure preserves the last graph.** Phase A never touches `kg_nodes`, `kg_edges` or `kg_graphs`. Phase B is a single transaction (delete the workspace's nodes and edges, insert new ones, upsert `kg_graphs`), the same approach as `ResearchRepository.replace_contradictions`.
6. **Idempotency and retries.**
   - Per-call retries are already in `LangChainLLM._call`.
   - A batch whose output fails validation (`LLMOutputError`) is retried once, then skipped and counted. A document with too many skipped batches fails its extraction without failing the whole job.
   - Re-running a job never duplicates mentions: the per-document unique key and a "commit all of a document's mentions in one transaction" rule prevent it.
7. **Consistency while files change.**
   - Before committing a document's extraction, take `DocumentRepository.lock`-style `FOR UPDATE` on the document and check it still exists and is ready. A removal in between makes the insert a no-op, and a vanished chunk fails its foreign key and the batch is dropped.
   - Phase B reads the linked-document set inside its own transaction and records exactly that set in the fingerprint. A paper added during the job therefore shows as `update_available` afterwards, never half-included.
8. **Duplicate jobs.** The partial unique index on `kg_jobs` makes the second insert fail. The service catches it and returns the active job. A global `asyncio.Semaphore(1)` in the runner keeps only one job calling the LLM at a time across workspaces, which protects quota.

---

## 13. LLM Isolation, Token Budget, and Cost Risks (proposed, with existing facts)

**Workload estimate.** These are estimates, not measured; the token counts are assumptions.

- About 45 chunks per paper (PROGRESS.md: 37–85). Excluding reference-list and very short chunks might remove about 10–20%.
- **10 papers ≈ 400–450 chunks.** At 4 chunks per call (about 1.8K passage tokens, 0.6K prompt and up to 1.5K output, so about 4K tokens per call), that is **about 100–115 calls** per full generate.

| Option | Daily cost | Throughput | Notes |
|---|---|---|---|
| Strong tier (flash-lite, 500 RPD, shared with chat) | About 22% of the daily quota per 10-paper graph | — | Two or three graphs a day would starve chat. **Not acceptable without a separate key or model.** |
| Groq `gpt-oss-20b` / `-120b` (8K TPM, 1K RPD) | — | About 2 calls/min, so about 1 h per 10 papers | A tokens-per-day cap already hit the eval judge |
| Gemma 4 on the same AI Studio account (30 RPM, **16K TPM, 14.4K RPD**) | Separate per-model bucket | About 4 calls/min, so about 30 min | **Unverified:** whether LangChain's `json_schema` structured output works for Gemma on the Gemini API must be checked with one integration call before choosing it |

**Isolation design (proposed):**

1. **A third tier, "graph".**
   - Settings: `LLM_GRAPH_PROVIDER` (default `fake`), `LLM_GRAPH_MODEL`, `LLM_GRAPH_RPM/TPM/RPD`, and optional `LLM_GRAPH_API_KEY` (`SecretStr`; when empty, the provider's existing key is used).
   - Built in `providers/factory.py` with its **own** `RateLimiter`, never shared with fast or strong.
   - `build_hosted_llm` gains an optional key argument. This is a provider-layer change and touches no security boundary.
2. **Refuse risky configs.** If the graph tier uses the same `(provider, model, key)` as fast or strong, refuse to start unless `LLM_GRAPH_RPD` is set below the shared quota, as `eval/judge.py` refuses the strong model. A separate key or model gives a separate provider quota bucket, because Groq and Gemini quotas are per model per organization or project.
3. **Per-job budget.** `KG_MAX_CALLS_PER_JOB` (for example 150) and `KG_CHUNKS_PER_CALL` (for example 4). The job estimates its calls before starting, and stops with `budget_exceeded` when the cap is reached, keeping completed documents. Optionally, `KG_MAX_DOCUMENTS_PER_JOB` keeps the first version predictable.
4. **Accounting.** Wrap each job in `track_usage()` and store `llm_calls` and tokens on `kg_jobs` and per extraction. Optionally, also write an `agent_runs` row only at the end (status `completed`/`failed`, workflow `knowledge_graph`), so existing cost reporting sees it without the QA sweep touching it.
5. **Known gaps that remain:**
   - The daily counter resets on restart (`RateLimiter` is in memory).
   - Tokens-per-day caps are not modelled.
   - The provider 429 (`is_daily_quota` → `LLMQuotaExceededError`) is the real backstop, and the job must turn it into a clean `failed: llm_quota_exhausted` while keeping extractions.
   - A persistent usage ledger would fix the restart reset, but it is scope creep for v1.
6. **CPU contention.** Embedding entity names for merge candidates uses the shared `LocalInference` slot (`LOCAL_INFERENCE_CONCURRENCY=1`), which chat retrieval also needs. Keep it to one small batch per build, or use deterministic normalization only in v1.

**Normalization (proposed v1):**

- `normalized_key` = casefold, Unicode-normalize, strip punctuation and plural "s", and collapse whitespace.
- Merge mentions with the same `(entity_type, normalized_key)`. Merge an acronym and its expansion only when the LLM emitted both in the same chunk.
- No embedding or LLM merging in v1. Over-merging common short acronyms across fields (for example "PCA", "SVM", "PCL") is the main quality risk. Keeping merges conservative errs toward duplicates, which is safer than wrong links.

---

## 14. Security, Authorization, and Evidence Integrity

**Existing guarantees to preserve:**

- **SQL scoping:** every repository query filters by `user_id`, and workspace-scoped reads join `workspace_documents` + `workspaces` (`ChunkRepository._in_workspace`).
- **404 for others' data:** non-owned resources return 404 (D-047).
- **RLS:** enabled on every table, with client roles revoked (migrations `0002`, `0007`).
- **Untrusted text:** document text is wrapped with `data_block` (`services/guardrails.py`).
- **Citation integrity:** citations are only built from labels in the evidence set (`EvidenceSet.check`).

**Proposed rules for the graph:**

1. **Isolation in SQL.** Every graph query takes `user_id` and `workspace_id` as required arguments and joins through `workspace_documents`. Node and edge evidence endpoints check that the node or edge belongs to the workspace *and* that each evidence chunk is in a ready document linked to it. Add cross-user and cross-workspace tests, as `test_retrieval_db.py` does.
2. **No fabricated evidence.**
   - The LLM cites batch labels (`E1`..`E4`). Labels outside the batch are dropped (`EvidenceSet` pattern).
   - An entity mention is kept only if its `surface_text` occurs in the cited chunk's text (case- and whitespace-insensitive).
   - A relation is kept only if both endpoints' mentions are kept and occur in the cited chunk.
   - Quotes are verbatim sentences from the chunk, chosen deterministically by `CitationService.quote`, never generated text.
3. **No overclaiming.** `related_to` and other relations are shown as "mentioned together in a passage", not as proven facts. There are no extraction-generated `contradicts` edges. If contradictions are added later, they come only from A4's stored `Contradiction` records with both labels, keeping "context-dependent" separate.
4. **Prompt injection.** Chunks go inside `data_block`, and the system prompt states that passage text is data. Stored labels pass through `clean_metadata_text`. React renders labels as text only (no HTML).
5. **Knowledge mode.** Extraction is corpus-only by construction: no web search and no general knowledge in labels. The prompt forbids adding entities not present in the passages, and rule 2 enforces it.
6. **Secrets and data.** An optional `LLM_GRAPH_API_KEY` is a `SecretStr`, never logged (as in `build_hosted_llm`). Document text already goes to Groq and Gemini. The graph tier adds no new external service if it stays on those providers. Using any *other* provider would send user documents to a new external service, which needs approval.
7. **Lifecycle.**
   - Workspace deletion cascades through `workspace_id` foreign keys on `kg_jobs`, `kg_graphs`, `kg_nodes` and `kg_edges`.
   - Document deletion cascades through `document_id` and `chunk_id` foreign keys on extractions and mentions.
   - Graph data is never shown for documents the workspace no longer links.

---

## 15. Hugging Face Spaces Deployment Considerations

- **One process, one replica** (`backend/Dockerfile` `CMD uvicorn ...`, no workers). In-process runner state is fine, but the partial unique index is still the authoritative duplicate guard.
- **Restarts.** The Space restarts on redeploy and on any variable or secret change, and sleeps after 48 h idle (`docs/SETUP.md`). Shutdown cancels tasks (pattern: `QARunner.aclose`).
- **Startup sweep (proposed):** mark `queued`/`running` jobs whose `heartbeat_at` is older than `KG_JOB_STALE_MINUTES` (for example 10) as `failed: interrupted`, excluding jobs this process is running. The heartbeat is updated after each batch. **Do not** reuse `fail_stale_runs` (§5).
- **No automatic resume in v1.** The user clicks Update, and completed documents are skipped. Automatic resume of `queued` jobs at startup is possible later, but it can surprise users and spend quota after a redeploy.
- **Build impact.** No new backend dependencies are needed: LangChain providers, SQLAlchemy and the models are already in the image. The frontend needs none if the layout stays dependency-free. The image size is unchanged.
- **Config.** New variables (names only): `LLM_GRAPH_PROVIDER`, `LLM_GRAPH_MODEL`, `LLM_GRAPH_RPM`, `LLM_GRAPH_TPM`, `LLM_GRAPH_RPD`, optional secret `LLM_GRAPH_API_KEY`, `KG_CHUNKS_PER_CALL`, `KG_MAX_CALLS_PER_JOB`, `KG_JOB_STALE_MINUTES`.
  - Update `backend/.env.example` and `docs/SETUP.md`.
  - The Dockerfile sets `LLM_FAST_PROVIDER` and `LLM_STRONG_PROVIDER`. It would need `LLM_GRAPH_PROVIDER` too, or the graph stays `fake` (off) in prod, which is a safe default.
- **Database.** Migration `0008` goes to the dev project first. Prod migration only at a phase gate, with explicit approval (CLAUDE.md §8).
- **Long jobs.** A 30–60 min job keeps the Space busy but not CPU-bound: LLM calls are network waits. Chat still works while it runs, because the graph tier uses its own limiter.

---

## 16. Technical Risks and Open Questions

**Risks** (highest first):

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| 1 | Graph extraction uses up the daily quota chat needs | Chat answers fail with `llm_quota_exhausted` | Separate graph tier, model or key; own limiter; per-job budget; refuse a shared config (§13) |
| 2 | Shared limiter head-of-line blocking (`RateLimiter.acquire` sleeps while holding its lock) | Slow chat during graph jobs | Never share a limiter between graph and interactive tiers |
| 3 | Extraction quality: hallucinated or trivial entities, generic "related_to" noise | A graph that misleads or adds no value (the reason the old graph was retired) | Closed vocabulary; verbatim-presence check; minimum `document_count` filter in the UI; real-paper evaluation across several fields before release |
| 4 | Over-merging or under-merging entities across papers | False cross-paper links (integrity) or duplicates (clutter) | Conservative deterministic merge in v1; show aliases; plan a merge review later |
| 5 | Restarts mid-job | Lost progress, confusing status | Per-document commits, heartbeat sweep, Update resumes |
| 6 | QA sweep kills graph jobs if they are stored in `agent_runs` | Jobs marked failed while still running | Separate `kg_jobs` table |
| 7 | Large graphs in React Flow (hundreds of nodes) | Unreadable, slow on phones | Show the top N nodes by support (for example 150), type filters, search, an "only shared across ≥ 2 papers" toggle |
| 8 | Section labels are unreliable ("References" on body text, PROGRESS.md known issue) | Wrong chunks skipped or reference lists extracted | Skip by content heuristics too (citation-list density), not by section label alone |
| 9 | Structured-output support of the chosen graph model is unverified (Gemma) | Validation failures | One integration test on dev before choosing; fall back to another model |
| 10 | The daily counter resets on restart; tokens-per-day not modelled | Unexpected 429s | Treat a 429 as a clean, resumable failure |

**Open questions:**

1. Is S10 a service (recommended) or part of A4?
2. Which model and key for the graph tier: Gemma 4 on AI Studio, Groq `gpt-oss-120b`, or a second Gemini key?
3. Should extractions be shared across a user's workspaces (recommended: yes, it saves quota), or kept per workspace for simplicity?
4. Should v1 include `finding` nodes, or only concept, method, dataset and metric (smaller, cleaner graphs)?
5. Should A4 contradictions appear as an edge overlay in v1, or later?
6. Is a maximum-papers-per-graph cap acceptable for v1 (for example 20)?
7. Is there a time or quality target for the demo (for example "10 papers in under 40 min, at least 80% of sampled edges judged correct by a human")?

---

## 17. Suggested Implementation Phases

Sized for limited time; each phase ends with green CI and something that can be demonstrated.

| Phase | Content | Done when |
|---|---|---|
| **0. Spec and approval** | Decisions in §18. SRS §5.3/§9/§14.1/§16.1/§19 and a DECISIONS entry (D-081). Settings names. | Approved |
| **1. Schema and job runner (fake LLM)** | Migration `0008` (dev), models, repository with ownership filters, `kg_jobs` partial unique index, runner with global semaphore, heartbeat, startup and periodic sweep, `POST`/`GET` job endpoints | Unit tests: duplicate POST returns the same job, restart sweep, cross-user 404 |
| **2. Extraction (fake, then real)** | Chunk selection, batching, `kg_extraction.v1.md`, `KGExtraction` schema next to the service, label and verbatim checks, per-document commit, budget and quota failure handling, graph tier in `providers/factory.py` | Unit tests with `FakeLLM` (invalid labels dropped, absent entities dropped, quota → failed with extractions kept); one dev integration run on 2–3 real papers from different fields |
| **3. Build and read API** | Normalization, atomic rebuild, fingerprint and state, graph and evidence endpoints with live-link filtering | Tests: removed paper hides its evidence at once; an edge supported by two papers survives one removal; a failed build keeps the old graph |
| **4. Frontend** | Graph route and page, link in the library header, state machine UI, React Flow canvas, evidence panel via `SourceViewer`; `npm run gen:api` | `npm run lint && npm run build`; manual UI checklist |
| **5. Quality and quota check** | Real-paper runs across several fields; record calls, tokens and duration per paper and edge precision on a sample in PROGRESS.md | Numbers recorded honestly |

Phases 1–3 are the core; phase 4 can start against the fake backend once phase 3's API contract is fixed.

---

## 18. Final Recommendations

### UI integration (§5 of the task)

**Where it goes:**

- **New route:** `frontend/src/app/(app)/workspaces/[id]/graph/page.tsx`.
- **New component folder:** `frontend/src/components/graph/` (`knowledge-graph.tsx`, a small dependency-free `layout.ts` that can start from the retired one in `2457b37^`, and `evidence-panel.tsx`).
- **Entry point:** add a "Knowledge graph" link to the header buttons in `frontend/src/components/workspaces/document-library.tsx`, next to "Analysis". A shared workspace tab bar would be nicer but is outside scope.

**Files likely to change:** `document-library.tsx`, `frontend/src/app/(app)/layout.tsx` (allow a wide page, or add a route-level wrapper), `frontend/src/lib/api/schema.d.ts` (generated), and the new files above.

**States:**

| State | UI |
|---|---|
| Empty (no ready papers) | Explain that the graph needs ready papers; link to the library or upload |
| Empty (papers ready) | One primary "Generate knowledge graph" button, with an estimate ("about N model calls, may take ~M minutes") |
| Queued | "Waiting to start", button disabled; poll the job every 3 s (`refetchInterval` pattern) |
| Generating | Real progress from the job: "Reading paper k of n: *title*", then "Building graph". No fake percentage (as in D-080) |
| Ready | Canvas plus filters (entity type, "shared by ≥ 2 papers"), search, legend, built-at time |
| Update available | Banner "N papers added or removed since this graph was built" with an "Update graph" button; the old graph stays usable |
| Updating | Old graph shown, read-only banner with progress |
| Failed | Plain reason (interrupted, quota used up, budget reached), "Try again" (resumes); the last good graph stays visible |

**Selection and evidence:**

- Clicking a node or edge (pointer or keyboard; React Flow nodes are focusable) opens a side panel. It shows the label, type, aliases and supporting papers.
- For each supporting passage, the panel shows paper, page and quote. "Open source" opens the existing `SourceViewer` with the quote highlighted (`useSourceViewer` + an `asCitation`-style adapter).
- Edges show their relation type and the per-paper statements.
- On phones (375 px) the panel is a full-screen sheet, as `SourceViewer` already is. The canvas needs zoom controls and 40 px targets.

**React Flow:** 12.12.0 is installed and works with React 19 and Next 16. Import `@xyflow/react/dist/style.css` in a client component, as the retired screen did. v1 needs no layout library: lay out by entity type in columns or rings, ordered by connections. Consider `@dagrejs/dagre` (small) only if real graphs tangle.

### Overall recommendations

1. Build the graph as **S10, a service with bounded LLM calls** (needs approval), not a new agent or a LangGraph workflow.
2. Use a **dedicated graph LLM tier** with its own limiter, an optional own key, and a per-job budget. Never share the strong tier's limiter.
3. Keep **two layers:** immutable per-document extractions (resumable, reusable) and an atomically rebuilt per-workspace graph. That one choice gives incremental updates, failure safety, restart recovery and shared-document correctness.
4. Use a **new `kg_jobs` table** with a partial unique index and heartbeat-based sweep. Do not use `agent_runs` for live job state.
5. **Filter evidence by current workspace links at read time**, so removed papers vanish at once without destructive operations.
6. Enforce the **verbatim-presence and label rules** so that no node or edge exists without a real passage, and no `contradicts` edges come from extraction.
7. Keep v1 small: a closed vocabulary, deterministic merging, a node cap with filters, manual Generate and Update, and no automatic resume.

### Decisions that need approval

1. Classification: S10 service (recommended) vs. A4 task vs. new agent.
2. Graph LLM tier: new settings and optional new secret `LLM_GRAPH_API_KEY`; which model and provider (Gemma 4 on the existing Gemini account recommended, pending a structured-output check).
3. New tables and migration `0008` (dev first; prod only at a phase gate).
4. Entity and relation vocabulary for v1, and excluding `contradicts` edges from extraction.
5. Sharing extractions across a user's workspaces.
6. No automatic job resume after a restart in v1.
7. A wider page for the graph route (layout change), and whether a layout library may be added later.
8. The SRS and DECISIONS updates listed in phase 0.

*Confirmed scope of this audit:* no application code, migrations, dependencies, environment files or existing documents were changed; no LLM calls were made. This report is the only new file.
