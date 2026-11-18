# Decision Log

One entry per decision. Each approved change to a flexible default or deviation from the SRS is recorded here and reflected in `docs/SRS.md` in the same commit (CLAUDE.md §1a).

Format: **ID — title** · date · decision · reason.

---

## D-001 — Phase 0 is current; PROGRESS.md first
- **Date:** 2026-09-29
- **Decision:** The project is in Phase 0. Creating `docs/PROGRESS.md` is its first task.
- **Reason:** CLAUDE.md requires reading PROGRESS.md to find the current phase, but the file did not exist.

## D-002 — Git workflow follows CLAUDE.md
- **Date:** 2026-09-29
- **Decision:** Task branches `p<phase>/<task>` from `dev` → PR into `dev`; `dev` → PR into `main` at phase gates, tagged `phase-N-done`. SRS §21.3 updated to match.
- **Reason:** SRS §21.3 ("one branch per phase, merged to main") contradicted CLAUDE.md §7.

## D-003 — Humans create accounts; Claude writes setup steps
- **Date:** 2026-09-29
- **Decision:** The team creates Supabase dev/prod, Vercel, Hugging Face Spaces, and GitHub secrets. Claude Code writes step-by-step instructions in `docs/SETUP.md` during the deploy task.
- **Reason:** Account creation and secret handling cannot be done by the coding agent.

## D-004 — Real tests in Phase 0
- **Date:** 2026-09-29
- **Decision:** Phase 0 includes unit tests for `/health` and config loading.
- **Reason:** `pytest` exits with code 5 when no tests are collected, so the "`uv run pytest` passes" exit criterion needs real tests.

## D-005 — Fakes in app/providers/fakes/, selectable by config
- **Date:** 2026-09-29
- **Decision:** Fake providers live in `app/providers/fakes/` and are selected through config (e.g. `LLM_PROVIDER=fake`). Unit tests use the same fakes.
- **Reason:** Local development and CI can then run without API keys, and tests exercise the same code path as the app.

## D-006 — CI contents
- **Date:** 2026-09-29
- **Decision:** CI runs `ruff check`, `ruff format --check`, `mypy`, backend unit tests, frontend lint and build. Integration tests stay out of CI for now.
- **Reason:** The SRS only said "lint + unit tests". Integration tests need secrets.

## D-007 — gen:api and CORS in Phase 0
- **Date:** 2026-09-29
- **Decision:** `npm run gen:api` (openapi-typescript) is set up in Phase 0 and used for the frontend health call. CORS origins come from config.
- **Reason:** CLAUDE.md requires all API calls to go through the generated client; the deployed frontend needs CORS to reach the backend.

## D-008 — Provider access by layer
- **Date:** 2026-09-29
- **Decision:** Agents and services may call providers; repositories may not.
- **Reason:** The layering rule did not say where providers sit.

## D-009 — Routers may call services for plain CRUD
- **Date:** 2026-09-29
- **Decision:** Routers may call services directly for plain CRUD. Graphs are only for agentic workflows.
- **Reason:** Routing CRUD through a graph or agent would add complexity for no benefit.

## D-010 — Prompt and schema locations
- **Date:** 2026-09-29
- **Decision:** All prompts live in `app/prompts/` (subfolders `agents/` and `services/`), versioned. Output schemas live next to their owner.
- **Reason:** Services S1 and S7 make bounded LLM calls, and the old rules only covered agent prompts and schemas.

## D-011 — A6 subagents are part of A6
- **Date:** 2026-09-29
- **Decision:** A6's subagents are not new LLM agents. They may use only existing services and agents as tools.
- **Reason:** Keeps the agent count at A1–A6 and prevents A6 from bypassing layering.

## D-012 — Alembic scope and pgvector
- **Date:** 2026-09-29
- **Decision:** Alembic ignores Supabase's `auth` and `storage` schemas and the LangGraph checkpoint tables. pgvector is enabled in the first Phase 1 migration.
- **Reason:** Those objects are managed by Supabase or the checkpointer library; autogenerate would otherwise try to change them. Phase 0 has no domain tables.

## D-013 — NFR-10 embedding-dimension exception
- **Date:** 2026-09-29
- **Decision:** Providers are swappable by config only, except that changing the embedding dimension needs a migration and re-indexing.
- **Reason:** `chunks.embedding` is a fixed `vector(384)` column, which contradicted "configuration only".

## D-014 — Default mode and approval
- **Date:** 2026-09-29
- **Decision:** `default_mode` may be Corpus Only or Corpus + Web. Choosing Corpus + Web counts as approval for that conversation and is logged (`approvals.conversation_id` added; `run_id` nullable). General Knowledge always needs per-request confirmation.
- **Reason:** `default_mode` conflicted with per-request approval. This keeps General Knowledge strictly gated.

## D-015 — Archive vs delete
- **Date:** 2026-09-29
- **Decision:** `PATCH` with `archived=true` archives a workspace. `DELETE` permanently deletes it, after confirmation in the UI. FR-02 updated.
- **Reason:** FR-02 listed only archive, while the API listed DELETE.

## D-016 — Batched judge calls; LLM-call budget ≤ 10
- **Date:** 2026-09-29
- **Decision:** All borderline judge checks for a draft go to the LLM in one batched call. NFR-13 changes to an average of ≤ 10 LLM calls per corpus-only question, to be measured in Phase 2.
- **Reason:** Per-claim judge calls plus up to 2 revision loops could exceed the original budget of 8.

## D-017 — eval/ moves into backend/
- **Date:** 2026-09-29
- **Decision:** Evaluation code lives in `backend/eval/`. Ragas goes in an `eval` dependency group. Command: `uv run python -m eval.run` from `backend/`.
- **Reason:** One uv project owns all Python code and dependencies; the two documents showed different commands.

## D-018 — SRS aligned with CLAUDE.md on dependencies and process
- **Date:** 2026-09-29
- **Decision:** The SRS stack is a default. Alternatives are proposed, approved, logged here, and reflected in the SRS in the same commit (CLAUDE.md §1a).
- **Reason:** SRS §15/§21.3 treated the stack as fixed, contradicting CLAUDE.md §1a and §3.

## D-019 — api_tokens for MCP (Phase 7)
- **Date:** 2026-09-29
- **Decision:** Add an `api_tokens` table (hashed tokens, revocable) and `GET/POST /api-tokens`, `DELETE /api-tokens/{id}`, scheduled for Phase 7.
- **Reason:** The MCP server authenticates with user-generated API tokens, but the data model and API had no place for them.

## D-020 — Revision summary wording
- **Date:** 2026-09-29
- **Decision:** The v1.1 summary now says the v1.0 components were "reorganized into 6 LLM agents and 9 deterministic services".
- **Reason:** "12 components split into 6 + 9" did not add up.

## D-021 — PROGRESS.md tracks two lines
- **Date:** 2026-09-29
- **Decision:** `docs/PROGRESS.md` tracks the backend phase and the frontend track separately.
- **Reason:** Phase 3 (frontend) runs in parallel with backend phases.

## D-022 — Phase 0 split into task branches
- **Date:** 2026-09-29
- **Decision:** Phase 0 is split into task branches, each with its own plan (see `docs/PROGRESS.md`).
- **Reason:** Phase 0 touches far more than ~5 files; smaller branches keep reviews manageable.

## D-023 — Readiness endpoint
- **Date:** 2026-09-29
- **Decision:** Add `GET /health/ready`, which checks the database connection, to Phase 0. `/health` stays dependency-free.
- **Reason:** `/health` alone does not show that the deployed backend can reach Supabase.

## D-024 — CPU inference benchmark in Phase 1
- **Date:** 2026-09-29
- **Decision:** Phase 1 exit criteria include measuring embedding, reranker, and NLI latency on the deployed CPU tier.
- **Reason:** Local models on free CPU hosting may threaten NFR-01 and NFR-02; finding out in Phase 1 is cheaper than in Phase 8.

## D-025 — Async SQLAlchemy + psycopg; selector event loop on Windows
- **Date:** 2026-09-29
- **Decision:** The backend uses an async SQLAlchemy engine with psycopg 3 (`postgresql+psycopg://`). On Windows, run uvicorn with `--reload` or `--loop asyncio:SelectorEventLoop`; no platform code in the app.
- **Reason:** psycopg's async mode rejects Windows' `ProactorEventLoop`, which uvicorn uses without `--reload` (verified with uvicorn 0.54). asyncpg was rejected because the LangGraph Postgres checkpointer uses psycopg; a sync engine would only defer the problem.

## D-026 — Supabase connection string
- **Date:** 2026-09-29
- **Decision:** `DATABASE_URL` uses the Supabase session pooler (port 5432) or the direct connection, not the transaction pooler (port 6543). The engine sets `prepare_threshold=None` as a guard.
- **Reason:** Transaction pooling breaks psycopg server-side prepared statements.

## D-027 — Providers default to `fake`
- **Date:** 2026-09-29
- **Decision:** All `*_PROVIDER` settings default to `fake`, so a fresh clone runs without keys; deployments set real values. Allowed values are `Literal`s in `app/core/config.py`, which task #3 may extend.
- **Reason:** Follows D-005; tests, CI, and first-run local development need no secrets.

## D-028 — Single error envelope
- **Date:** 2026-09-29
- **Decision:** Domain errors, validation errors, HTTP errors, and unhandled errors all return `{"error": {"code", "message", "details"}}` (`app/schemas/errors.py`). Domain exceptions in `app/core/errors.py` carry no HTTP status; `app/api/errors.py` maps them. Unhandled errors return a generic 500 and are logged with their traceback.
- **Reason:** The generated frontend client gets one error type, and internal details never reach clients. Open for Phase 1: whether ownership failures should return 404 instead of 403 so resource existence isn't revealed.

## D-029 — Backend tooling in Phase 0 task #2
- **Date:** 2026-09-29
- **Decision:** Ruff (line length 100), mypy `strict` with the pydantic plugin, and pytest (`-m "not integration"` by default) are configured in `backend/pyproject.toml` now; task #6 only adds the CI workflow. The test client uses `httpx2`, because Starlette deprecated `httpx` for `TestClient`.
- **Reason:** Code is lint- and type-clean from its first commit, and `uv run pytest` runs unit tests only, as CLAUDE.md §5 says.

## D-030 — Development moves to WSL2
- **Date:** 2026-09-30
- **Decision:** Local development runs in WSL2 (Ubuntu), with the repository on the Linux filesystem (e.g. `~/projects`, not `/mnt/c`) and a virtual environment created inside WSL by `uv sync`. The Windows workaround in D-025 (`--reload` or `--loop asyncio:SelectorEventLoop`) is no longer needed and applies only to anyone still developing on native Windows. Docker and Hugging Face Spaces are unaffected.
- **Reason:** Windows Smart App Control blocked unsigned compiled modules (first SQLAlchemy's Cython extension; later phases add torch, sentence-transformers, and PyMuPDF), and psycopg's async mode rejects the Windows `ProactorEventLoop`. Neither applies on Linux, which also matches the production container.

## D-031 — Two LLM tiers with their own provider and model
- **Date:** 2026-09-30
- **Decision:** `LLM_PROVIDER` is replaced by `LLM_FAST_PROVIDER`/`LLM_FAST_MODEL` and `LLM_STRONG_PROVIDER`/`LLM_STRONG_MODEL`. An `LLMProvider` instance is bound to one model; the factory builds a "fast" and a "strong" instance, and agents receive the one they need instead of choosing model IDs. SRS §15.1 updated.
- **Reason:** SRS §15.1 uses a fast model (Groq) and a stronger model (e.g. Gemini), possibly from different vendors, which a single provider setting cannot express.

## D-032 — Scholarly search and web search are separate interfaces
- **Date:** 2026-09-30
- **Decision:** `ScholarlySearchProvider` (search, DOI lookup, related papers, open-access PDF) covers the scholarly APIs, selected by `SEARCH_PROVIDER`. `WebSearchProvider` covers Tavily, selected by the new `WEB_SEARCH_PROVIDER`. The web provider is only given to code holding a Corpus + Web approval. SRS §10.1 updated.
- **Reason:** Web results and paper records have different shapes, and a separate interface makes the approval gate structural rather than relying only on run-state checks.

## D-033 — Reranker scores in [0, 1]
- **Date:** 2026-09-30
- **Decision:** `RerankerProvider.score` returns one score per passage in [0, 1], in input order; real cross-encoders apply a sigmoid to the logit. Sorting and top-k stay in S2. SRS §8.2 updated.
- **Reason:** S3's sufficiency thresholds are easier to calibrate and survive a model change when scores have a fixed range.

## D-034 — All provider interfaces are async
- **Date:** 2026-09-30
- **Decision:** Every provider method that does I/O or inference is `async`. Local CPU models (embedding, reranker, NLI, parser) will run inference through `asyncio.to_thread` behind a small concurrency limit (Phase 1).
- **Reason:** Callers treat all providers the same way, and CPU-bound inference never blocks the event loop that serves SSE streams.

## D-035 — Providers validated at startup; model preloading controlled by PRELOAD_MODELS
- **Date:** 2026-09-30
- **Decision:** `build_providers()` runs in the app lifespan and stores the result on `app.state.providers`. An unknown or unimplemented provider fails startup with `ProviderConfigurationError`. Building a provider must stay cheap. **Phase 1 adds a `PRELOAD_MODELS` setting** (default `false` for local development, `true` in the Docker/production configuration): when true, local model weights load at startup; when false, they load on first use. SRS §15.3 updated.
- **Reason:** A misconfigured deployment should fail before it takes traffic. But `uvicorn --reload` restarts on every file save, and with a 4 GB WSL memory limit, reloading the embedding, reranker, and NLI models on each restart would be slow. The setting is not added now because no Phase 0 provider has weights.

## D-036 — Verified answers are sent whole, not token-streamed
- **Date:** 2026-09-30
- **Status:** Confirmed 2026-10-06 (Phase 2 task #8); SRS v1.17 removes the `token` event (§5.4, §16.2).
- **Decision:** `LLMProvider` has no token-streaming method. The QA run streams progress events over SSE and then sends the verified answer.
- **Reason:** A3 may remove or revise claims in A2's draft, so streaming draft tokens would show users unverified text. Progress events still meet NFR-01's 2-second first event.

## D-037 — Fake providers report distinct model names
- **Date:** 2026-09-30
- **Decision:** Fakes identify themselves (e.g. embeddings as `fake-hash-384-v1`), and that name is what gets recorded per chunk (FR-07).
- **Reason:** Chunks embedded by the fake in a shared dev database can be found and re-embedded instead of silently mixing with real embeddings.

## D-038 — Dependabot keeps GitHub Actions pins current
- **Date:** 2026-09-30
- **Decision:** `.github/dependabot.yml` checks the `github-actions` ecosystem weekly. It groups all action bumps into one PR targeting `dev`, with `chore(deps):` commit messages. Dependabot PRs are exempt from the `p<phase>/` branch-name rule (CLAUDE.md §7) but still merge only through a PR with passing CI. Python dependencies (`uv` ecosystem) are not included for now. SRS §15.1 updated.
- **Reason:** Actions are pinned to commit SHAs so a moved tag can't change CI, but SHA pins don't update on their own. Without an update mechanism they would go stale and miss security fixes.

## D-039 — uv version pinned in pyproject.toml
- **Date:** 2026-09-30
- **Decision:** `backend/pyproject.toml` sets `[tool.uv] required-version = "==0.12.21"`. uv refuses to run with any other version. CI's setup-uv reads the same setting (the workflow has no separate `version:` input), so `pyproject.toml` is the single source. Upgrading uv means changing this line, and everyone upgrades together (`uv self update <version>`). SRS §15.1 updated.
- **Reason:** Different uv versions can resolve and write `uv.lock` differently, and each uv release ships a fixed set of Python builds. Pinning it keeps local development and CI identical.

## D-040 — Backend is the only database client; Data API off; automatic RLS
- **Date:** 2026-09-30
- **Decision:** The Supabase projects have the Data API (PostgREST) disabled and automatic RLS enabled for new tables in `public` (the `ensure_rls` event trigger, which runs `public.rls_auto_enable()`). The backend is the only database client. The frontend uses Supabase only for Auth and never queries tables. The backend connects as `postgres`, which owns the tables and has `BYPASSRLS`, so tables need no RLS policies. `anon` and `authenticated` get no rows: the Data API is off, and RLS with no policies denies them. The prod project must be configured the same way (step goes into `docs/SETUP.md`, task #7). SRS §14.1 and §18 updated (v1.4).
- **Reason:** All data access goes through the backend's authorization layer (user ownership and workspace filters in SQL, CLAUDE.md §2), and RLS adds defense in depth in case the Data API is re-enabled or a Supabase key leaks. Verified on dev: a table created in `public` gets `relrowsecurity = true`, and the backend still reads and writes it.

## D-041 — Alembic setup
- **Date:** 2026-09-30
- **Decision:**
  - **Configuration:** `backend/alembic.ini` has no `sqlalchemy.url`. `alembic/env.py` reads `DATABASE_URL` through `app.core.config.get_settings()` and builds its engine with the app's `create_engine_from_settings()`, so migrations use the same async psycopg driver, `prepare_threshold=None` (D-026), and connect timeout. Online mode runs migrations through `AsyncConnection.run_sync`, and offline `--sql` mode is supported.
  - **Scope:** `include_schemas=False` plus the `include_name` hook in `app/models/migration_scope.py`. Autogenerate reflects only `public`, and within it skips the LangGraph checkpoint tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`). `include_name` runs before reflection, so excluded objects are never loaded.
  - **Naming convention:** `Base` lives in `app/models/base.py`, and its metadata has a naming convention: `pk_<table>`, `fk_<table>_<cols>_<referred>`, `uq_<table>_<cols>`, `ix_<table>_<cols>`, `ck_<table>_<name>`. Check constraints must be given `name=`.
  - **Revisions:**
    - The history starts with an empty baseline revision `0001`.
    - File names are date-prefixed.
    - New revision files are run through `ruff format` and `ruff check --fix` by a post-write hook.
    - A unit test requires a single head.
  - **When migrations run:** explicitly (`uv run alembic upgrade head`), never at app startup. The deploy-time step is decided in task #7.
- **Reason:**
  - One source of configuration and one engine setup. No secret in `alembic.ini`, which also avoids ConfigParser `%` interpolation breaking on passwords.
  - Deterministic names keep autogenerate diffs stable and let downgrades drop constraints by name.
  - The single-head test catches parallel PRs that each add a migration.
  - Startup migrations would race between workers and tie app restarts to schema changes.

## D-042 — Deployment mechanics
- **Date:** 2026-10-01
- **Decision:** `backend/` is the Hugging Face Space root. `.github/workflows/deploy-backend.yml` uploads it with `hf upload --delete "*"` (huggingface_hub pinned) on push to `main`, and the Space builds `backend/Dockerfile` (`python:3.11.16-slim-trixie`, uv 0.12.21 copied from its image, user 1000, port 7860). A unit test keeps the uv tag, Python minor version, and port in step with `pyproject.toml`, `.python-version`, and the Space README. Migrations are not run by the deploy: someone runs `alembic upgrade head` against prod by hand before each `dev` → `main` merge that adds one (completes D-041). Vercel builds only `main` (`ignoreCommand` in `frontend/vercel.json`).
- **Reason:** Uploading a folder needs no git history rewriting or force-push to the Space. Migrations stay out of container start-up (D-041) and out of CI secrets. Preview builds would fail CORS against the prod Space.

## D-043 — Hugging Face PRO for the backend Space
- **Date:** 2026-10-01
- **Decision:** Since July 2026, Docker Spaces require Hugging Face PRO. The team pays for PRO (about ₹800/month) and keeps the backend on a Docker Space with Protected visibility (public app URL, private files). SRS v1.5 updates NFR-13 and §15.3.
- **Reason:** It keeps the local models (embedding, reranker, NLI) and the architecture in SRS §15 unchanged. The Docker image is portable, so the backend can move to another container host if the cost becomes a problem.

## D-044 — Chunk size fits 512-token models
- **Date:** 2026-10-02
- **Decision:** FR-06 chunks target ~350–450 tokens measured with the embedding model's tokenizer, with ~12% overlap (was 500–800 tokens, 10–15%).
- **Reason:** The embedding model and reranker truncate at 512 tokens, so 500–800-token chunks would lose text.

## D-045 — No LLM calls in Phase 1 (FR-04 and S7 split)
- **Date:** 2026-10-02
- **Decision:** Phase 1 metadata = PDF metadata + DOI regex + DOI lookup (Crossref/OpenAlex, `CONTACT_EMAIL` setting, short timeout; failure keeps PDF metadata) + title fallback to the first top-level heading. First-page LLM extraction and the S7 LLM keywords/summary move to Phase 2; S7 in Phase 1 is centroid only.
- **Reason:** Phase 1 then needs no LLM provider, and Phase 2 builds the LLM path anyway.

## D-046 — Workspace DELETE removes unshared documents
- **Date:** 2026-10-02
- **Decision:** `DELETE /workspaces/{id}` removes its document links and permanently deletes (chunks and Storage file) every document no other workspace uses. Resolves the open question from D-015.
- **Reason:** There is no standalone document library in Release 1.0, so unlinked documents would be unreachable.

## D-047 — Non-owned resources return 404
- **Date:** 2026-10-02
- **Decision:** Requests for another user's workspace, document, or other resource return 404, the same as a missing one.
- **Reason:** A 403 would reveal that the resource exists.

## D-048 — Default embedding model bge-base-en-v1.5 (768-dim)
- **Date:** 2026-10-02
- **Decision:** Default embedding model is BAAI/bge-base-en-v1.5 (768-dim); `chunks.embedding` is `vector(768)`. A sanity benchmark against bge-small (3 papers, ~15 questions) runs in task #1; switch to bge-small only if bge-base is clearly worse. The question set is small, so it catches only large differences.
- **Reason:** Better retrieval quality at an acceptable CPU cost; the schema is not created yet, so switching now is free (D-013).

## D-049 — Accepted Phase 1 risks
- **Date:** 2026-10-02
- **Decision:** (1) CPU-only torch installed from the PyTorch CPU index via uv. (2) At startup, documents left in an in-progress status are marked `failed`. (3) The backend accesses Supabase Storage with the secret key, server-side only. (4) JWTs are verified against the project's JWKS URL.
- **Reason:** Each is the simplest option that fits the free CPU host and the in-process background ingestion.

## D-050 — Default embedding model back to bge-small-en-v1.5 (reverses D-048)
- **Date:** 2026-10-02
- **Decision:** The default is BAAI/bge-small-en-v1.5 (384-dim); `chunks.embedding` will be `vector(384)`.
- **Reason:** Retrieval quality was tied with bge-base in task #1 (16 questions), and ingestion embedding is about 3× faster, which protects NFR-02 on the CPU Space.

## D-051 — Smaller reranker: ms-marco-MiniLM-L-6-v2, 20 candidates
- **Date:** 2026-10-02
- **Decision:** The reranker is cross-encoder/ms-marco-MiniLM-L-6-v2 (was bge-reranker-base), and `RERANK_CANDIDATES` is 20 (was 30).
- **Reason:** About 8.6× faster per question (1.3 s vs 11.2 s for 20 candidates locally), which protects NFR-01. Recall@5 after RRF + rerank was tied on one question set and one question lower on the other (two sets of 16 and 17 questions).

## D-052 — Schema integration tests run in CI against a pgvector container
- **Date:** 2026-10-03
- **Decision:** CI's `migrations` job runs `upgrade head → check → downgrade base → upgrade head` and the schema integration tests (`test_schema_db.py`, `test_migrations_db.py`) against a `pgvector/pgvector:0.8.2-pg17` container. `tests/integration/supabase_baseline.sql` sets it up the way Supabase is set up: `anon`/`authenticated` roles, the `extensions` schema on the search path, and Supabase's default grants. This is an exception to CLAUDE.md §4 (integration tests not in CI): these tests need no secrets.
- **Reason:** RLS and the client-role revokes are security properties; checking them on every PR is cheap. Other integration tests still need the Supabase dev project and stay out of CI.

## D-053 — Workspace repository tests also run in CI's pgvector job
- **Date:** 2026-10-03
- **Decision:** `test_workspaces_db.py` (ownership filters, D-046 deletion) joins the D-052 `migrations` job; it needs no secrets.
- **Reason:** Cross-user isolation in SQL is a security property the unit tests (in-memory store) cannot check.

## D-054 — Chunk pages are PDF page indexes
- **Date:** 2026-10-03
- **Decision:** `page_start`/`page_end` (and citations) use the 1-based PDF page index, not the printed page number.
- **Reason:** The source viewer opens pages by index; printed numbers are often missing or offset (journal page ranges).

## D-055 — `count_tokens` on the embedding provider interface
- **Date:** 2026-10-03
- **Decision:** `EmbeddingProvider.count_tokens(text)` (sync; model tokenizer without special tokens; the fake counts words) sizes chunks.
- **Reason:** FR-06 measures chunks with the embedding model's tokenizer; the chunker stays provider-agnostic and testable.

## D-056 — Only confirmed DOIs are stored
- **Date:** 2026-10-03
- **Decision:** A DOI is stored only after Crossref or OpenAlex confirms it. If the lookup is unavailable or finds no candidate, the DOI stays empty and the PDF metadata is kept (NFR-04). `ParsedPage` gains `raw_text` (the PDF's own line breaks) for the DOI search.
- **Reason:** An unverified DOI (e.g. a run-on match like "…v1Tuneable") would be indistinguishable from a real one later; a missing DOI is safer.

## D-057 — Unique content hash per user; duplicates linked with PUT
- **Date:** 2026-10-03
- **Decision:** Migration 0003 makes `documents (user_id, content_hash)` unique. The insert uses `ON CONFLICT DO NOTHING`, so a concurrent second upload waits for the first and is answered as a duplicate (200, `duplicate: true`). A duplicate is linked to another workspace with the new `PUT /workspaces/{id}/documents/{doc_id}`. A `failed` duplicate is ingested again.
- **Reason:** Without the constraint, two concurrent uploads of one file both pass the lookup and ingest twice. `ON CONFLICT` gives the same result as catching the `IntegrityError` without aborting the request's transaction.

## D-058 — Ingestion concurrency and stale sweep
- **Date:** 2026-10-03
- **Decision:** Ingestion runs as a FastAPI background task behind a semaphore (`INGESTION_CONCURRENCY`, default 1); extra uploads wait in `uploaded`. In-progress documents whose `updated_at` is older than `INGESTION_STALE_MINUTES` (15) are marked `failed` at startup and every `INGESTION_SWEEP_INTERVAL_MINUTES` (5), except documents this process still has queued or running. A failed document is re-ingested by uploading it again.
- **Reason:** One CPU-bound ingestion at a time protects query latency on the 2-vCPU Space; the periodic sweep frees documents stuck by a restart without a separate re-upload rule, and the exclusion keeps a long upload queue from being failed while it waits.

## D-059 — Exact dense search; OR full-text query
- **Date:** 2026-10-03
- **Decision:** Dense retrieval selects the workspace's chunks in a `MATERIALIZED` CTE and orders them by cosine distance (exact, never the HNSW index; a DB test checks the plan). Full-text retrieval turns `plainto_tsquery('english', q)` into an OR query by replacing `&` with `|` and parses it with the `simple` config (re-parsing with `english` would stem the lexemes twice).
- **Reason:** HNSW filters after the nearest-neighbour scan, so a small workspace could get fewer than top-k results; exact search over ≤ ~2 500 chunks per workspace (NFR-03) is fast. Requiring every term (AND) matches almost nothing for natural-language questions.

## D-060 — Compatibility check details and threshold
- **Date:** 2026-10-03
- **Decision:** A document vector is the normalized mean of its first 4 chunks. The pre-upload check (`POST …/documents/compatibility`) parses only the first 3 pages (`DocumentParser.parse` gains optional `max_pages`), stores nothing, and skips empty workspaces. The upload takes `override`, and the score is stored when the document is ready. `PUT` link of a ready document answers 409 `compatibility_warning` unless `override=true`. The threshold is 0.83: with bge-small, leave-one-out on the six benchmark papers scored 0.870–0.926 (Plasmonic lowest), and two arXiv stock-prediction papers scored 0.685 and 0.788.
- **Reason:** Parsing 3 pages (~1.3 s) keeps the check fast. bge-small cosines are high for any scientific text, so the threshold has to sit high. With 2 chunks the classes overlapped; 8 chunks widened the gap only slightly (0.863 vs 0.763).

## D-061 — Docker model download runs as local; CI builds the image for release PRs
- **Date:** 2026-10-04
- **Decision:** The Dockerfile runs `ENVIRONMENT=local python -m scripts.download_models` (runtime stays `prod`, whose validation needs Space secrets absent at build time); a `docker-build` CI job builds the image with `DOWNLOAD_MODELS=false` on PRs into `main`.

## D-062 — Hosted LLM providers, demo provider, client-side retries and rate limits
- **Date:** 2026-10-04
- **Decision:** Fast tier Groq `openai/gpt-oss-20b`, strong tier Gemini `gemini-3.5-flash-lite` (defaults), both via LangChain behind `LLMProvider`, structured output with `json_schema` validated by `parse_structured`. LangChain client retries are off; the app retries 2× with backoff. One rate limiter per (provider, model) with requests/tokens per minute and a daily request cap (in memory); at the cap, or on a provider per-day 429, calls fail at once with `llm_quota_exhausted`. A `demo` provider gives canned replies marked `[DEMO OUTPUT]` for key-free local runs and is refused in prod; `fake` stays the strict test double. A `track_usage()` scope counts LLM calls and tokens per run (NFR-13).
- **Reason:** Free-tier quotas are per model (AI Studio, 2026-10-04): every non-lite Gemini Flash allows 20 requests/day; `gemini-3.5-flash-lite` allows 15 RPM / 250K TPM / 500 RPD. Groq gpt-oss-20b: 30 RPM / 8K TPM / 1K RPD. Lite may be weaker on multi-paper reasoning and judging; task 10 compares it with `gemini-3.8-flash` on a small calibration subset. It ignores `temperature` (fixed sampling), so runs are not bit-reproducible. Separating `demo` from `fake` keeps tests strict.

## D-063 — Benchmark splits and item provenance
- **Date:** 2026-10-04
- **Decision:** Benchmark v1 has a fixed calibration split and test split recorded in the dataset file. Thresholds (S3) and all tuning use only the calibration split (the 33 Phase 1 questions may join it); C1–C5 results are reported on the test split. Each item records `drafted_by` (claude|human) and `verified_by`; reports count only verified items and state the drafted/verified split. Claude may draft items from downloaded open-access papers; the team writes or reviews the unanswerable ones.
- **Reason:** Tuning on the reported questions would inflate the results; provenance shows how much of the benchmark a human checked.

## D-064 — Chat history schema details
- **Date:** 2026-10-04
- **Decision:** Additions to the §14.1 entities: `conversations.user_id` and `conversations.mode` (default: the workspace's `default_mode`); `agent_runs.user_id`, `conversation_id`, `error` and `finished_at`; `citations.chunk_id` and a snapshot of the source (`document_title`, `page_start`/`page_end` instead of `page`, `section`, `quote`). Citation and evidence links to chunks and documents become NULL when the source is deleted. `messages.mode` can also be `general_knowledge`, and approval `options`/`decision` hold mode names. `external_source_id` waits for Phase 5, which adds it together with `external_sources`. A finished answer (message, claims, evidence, citations, run finish) is saved in one transaction.
- **Reason:** A `user_id` column lets ownership be filtered in SQL without joins. The snapshot keeps history readable after a document is deleted, and adding the external FK later avoids an empty Phase 5 table now.

## D-065 — S3 = reranker fast pass + batched LLM answerability check
- **Date:** 2026-10-04
- **Decision:** A sub-question with best reranker score ≥ `SUFFICIENCY_FAST_PASS_SCORE` (0.97) is covered without an LLM call; every other sub-question with evidence goes to one batched strong-tier call (`sufficiency_check.v1`, all 8 evidence chunks) that returns covered/partial/insufficient with a reason. The prompt leans against false `insufficient` (A3 catches unsupported claims later). The 0.97 cutoff is provisional (highest unanswerable 0.926 on an unverified split) and is recalibrated when the calibration questions are human-verified. Benchmark v1 starts now with the calibration split only (`backend/eval/data/benchmark_v1.jsonl`); task #10 adds the test split.
- **Reason:** Reranker scores alone overlap: the best single threshold (0.888) gave balanced accuracy 0.78 with 13 of 33 answerable questions judged insufficient. With the check: 1 of 33, and 0 of 20 unanswerable judged covered. Cost: at most one extra LLM call per question.

## D-066 — A2 cites evidence labels, not chunk UUIDs
- **Date:** 2026-10-05
- **Decision:** S5 labels the run's evidence set `E1..En` (chunks of covered/partial sub-questions, deduplicated); A2 cites labels and S5 maps valid ones to chunk IDs and a citation snapshot (quote = chunk sentence with most word overlap with the claim, ≤ `CITATION_QUOTE_MAX_CHARS`). A2 sentences have a kind (`evidence` needs a citation, `gap`, `general`); `general` sentences are dropped outside General Knowledge mode.
- **Reason:** Short labels are cheaper and less error-prone for the LLM than 36-character UUIDs; S5 still validates every citation against the evidence set (SRS §12.3).

## D-067 — A3 claims are A2 sentences; NLI over sentence windows, accept-only; nli-deberta-v3-xsmall
- **Date:** 2026-10-05
- **Decision:** A3 does not extract claims with an LLM: each A2 sentence that cites passages is one claim (A2 already keeps a sentence to one or two facts). NLI scores the claim against `VERIFICATION_WINDOW_WORDS` (120) sentence windows of each cited chunk, best window counts. Entailment ≥ 0.9 with no cited chunk contradicting (≥ 0.5) → supported; everything else, plus `gap` sentences with citations, goes to one batched strong-tier judge call. NLI alone never rejects (`VERIFICATION_UNSUPPORTED_SCORE` = 0). Default NLI model `cross-encoder/nli-deberta-v3-xsmall`.
- **Reason:** An extraction call would add up to 3 LLM calls per question (NFR-13). On 102 claim–evidence pairs from the calibration split (`2026-10-04T201501Z_compare_nli_3311491.json`, unverified), windows beat whole chunks for every model (xsmall AUC 0.91 vs 0.74). Every model scored some supported claims near 0, so NLI-only rejection would drop correct claims. xsmall auto-accepts 12 of 34 supported claims with 0 false accepts at 607 ms/claim (2 threads); base has AUC 0.96 but accepts "1–100 nm" against "1–100 μm" at 0.997 and costs 2452 ms/claim.

## D-068 — First-page LLM metadata only without a confirmed DOI; S7 summary refresh
- **Date:** 2026-10-06
- **Decision:** FR-04's first-page LLM call (fast tier, `first_page_metadata.v1`, page 1 cut to `METADATA_LLM_MAX_CHARS`) runs only when no DOI is confirmed; its title, authors, year, and venue replace the PDF metadata field by field, it never supplies a DOI, and a failure keeps the PDF metadata. The S7 keyword summary (strong tier, `topic_summary.v1`) reads the titles and first chunks of the 20 most recently added ready documents and is refreshed in the background after ingestion, link, and removal; workspace responses include `keywords` and `summary`.
- **Reason:** A confirmed DOI already gives authoritative metadata, so the call is saved there; the summary call must not run inside the ingestion transaction, and the document cap bounds its input.

## D-069 — Eval harness: baseline prompts in eval/, Ragas through our providers, report format
- **Date:** 2026-10-06
- **Decision:** C1/C2 prompts live in `backend/eval/prompts/` (eval-only, not `app/prompts/`) and return `{answer, abstained}` so abstention can be scored. C2 uses `RetrievalService.retrieve_dense` (dense top 8, no fusion or reranking). Ragas faithfulness and answer relevancy call the judge through `LLMProvider` (`EVAL_JUDGE_*`, default Groq `openai/gpt-oss-120b`; the strong-tier model is refused). Ragas 0.4.3 needs `langchain-community<0.4.2`. A retrieved chunk hits a gold passage when it is from the gold paper and holds the snippet (or covers the page). Reports give verified-only metrics and, until items are verified, provisional all-item metrics. Benchmark items gain `type` and `evidence`.
- **Reason:** Routing Ragas through the providers reuses retries, rate limits, usage counting, and the fakes; no item is human-verified yet, so verified-only reports would be empty.

## D-070 — Heavy LLM evaluation runs deferred to Phase 8; paid LLM credit allowed for final evaluation and demo
- **Date:** 2026-10-06
- **Decision:** Development stays on free tiers with small eval smoke runs (`--limit 2`) per phase; the C2 Ragas rerun, the `gemini-3.8-flash` comparison, and all full benchmark runs move to Phase 8, where the team may buy paid LLM credit. Before the final runs, the S3 and A3 thresholds are recalibrated on the calibration split with the final model, and C1, C2, and C5 are all rerun with that model (the task #10 numbers become development baselines); the Ragas judge stays a different model from A3's. The deployed app uses demo-only API keys, never shared with development, tests, or evaluations.
- **Reason:** Free-tier daily quotas (including Groq's tokens per day) cannot finish full benchmark runs and are shared with development, which put demos at risk; a fair comparison needs every condition on the same model.


## D-071 — Phase 2 release: hosted LLMs set in the image, NFR-01/NFR-13 on a 12-item sample, `trace_url` left empty
- **Date:** 2026-10-06
- **Decision:** The Dockerfile sets `LLM_FAST_PROVIDER=groq` and `LLM_STRONG_PROVIDER=gemini`, so prod never answers with the fake LLM (without keys it fails at startup). NFR-01 and NFR-13 are measured on the Space with `scripts/measure_qa.py` on 12 test items (7 single, 2 multi, 1 comparison, 2 unanswerable); Phase 8 repeats it on the full benchmark (D-070). `agent_runs.trace_url` stays empty; LangSmith traces are found by the `agent_run_id` metadata filter.
- **Reason:** `fake` is the config default and is not refused in prod; free-tier and demo-key quotas cannot cover the full benchmark; resolving a trace URL costs a LangSmith API call per run.


## D-072 — Chat history returns claims; `GET /runs/{run_id}` for paused runs; `GET /chunks/{id}` deferred
- **Date:** 2026-10-08
- **Decision:** `GET /conversations/{id}/messages` includes each message's claims with evidence and citations; a question stores the `run_id` of the run that answers it; new `GET /runs/{run_id}` returns the run's state and, while paused, its approval request. `GET /chunks/{id}` is not built for now; citations already carry page range and quote.
- **Reason:** without these, reloading a conversation needs one request per answer, and a run paused for approval cannot be found again (SRS §20).

## D-073 — Paper & ink design system; landing page added to Phase 3
- **Status:** superseded: motion by D-074, visual direction by D-088.
- **Date:** 2026-10-08
- **Decision:** The frontend uses the "Paper & ink" theme (warm paper, ink, one marker-yellow highlight, Newsreader headings, light + dark following the system with a toggle), with rules in `.claude/skills/ui-design` and `trust-ui`. Phase 3 gains task #2b, a landing page at `/` with CSS-only animations (no new npm dependencies).
- **Reason:** the team asked for a research-specific look that avoids generic AI styling; the SRS Phase 3 scope had no landing page.

## D-074 — `motion` for animation; `docs/DESIGN.md` is the design source
- **Status:** fonts and tokens superseded by D-088; `motion` and `docs/DESIGN.md` as the design source stand.
- **Date:** 2026-10-08
- **Decision:** The frontend adds `motion` (`motion/react`) for the landing page's hero demo, scroll-driven sections and count-ups, replacing D-073's "CSS-only, no new npm dependencies". Visual and motion rules live in `docs/DESIGN.md` (IBM Plex fonts via `next/font`, hex tokens); `.claude/skills/ui-design` now points there. The navbar uses a solid 95% paper background instead of backdrop blur.
- **Reason:** the team's redesign brief needs sequenced, interruptible animation that CSS alone cannot express cleanly.

## D-075 — Functional UI first, one polish pass after Phase 7
- **Status:** timing superseded by D-088 (the redesign starts before Phase 7, in steps).
- **Date:** 2026-10-08
- **Decision:** Phase 3–7 screens are built functional and tidy: design tokens, accessibility (DESIGN.md §8) and the `trust-ui` rules still apply; the per-PR checks in DESIGN.md §10 and visual or motion polish are deferred to a new UI polish pass between Phase 7 and Phase 8, where the team brings new designs. §22.1's first cut ("merge UI polish") still refers to the Phase 6 merge screen only.
- **Reason:** the team plans a redesign after the core features; polishing each screen now would be redone then.

## D-076 — Phase 3 deployed before the E2E test (interim release)
- **Date:** 2026-10-08
- **Decision:** `dev` is released to `main` and deployed after task #6, before task #7 (Playwright E2E). The E2E test stays on the Phase 3 list and runs against the deployed app afterwards; `phase-3-done` is tagged only when it passes (SRS §22 exit criterion unchanged).
- **Reason:** the team wants to check the UI on the real deployment first; the E2E test needs the Phase 3 UI deployed anyway.

## D-077 — Discover: user-started search and open-access import, brought forward from Phase 5
- **Date:** 2026-10-15
- **Decision:** A Discover page searches arXiv (Atom API) and OpenAlex and imports a paper's open-access PDF into a chosen workspace (`GET /papers/search`, `POST /workspaces/{id}/import`; FR-17 in part, S9). A search or import started by the user on Discover is their consent for that external call. It is separate from QA knowledge modes, which are unchanged (corpus-only by default; no web use in a run without a recorded approval). An imported paper becomes an ordinary corpus document: it goes through the same ownership check, compatibility check (409 until "Import anyway"), duplicate handling and ingestion as an upload, with `source=import` and the paper's landing URL. Results are importable only when a listed PDF answers with a PDF at search time (OpenAlex locations probed with a ~1 KB ranged GET within an 8 s budget; arXiv's own PDFs trusted); papers without one are link only, and nothing is stored for them. PDF downloads use httpcore with a pinned network backend: each connection resolves the host once, requires every address to be public, and connects to that validated IP, so redirects and DNS rebinding cannot reach internal addresses. Only http(s) on ports 80/443, no credentials, at most 3 redirects, the 25 MB upload cap while streaming, and a `%PDF-` check. Google Scholar (no API; scraping is out of scope) and Semantic Scholar are not used. Not built yet: related papers (FR-16), metadata-only save and `external_sources`, response caching, Europe PMC, Unpaywall.
- **Reason:** the team approved Discover as the next differentiating feature; checking the socket destination is the only reliable SSRF guard for URLs that come from third-party metadata, and many listed open-access PDFs sit behind publisher bot protection (2 of 7 downloaded in a live check), so a listing alone cannot mark a paper importable.

## D-078 — Evidence-provenance graph retired; Semantic Research Knowledge Graph planned next
- **Date:** 2026-10-15
- **Decision:** The Phase 4 evidence graph (`GET /workspaces/{id}/graph` and its React Flow screen) is removed. Contradictions, gaps, comparison, saved findings and citation verification are unchanged. A Semantic Research Knowledge Graph is the next major feature after Discover; it will be specified (scope, data, evidence rules) and approved before work starts. `@xyflow/react` stays installed for it.
- **Reason:** the team judged that the evidence graph only re-drew records already visible elsewhere and added nothing new; the planned graph is meant to add research value instead.

## D-079 — Discover reliability: separate timeouts, bounded retries, three PDF states
- **Date:** 2026-10-15
- **Decision:** Discover search and paper lookups use their own 15 s timeout (`DISCOVER_TIMEOUT_SECONDS`) and retry a timeout, network error, 429 or 5xx once; DOI lookups during ingestion keep 5 s and no retry. A PDF download retries a timeout, network error, cut-off body, 429 or 5xx once, never a 401/403/404, a non-PDF, an oversize file or an unsafe destination; one download is bounded by 90 s and an import's locations together by 120 s, trying up to 5 locations. Failures carry a `reason` and `retryable` flag; a failed lookup is `source_unavailable`. Search reports `pdf_status`: `verified` (a PDF answered a 1 KB check), `unverified` (a PDF link not checked, as for arXiv, or the check was inconclusive), `none` (link only; locations that refused or returned a page are dropped). "Importable PDFs only" asks OpenAlex for open-access works (`open_access.is_oa:true`) and hides link-only papers. Each import stage is logged with an import id and timings, without user data or content. No new source is added.
- **Reason:** the "Timed out." seen in manual testing could only come from the paper lookup at import (5 s, no retry; its raw message reached the UI), and a live run showed OpenAlex searches exceeding 5 s on all attempts. In a live sample of 80 OpenAlex results across eight fields (computer science, physics, economics, climate, education, materials, psychology, mathematics; 10 each), the open-access filter raised verified PDFs from 24 to 35, and exact arXiv title matches rescued 0 of 56 papers without a working PDF. For biomedical papers, Europe PMC PDF links returned 403 (0 of 5) and the NCBI PMC OA service redirected to HTML. Unpaywall's data already feeds OpenAlex. Coverage varies by field (physics 9 of 10, economics 0 of 10); the project is not tied to one domain.

## D-080 — OpenAlex API key and quota handling; faster search checks; slow-import feedback
- **Date:** 2026-10-16
- **Decision:** An optional `OPENALEX_API_KEY` is sent to OpenAlex only, in the `Authorization: Bearer` header (never in URLs or logs, never to clients). A 429 whose `Retry-After` exceeds 5 s is a used-up quota: it is not retried, OpenAlex searches pause until `Retry-After` while single-paper lookups (free) continue, and search responses list the source in `quota_exhausted` so the UI explains it while still showing arXiv results. The PDF check budget per search drops from 8 s to 4 s; papers whose check does not finish stay "PDF link found, not verified" and can be imported. Import timeouts are unchanged (per step 30 s, per download 90 s, per import 120 s). Discover defaults to all papers; "Importable PDFs only" is a switch that reruns the active search, as does changing the source. A row importing for over 10 s says the source is responding slowly, and after 45 s that the import stops by itself if the PDF cannot be downloaded; there is no percentage.
- **Reason:** measured on 2026-10-15 (eight fields): search took a median of 7–8 s and up to 11 s, of which the PDF check was 5–8 s, held to its full budget in half the searches by a few slow hosts (www.nber.org answers after about 20 s); the APIs took 1.7 s. Imports took 2.5–6 s (lookup 0.6–1.1 s, download 0.5–2.7 s, compatibility check about 4 s), and the slowest legitimate PDF host measured (about 21 s) fits the existing limits, so shortening them would only add failures for large or slow repositories. OpenAlex's keyless budget is 1,000 credits a day per IP (a search costs 10; lookups are free), about 100 searches a day for every user of the Space together; the measurements used it up.

## D-081 — Semantic Research Knowledge Graph specified: S10 service, closed vocabulary, passage-validated relationships, separate graph tier
- **Date:** 2026-10-18
- **Decision:** The knowledge graph (FR-33, SRS §9.1) is built by S10 Knowledge Graph Service, which makes bounded LLM calls; it is not a new agent and not a LangGraph workflow. Vocabulary v1: entity types concept, method, dataset, metric, task, tool, finding; relationship types uses, evaluated_on, measured_by, addresses, compared_with, reports. There is no generic `related_to`, `improves_on` is deferred, and extraction never creates contradiction edges. A relationship is kept only if its cited passage states it: a verbatim quote of at most two sentences, both entities named in that quote, stated about the paper's own work and not hedged, and local NLI entailment of the relationship's statement above a provisional threshold; anything else is rejected. Entities merge only on equal type and normalized name, and findings never merge across papers. Extractions are stored per paper and extractor version and reused across the same user's workspaces. The workspace graph is rebuilt in one transaction. A workspace has at most one active job (database constraint); one graph job calls the LLM at a time; the checkpoint unit is one paper. There is no automatic resume: the sweep fails only jobs not running in this process whose heartbeat (written every minute, also while waiting for rate limits) is stale, and Retry/Update continues from completed papers. A third LLM tier, "graph", has its own model, optional key, rate limiter and per-job call budget, defaults to `fake`, and gets its model from a structured-output test (SRS §9.1 criteria). New tables arrive in migration 0008, dev first. The page is a dedicated wide React Flow page.
- **Reason:** the team approved the architecture audit (`docs/KNOWLEDGE_GRAPH_ARCHITECTURE_AUDIT.md`) with these changes. Generic edges and co-mention links would rebuild the graph the team retired in D-078. Naming both entities in a passage does not show that the passage states their relationship, hence the quote and entailment rules. A long job on the strong tier would use up the 500-requests-a-day quota that Q&A needs, and the QA run sweep would fail a job older than 15 minutes, hence the separate tier and the job table with its own heartbeat. Reusing per-paper extractions saves quota and makes restarts and incremental updates cheap.

## D-082 — Knowledge graph Phase 1: jobs, checkpoints, and state; defaults
- **Date:** 2026-10-18
- **Decision:** Migration 0008 creates the nine knowledge graph tables of SRS §14.1 with RLS. `kg_jobs` has a partial unique index on `workspace_id` for queued or running jobs. `POST /workspaces/{id}/knowledge-graph/jobs` takes no body: the job is `update` when the workspace already has a graph, otherwise `generate`. It answers 202 for a new job, 200 with the active job, 409 `no_ready_documents`, and 503 until an extractor and a graph builder are configured (Phase 2). The ownership check comes before the 503, so a stranger gets 404. `GET .../knowledge-graph` returns the derived state and staleness; staleness compares a SHA-256 of the extractor version and the sorted ready document ids with the fingerprint the build recorded. Defaults: heartbeat 60 s, stale after 10 min, sweep every 5 min, 150 graph-tier calls per job (`KG_*` settings; the heartbeat must be shorter than the stale time). Job failures are stored as `error_code` (`interrupted`, `llm_quota_exhausted`, `budget_exceeded`, `internal_error`, or the domain error's code) with a plain message. Unexpected errors are logged but never shown.
- **Reason:** D-081 Phase 1. The client never chooses the kind, so it cannot ask for a fresh Generate over an existing graph by mistake. Extraction checkpoints already make an Update read only new papers. The stale time leaves room for ten missed heartbeats, and 150 calls cover a 10-paper workspace at 4 passages per call (about 115) with a margin. All defaults are provisional until measured in the quality phase.

## D-083 — Knowledge graph Phase 2: graph tier, extraction, validation, build, read API
- **Date:** 2026-10-18
- **Decision:**
  - **Graph tier:** `LLM_GRAPH_PROVIDER` (fake, groq or gemini; never demo), `LLM_GRAPH_MODEL`, optional `LLM_GRAPH_API_KEY`, and `LLM_GRAPH_RPM/TPM/RPD` (provisional 10, 8,000, 300). It is built by its own factory function with its own rate limiter. Startup refuses a graph model equal to the fast or strong model unless the graph tier has its own key. While the provider is `fake`, no extractor is wired and starting a job answers 503. The Dockerfile is unchanged, so production stays off.
  - **Extraction:** passages under 40 words, reference lists (judged by content: at least half the lines are short numbered or DOI/"et al." + year entries) and back matter (by section label) are skipped. At most 60 passages per paper, 4 per call, 1,500 output tokens. The extractor version `kg-extraction.v1+rules.v1` covers both prompt and rules.
  - **Validation:** rules apply in order and each rejection is counted by name: label, verbatim quote of at most 2 sentences and 600 characters (stored as the exact passage span), endpoints and allowed types, both non-finding names as whole words in the quote, own-work stance with a future-work phrase backstop, then NLI (entailment ≥ 0.9, contradiction < 0.5, provisional).
  - **Entities:** an entity is kept through a kept relationship, or alone if its name is in its passage. A finding exists only through a kept relationship, with its statement as the NLI hypothesis.
  - **Invalid replies and budget:** an invalid reply is retried once. A paper is `failed` only if every batch is invalid, and a later attempt replaces a failed extraction. The extractor checks before a paper's first call that the job budget covers all its batches.
  - **Build:** groups mentions by type and normalized key, merges an acronym with its expansion only where a passage of the workspace states both, stores `compared_with` in a fixed order, and drops self-loops. It replaces nodes and edges and upserts `kg_graphs` in one transaction.
  - **Read API:** graph reads and node/edge evidence (in the `CitationRead` shape) count only papers currently linked and ready; at most 500 nodes, most-supported first, with `truncated`.
- **Reason:** D-081 Phase 2 as planned and approved on 2026-10-18. The read API is built now so Phase 3 is frontend only. Lengths are checked in code rather than in the JSON schema, so providers that reject schema constraints still work. Every default stays provisional until the model check and the Phase 4 quality run.

## D-084 — Knowledge graph: provisional Gemma extractor, attribution context, isolated relationship judge prototype
- **Date:** 2026-10-18
- **Decision:**
  - **Provisional extractor:** `gemma-4-26b-a4b-it` with prompt `kg_extraction.v2` and `KG_MAX_OUTPUT_TOKENS` 3,000 (was 1,500) is the provisional extractor, not the final one. Groq `openai/gpt-oss-120b` is not used as the extractor.
  - **Schema rejections:** on the graph tier only, a provider refusing its own reply for the schema (Groq HTTP 400 `json_validate_failed`) counts as an invalid reply, retried once, not as an outage.
  - **NLI stays at 0.9:** `KG_RELATION_ENTAILMENT_SCORE` is unchanged. Both NLI cross-encoders scored true and false relationships, and forward and reversed statements, alike (0.93–0.998), so a higher threshold is not justified; NLI acts as a consistency filter only.
  - **Attribution context:** `attribution_context` gives the sentence before a quote, from its passage, from the previous passage, or explicitly none. It is never evidence and never replaces the verbatim quote.
  - **Judge prototype:** `services/knowledge_graph_judge.py` (prompt `kg_relationship_judge.v1`) returns stated / not_stated / other_work verdicts per candidate, one call per paper. Missing, contradictory or unparseable verdicts count as not stated, so it can only remove relationships. It is not wired into graph generation.
  - **Evaluation set:** `eval/data/kg_judge_v1.jsonl` has 31 candidates: 24 rebuilt from the saved model-check reports without new extraction calls, plus 7 constructed from the same quotes. Labels were drafted by Claude and await human verification.
- **Reason:** the model checks (2026-10-18) showed JSON validity fixed by prompt v2 but precision around 0.6 for Gemma and 0.4–0.5 for Groq. Half the false relationships credited cited work (e.g. "Wang ... found") to the paper, and that attribution sat in the sentence before the quote, out of reach of quote-only rules. Groq also failed first-attempt validity (11/17) at about 1.7× Gemma's tokens per call, above its daily token cap for a 10-paper workspace.

## D-085 — Knowledge graph: deterministic attribution check (rules.v2), no LLM judge, graph-tier retries
- **Date:** 2026-10-20
- **Decision:**
  - **No LLM judge:** the relationship judge prototype stays unintegrated. A PROVISIONAL run (unverified Claude-drafted labels, `kg_judge_eval --provisional`) scored precision 0.33 against 0.42 with no judge, and caught 0 of 8 cited-work rows.
  - **Attribution check (rules.v2):** `attribution_problem` rejects a relationship (`attributed_elsewhere`) only on strong signs of cited or background research, reading the quote with its `attribution_context`. Own-work markers in the quote always keep it. `EXTRACTOR_VERSION` becomes `kg-extraction.v2+rules.v2`, so every paper is pending again.
  - **Sentence splitting:** "et al." no longer ends a sentence, so a context sentence keeps its cited author.
  - **Graph-tier retries:** `LLM_GRAPH_MAX_RETRIES` (default 4) and `LLM_GRAPH_RETRY_BASE_SECONDS` (default 10, so waits of 10, 20, 40 and 80 s) apply to the graph tier only; chat keeps `LLM_MAX_RETRIES` and `LLM_RETRY_BASE_SECONDS`.
- **Reason:** the model checks showed that most false relationships credit cited work to the paper. Rules can catch the clear cases at no LLM cost. On the 31 provisional examples the check rejected 7 of 8 cited-work rows and 0 of 23 others; on 11 local papers (about 2,900 sentences, unseen while the rules were written) it flags 44 sentences, all read by hand as cited or background work, after fixing the 4 false positives earlier drafts produced (a concessive "Although ... have been proposed", an own "has been observed", and two "consistent with previous reports/work"). Gemma 503 outages lasted longer than the 1 s and 2 s chat backoff.

## D-086 — Knowledge graph rules.v3: review papers, identity, cut concepts
- **Date:** 2026-10-20
- **Decision:**
  - `is_review` marks a paper whose title ("Perspectives", "survey", "advances in", ...) or first three passages ("in this review") call it a review. In a review, `attribution_problem` keeps a quote only in the review's own voice (we, our, here, this review): `review_literature` otherwise.
  - In any paper, a quote crediting "the authors" without the first person, right after a sentence reporting a cited study, is `cited_study`.
  - `names_as_identity` rejects a relationship whose quote names one entity as the other (`identity_not_relation`); `inside_phrase` rejects a `uses` target concept that every mention runs into a longer noun phrase (`entity_inside_phrase`).
  - `EXTRACTOR_VERSION` becomes `kg-extraction.v2+rules.v3`: existing extractions are stale and the next Update rereads every paper.
  - Isolated entities stay in the graph data; the UI shows connected nodes by default and reveals isolated ones on request.
- **Reason:** the first dev job (2026-10-20) kept 11 relationships, 4 of them wrong: 2 cited studies in a review ("In this study, the authors developed ...", "Furthermore, in a murine model ..."), an identity read as `uses`, and a concept cut from "Between-the-Eyes area". Replayed offline, rules.v3 rejects those 4 and keeps the other 7; the 31 provisional examples all match their labels; review detection is right on all 11 local PDFs (5 reviews, 6 research papers); the research-paper sentence scan finds no new flags.

## D-087 — Knowledge graph frozen as an experimental, initial-phase feature
- **Date:** 2026-10-20
- **Decision:** the Semantic Research Knowledge Graph stays in the product as implemented (jobs, rules.v3 extraction and validation, build, read API, graph page) and is presented as experimental. No further extraction experiments, rebuilds, model evaluations, or graph UI polish for now. Better semantic extraction, measured relationship accuracy, entity consolidation, cross-paper connections, and type and support filters are future scope (SRS §9.1).
- **Reason:** the end-to-end path works and every kept relationship has a verbatim, verified passage, but quality (about 3 of 7 clearly correct on hand review) and density (7 edges for 116 nodes on 3 papers) are not yet at the finished-feature bar, and further gains need a larger extraction effort than the remaining schedule allows.

## D-088 — Design direction: precise research workspace replaces "Paper & ink"
- **Date:** 2026-10-20
- **Decision:**
  - `docs/DESIGN.md` is rewritten for a precise research-workspace direction: Geist Sans for the interface, Geist Mono for technical metadata, Newsreader only for text quoted from papers; cool neutral surfaces, indigo only for interaction (primary action, active nav, focus, links), yellow only for evidence highlighting; a collapsible, workspace-aware sidebar shell; the source viewer beside the answer on wide screens.
  - DESIGN.md separates the current implementation (§0) from the target, and lists the implementation order (§13); the UI is redesigned in steps, each a PR into `dev`, starting with the foundation and app shell. This replaces D-075's single polish pass between Phase 7 and Phase 8 (SRS §22, v1.29).
  - `PRODUCT.md` is corrected: domain-general users, implemented, experimental (knowledge graph, D-087) and planned features listed separately; the next planned feature is Research Gap Discovery over the user's own papers (cited candidate gaps, not novelty claims), with external-literature checks as later enhancements. FR-21 is unchanged. The `ui-design` skill points to the new rules; `trust-ui` is unchanged and still governs the evidence UI.
  - Fonts load through `next/font/google`; no new npm dependency. No frontend code changes in this decision.
- **Reason:** the editorial "Paper & ink" look (serif headings, ink-filled actions, no accent colour) and the single-column, hub-and-spoke layout made the app feel basic and student-like (Phase 0 UI audit, 2026-10-20). Two voices (sans for the system, serif for sources) keep the useful part of the old direction as a trust signal. Proposed token contrast was computed with the WCAG formula: text ≥ 4.88:1 on every surface, control borders ≥ 3.2:1.
