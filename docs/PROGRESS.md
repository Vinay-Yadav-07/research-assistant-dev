# Progress

Last updated: 2026-10-20 · SRS version: 1.29

## Current status

| Track | Current | Status |
|---|---|---|
| Backend | Phase 4 — Research Intelligence | In progress (plan approved 2026-10-09) |
| Frontend | Phase 3 — Frontend Core | Done (tag `phase-3-done`) |
| Cross-phase | Discover search and import (D-077); evidence graph retired (D-078) | Merged into `dev` (PR #68) |
| Design | Design direction and product docs (D-088): `PRODUCT.md`, `docs/DESIGN.md` (current vs target), `ui-design` skill, SRS v1.29 | Docs only, on `feat/design-direction-docs`; UI not yet changed. Next: foundation and app shell (DESIGN.md §13 step 1) |
| Cross-phase | Semantic Research Knowledge Graph (D-081–D-087) | **Experimental, frozen 2026-10-20**: implemented end to end and reviewed in the browser; merged into `dev` (PR #69), not deployed. Limitations and future scope in SRS §9.1 |

## Phase 0 task branches

Each branch is created from an up-to-date `dev`, has its own plan approved before implementation, and merges into `dev` through a PR with passing checks.

| # | Branch | Scope | Track | Status |
|---|---|---|---|---|
| 1 | `p0/resolve-spec-issues` | SRS v1.2, CLAUDE.md updates, DECISIONS.md, PROGRESS.md | — | Done (PR #2) |
| 2 | `p0/backend-skeleton` | uv project, `app/` layout, pydantic-settings config (incl. CORS origins, provider selection), `.env.example`, logging, error model, `/health`, `/health/ready`, tests for health and config | Backend | Done (PR #3) |
| 3 | `p0/providers` | Provider interfaces (LLM, embedding, reranker, NLI, parser, search) and fakes in `app/providers/fakes/`, selected through config; tests | Backend | Done (PR #4) |
| 4 | `p0/alembic` | Alembic initialized against Supabase, excluding `auth`, `storage`, and checkpoint tables; no domain tables | Backend | Done (PR #7) |
| 5 | `p0/frontend-skeleton` | Next.js (TypeScript strict, Tailwind, shadcn/ui), `gen:api`, page calling `/health` through the generated client; adds the frontend lint and build job to `.github/workflows/ci.yml` | Frontend | Done (PR #9) |
| 6 | `p0/ci` | GitHub Actions: ruff check, ruff format check, mypy, unit tests; frontend lint and build. Backend job done here; the frontend job is added by task #5 | Both | Backend done (PR #6); frontend job added in task #5 |
| 7 | `p0/deploy` | Backend Dockerfile, Hugging Face Spaces, Vercel, `docs/SETUP.md` with step-by-step account and secret setup | Both | Done (PR #10) |

## Phase 1 task branches

Decisions made before Phase 1: D-044 to D-049 (SRS v1.6).

| # | Branch | Scope | Status |
|---|---|---|---|
| 1 | `p1/local-models` | sentence-transformers embedding, reranker, NLI providers; `PRELOAD_MODELS`; weights baked into the image; CPU benchmark and embedding comparison scripts | Done (PR #13) |
| 1a | `p1/fast-models` | bge-small + MiniLM reranker defaults, 20 rerank candidates (D-050, D-051); `RUN_BENCHMARK_ON_STARTUP`; reranker quality check | Done (PR #14) |
| 2 | `p1/schema` | First domain migration: pgvector, workspaces, documents, workspace_documents, chunks (`vector(384)`), topic_profiles; explicit RLS; revoke `anon`/`authenticated`; CI migration job | Done (PR #15) |
| 3 | `p1/auth-workspaces` | JWT via JWKS (FR-01), workspace CRUD (FR-02, D-046), 404 for non-owned (D-047), cross-user tests | Done (PR #16) |
| 4 | `p1/pdf-parser` | PyMuPDF4LLM parser provider, scanned-PDF check, sections, chunker (FR-05, FR-06) | Done (PR #17) |
| 5 | `p1/metadata-doi` | PDF metadata, DOI regex, Crossref/OpenAlex lookup, title fallback (FR-04, D-045) | Done (PR #18) |
| 6 | `p1/ingestion` | Upload (FR-03), Storage, background ingestion with status, startup sweep, embedding (FR-07), FR-31 document side | Done (PR #19) |
| 7 | `p1/retrieval` | Hybrid retrieval with RRF and reranker (S2, FR-08), retrieval debug endpoint, cross-workspace tests | Done (PR #20) |
| 8 | `p1/compatibility` | S7 centroid topic profile and compatibility check (FR-22) | Done (PR #21) |
| 9 | `p1/phase-1-done` | Deploy; NFR-02 and CPU latency measured on the Space; exit criteria; experiment log | Done (tag `phase-1-done`) |

## Phase 2 task branches

Plan approved 2026-10-04 with additions (D-062, D-063; general-knowledge claims are never marked supported).

| # | Branch | Scope | Status |
|---|---|---|---|
| 1 | `p2/llm-providers` | Groq + Gemini providers, retries, rate limiter, per-run usage counter, LangSmith settings, demo LLM | Done (PR #27) |
| 2 | `p2/chat-schema` | Migration 0004 (conversations, messages, claims, evidence, citations, approvals, agent_runs, eval tables), FR-25 endpoints | Done (PR #28) |
| 3 | `p2/query-analyzer` | A1, S6 input guardrail and out-of-scope route | Done (PR #29) |
| 4 | `p2/sufficiency-gate` | S3 thresholds calibrated on the calibration split | Done (PR #30) |
| 5 | `p2/synthesis-citations` | A2, S5 | Done (PR #31) |
| 6 | `p2/verification` | A3 (NLI + batched judge); NLI model choice | Done (PR #32) |
| 7 | `p2/qa-graph` | LangGraph QA graph, checkpointer (`langgraph` schema), S4 interrupt, agent_runs | Done (PR #33) |
| 8 | `p2/chat-sse` | SSE message endpoint, resume endpoint | Done (PR #34) |
| 9 | `p2/llm-metadata-keywords` | FR-04 LLM metadata, S7 keywords/summary | Done (PR #35) |
| 10 | `p2/eval-harness` | `backend/eval/`, benchmark v1 (calibration/test splits), C1/C2 | Done (PR #36) |
| 11 | `p2/phase-2-done` | Deploy, NFR-01 and LLM calls/question, exit criteria | Done (PR #37); results on `p2/phase-2-results` |

## Phase 3 task branches

Plan approved 2026-10-08: backend gaps first (D-072), then the UI. From task #3 on, screens are functional first; visual polish waits for the UI polish pass after Phase 7 (D-075). Frontend decisions (2026-10-08):

- **Approval card:** "Stay corpus-only" and "Use general knowledge" (works today); "Search external sources" shown disabled until Phase 5 (the stub only answers corpus-only with a notice). The backend keeps offering all three.
- **Data fetching:** TanStack Query for REST data (document status polling, cache refresh after upload/answer); the SSE chat stream uses a small custom fetch reader.
- **Corpus + Web mode:** disabled with a "Phase 5" tooltip in the mode selector and the workspace default-mode setting; an existing `corpus_web` conversation still shows its true mode.
- **E2E:** Playwright as a `workflow_dispatch` job (never on push) with secrets `E2E_BASE_URL`, `E2E_EMAIL`, `E2E_PASSWORD`; same env runs it locally. Trace/video uploaded as artifacts; the test deletes its workspace.
- **Email confirmation:** on in prod (checked in the dashboard), off in dev. The UI needs a "check your email" state; prod Site URL must be the Vercel URL; the E2E user is created in the dashboard with "Auto Confirm User".
- **Prod sign-up stays off** (invite-only): the team creates accounts in the prod dashboard (Authentication → Users → Add user, "Auto Confirm User"); sign-in works for them. The sign-up screen is still built (dev allows sign-up) and shows "Sign-up is closed" when the server refuses it. Reason: Supabase's built-in mailer only reaches project team members, and open sign-up would expose the demo LLM quota. Opening it later (e.g. Phase 8 demo) needs custom SMTP and the Site URL, no code change.

| # | Branch | Scope | Status |
|---|---|---|---|
| 1 | `p3/chat-history-api` | History returns claims and citations; the question stores its `run_id`; `GET /runs/{id}` with the pending approval (D-072) | Done (PR #41) |
| 1a | `p3/fix-message-order` | Migration 0006: `messages.created_at` defaults to `clock_timestamp()` (flaky history order, see Known issues) | Done (PR #43) |
| 2 | `p3/ui-skills` | `.claude/skills/` `ui-design` (Paper & ink theme, motion and copy rules) and `trust-ui`; light/dark tokens, Newsreader headings, no-flash theme script (D-073) | Done (PR #42) |
| 2b | `p3/landing` | Landing page at `/` per `docs/DESIGN.md`: looping hero demo (real Pang 2023 passage), sticky "How it works", chatbot comparison, provisional results, footer with API dot; `motion` added (D-074) | Done (PR #44) |
| 3 | `p3/auth` | Supabase login/sign-up, session, authenticated API client | Done (PR #45) |
| 4 | `p3/workspaces-library` | Workspace list, upload, statuses, compatibility and duplicate dialogs | Done (PR #46) |
| 5 | `p3/chat` | SSE reader, progress, claims with status, citation chips, approval card, mode badge | Done (PR #47) |
| 5a | `p3/fix-gk-abstain` | General-knowledge approval answered with an abstention: synthesis prompt v2; "?." in the abstention text | Done (PR #48) |
| 6 | `p3/source-viewer` | react-pdf viewer opening the cited page with the quote highlighted | Done (PR #49; highlight fix #50, chat feedback fix #51) |
| 7 | `p3/e2e` | Playwright upload → ask → open highlighted citation on the deployed app | Done (PR #54) |
| 8 | `p3/fix-perf` | Later questions hidden until answered (chat); metadata lookup runs while embedding (ingestion) | Done (PR #57) |

## Phase 4 task branches

Plan approved 2026-10-09. Analysis runs on demand (POST endpoints returning JSON), never during upload or chat, so NFR-01/NFR-02 are unaffected; chat `comparison` intents stay on A2.

| # | Branch | Scope | Status |
|---|---|---|---|
| 1 | `p4/research-schema` | Migration 0007: `saved_findings`, `contradictions`, `research_gaps` (RLS); `ResearchRepository` | Done (PR #58) |
| 2 | `p4/compare` | A4 `ComparisonTable`, per paper × attribute retrieval, cells cited or "Not reported"; `POST /compare` | Done (PR #59) |
| 3 | `p4/synthesize` | A4 `ThemeSynthesis`; cross-paper claims cite every named paper; `POST /synthesize` | Done (PR #60) |
| 4 | `p4/contradictions` | Findings per paper → NLI screen → LLM context check; stored; `POST /contradictions` | Done (PR #61) |
| 5 | `p4/gaps` | Corpus gaps from limitations/future work, each with evidence; `POST /gaps` | Done (PR #62) |
| 6 | `p4/findings-export` | Saved findings API; Markdown and BibTeX export | Done (PR #63) |
| 7 | `p4/graph-api` | `GET /workspaces/{id}/graph` from DB records (retired, D-078) | Done (PR #64) |
| 8 | `p4/analysis-ui` | Compare, synthesis, contradictions, gaps, save, findings + export screens | Done (PR #65) |
| 9 | `p4/evidence-graph-ui` | React Flow evidence graph (retired, D-078) | Done (PR #66) |
| 10 | `p4/phase-4-done` | Exit criteria measured, PROGRESS/DECISIONS, manual checklist | To do |

## Cross-phase features

Approved 2026-10-15 outside the phase order (CLAUDE.md §2). Status: **Implemented** (code and tests on the branch) · **Locally verified** (what was run) · **Deployed** (on the Space and Vercel).

| Feature | Branch | Implemented | Locally verified | Deployed |
|---|---|---|---|---|
| Discover: search arXiv and OpenAlex, import open-access PDFs into a workspace (D-077) | `feat/research-discovery` | Yes | Unit tests (search, PDF probe, SSRF guard, import route); live arXiv/OpenAlex tests; on Supabase dev: arXiv search → import of 1706.03762 → ingestion (15 pp.) → cited answer from that paper | No |
| Discover reliability: timeouts, bounded retries, PDF status, importable-only filter (D-079) | `feat/research-discovery` | Yes | Unit tests (retry, timeout, 403, cut-off body, network failure, probe vs. download, alternative locations, error messages); live search and end-to-end import on Supabase dev | No |
| Discover: OpenAlex key and quota handling, 4 s PDF check, all-papers default, slow-import notes (D-080) | `feat/research-discovery` | Yes | Unit tests (key header only to OpenAlex, quota not retried, search pause, lookups continue, partial results, slow-import note); live: quota path returns arXiv results without further OpenAlex searches. Re-measured 2026-10-16 with an OpenAlex key, 16 searches in eight fields: median 5.4 s, max 6.5 s (was 7-8 s, max 11 s); PDF labels identical at 4 s and 8 s on 3 slow queries | No |
| Evidence-provenance graph retired (D-078) | `feat/research-discovery` | Yes | Unit tests, research DB integration tests, frontend build | No |
| Semantic Research Knowledge Graph: architecture audit and specification (D-081, SRS §9.1) | `feat/semantic-knowledge-graph` | Specified (Phase 0) | — | No |
| Knowledge graph Phase 1: migration 0008, repository, job runner, state API (D-082) | `feat/semantic-knowledge-graph` | Yes; starting a job answers 503 until Phase 2 adds extraction | Unit tests (runner, API, models, migration scripts); migration SQL rendered offline and matched to the models; migration 0008 applied to Supabase dev, `alembic check` clean; DB integration tests on dev: 44 passed (9 new: one active job per workspace, owner scoping, idempotent per-paper extraction, cascades, heartbeat sweep); app starts against dev | No |
| Knowledge graph Phase 2: graph tier, extraction with evidence validation, atomic build, nodes/edges/evidence API (D-083) | `feat/semantic-knowledge-graph` | Yes; off until a graph model is chosen (no real LLM call made yet) | Unit tests (extraction rules, normalization, grouping, tier isolation, API); DB integration tests on dev: 15 knowledge graph tests pass (merge across papers, live hiding of removed papers, shared papers, atomic rebuild, failed-extraction replacement) | No |
| Knowledge graph attribution check (rules.v2) and graph-tier retries (D-085, SRS v1.26) | `feat/semantic-knowledge-graph` | Yes (generation still off: `LLM_GRAPH_PROVIDER=fake`) | Unit tests: 7 cited/background rejections, 17 own-work regressions, validation with the previous passage, "et al." splitting, graph-only retry settings, 10/20/40/80 s backoff. PROVISIONAL offline score on the 31 unverified examples: 7 of 8 other-work rejected (kgj-001, "In this study, the authors introduced ..." in a review, is kept), 0 of 13 stated and 0 of 10 not-stated rejected. Unseen check on 11 local PDFs (5 own-work arXiv papers, 6 reviews; about 2,900 sentences): 44 flagged, all cited or background work by hand review; 4 false positives from earlier drafts fixed and kept as regression tests (concessive "Although ... have been proposed, it was possible ...", own "has been observed", two "consistent with previous reports/work") | — | No |
| Knowledge graph page (`/workspaces/[id]/graph`): React Flow + dagre left-to-right canvas, connected entities by default with a toggle and count for isolated ones, searchable/sortable relationship list, evidence panel with verbatim quotes and the source viewer, status recovered from the backend | `feat/semantic-knowledge-graph` | Yes; manual UI test pending | `npm run lint`, `npm run build`, `npm test` (27 pass, 5 new layout tests); `gen:api` produced no change | No |
| Knowledge graph rules.v3 rebuild on dev (same 3-paper workspace) | `feat/semantic-knowledge-graph` | Job completed in 641 s: 27 requests (19 calls + 8 failed attempts, all recovered), 45.4K in / 10.1K out tokens (identical to the rules.v2 run, consistent with identical model replies at temperature 0), no quota errors. 7 edges (was 11), 116 nodes; 7/7 quotes verbatim. The 4 relationships hand-marked wrong are gone (review paper now keeps 0: `attributed_elsewhere` 4; `identity_not_relation` 1; `entity_inside_phrase` 2); the other 7 are unchanged. Still questionable: framework `uses` switch points (part of, not use), framework `addresses` catch-slip bond (loose), blink/motion detection `uses` eye's ROI (applied within a region) | `docs/experiments/2026-10-20T085255Z_kg_run_job_eede233.json` | No |
| Knowledge graph rules.v3: review papers, identity, cut concepts (D-086, SRS v1.27) | `feat/semantic-knowledge-graph` | Yes; existing extractions need an Update (version change) | Unit tests: review voice (6), review detection, "the authors" after a cited study, identity, cut concept, two validation tests. Offline replay of the dev job's 11 kept relationships: the 4 hand-marked wrong are rejected (2 `review_literature`, 1 `identity_not_relation`, 1 `entity_inside_phrase`), the 7 others kept. PROVISIONAL: 31/31 examples match their unverified labels. `is_review` correct on 11/11 local PDFs. No API change | — | No |
| Knowledge graph first end-to-end job on dev (`scripts/kg_run_job.py`, 3 papers: biomaterials review, mathematical modelling, computer science; one workspace of one account) | `feat/semantic-knowledge-graph` | Job completed in 827 s: 32 provider requests (19 calls + 13 failed attempts, all recovered by graph-tier backoff; 1 invalid reply retried), 45.4K in / 10.1K out tokens, no quota errors, cap 50. All 3 papers completed (31/49, 16/18, 23/24 chunks read). 11 relationships kept, 117 nodes (98 without an edge), 11 edges; 11/11 quotes verbatim in their source passage. Rejections: entity_not_in_quote 32, entity_not_in_passage 22, quote_not_verbatim 21, type_not_allowed 10, not_own_work 7, not_entailed 4, attributed_elsewhere 1, label_invalid 1. Hand review of all 11: about 3 clearly right, 4 acceptable or loose, 4 wrong (2 cited studies in the review introduced by "In this study, the authors ..." or "Furthermore, in a murine model ...", 1 wrong relation, 1 loose concept) | `docs/experiments/2026-10-20T080622Z_kg_run_job_be46740.json` | No |
| Knowledge graph model check (SRS §9.1 criteria; `scripts/kg_model_check.py`; 4 dev papers: biomaterials, finance, mathematical modelling, computer science) | `feat/semantic-knowledge-graph` | `gemma-4-26b-a4b-it`: prompt v1 + 1,500 output tokens 13/19 valid first attempt (6 `json_invalid`), 8 of 89 relationships kept; prompt v2 + 3,000 tokens 18/18 valid (1 batch lost to 503 outages), 12 of 94 kept; about 3,000 tokens and 15 s per call. `gemma-4-31b-it` untested (503 high demand). Groq `openai/gpt-oss-120b`, prompt v2, same batches: 11/17 valid first attempt (6 HTTP 400 schema rejections), 8 of 26 relationships kept, about 5,000 tokens per call (output 0.7–3K, reasoning included; one reply at the 3,000 cap), stopped by the 100K token budget after 17 requests. Hand review: Groq about 3 of 8 kept correct (4 attribute cited work to the paper), Gemma v2 about 7 of 12. Model not chosen yet. Relationship judge prototype (D-084, isolated, not wired in): attribution context, `eval/data/kg_judge_v1.jsonl` (31 candidates; labels drafted, not verified); offline: gold replay scores 1.0, keep-all baseline precision 0.42 (0.54 on the 24 real candidates). PROVISIONAL run on the unverified draft labels (`--provisional`, gemma-4-26b-a4b-it, 4 requests, 5.5K in / 0.8K out tokens): precision 0.33, recall 0.23, 0 of 8 other-work caught, 19 of 31 candidates got no verdict (dropped fail-safe); below the keep-all baseline, so the judge is not integrated. Engineering guidance only, not a verified result. 19 no-verdict rows: one call matched all its labels and three matched none, with output tokens consistent with full replies, so the likely cause is label echo format (`[R1]` vs `R1`; raw replies were not saved). Judge dropped (D-085) | `docs/experiments/2026-10-18T133006Z_*`, `2026-10-18T140219Z_*` | No |

Discover UI not yet tested by hand; manual checklist is in the branch's completion report.

## Phase 0 exit criteria

- [x] Deployed frontend calls deployed `/health` successfully through the generated API client (Vercel → HF Space, verified in production)
- [x] Deployed `/health/ready` reports the database reachable (Supabase prod)
- [x] CI green with all checks (SRS §15.1) on `main` (backend and frontend jobs)
- [x] `uv run pytest` passes, including `/health` and config-loading tests (141 unit tests after task #7)

## Phase 1 exit criteria (SRS §22)

Evidence from 2026-10-03/04 unless noted. Raw results: `docs/experiments/*.json` (commit 7bd8998).

- [x] **Upload 3 real papers → `ready`:** `test_retrieval_supabase.py` uploads 3 papers per set (6 PDFs) and asserts `ready`; `test_ingestion_supabase.py::test_real_paper_reaches_ready`; `measure_ingestion` over HTTP (local server, dev DB).
- [x] **Retrieval returns correct chunks with page/section:** `test_retrieval_supabase.py` (dev; `*_retrieval_eval_*.json`): embedding_comparison R@8 page 0.94 (snippet 0.88), embedding_check_v1 R@8 page 1.00 (snippet 1.00); every result has `page_start ≥ 1` and its section. Same numbers as task #7.
- [x] **Cross-user and cross-workspace leakage tests pass:** 53 integration tests on dev, including `test_auth_supabase.py::test_real_tokens_and_cross_user_isolation`; `test_retrieval_db.py::test_other_workspace_is_never_returned_even_when_closer`, `::test_other_users_workspace_returns_nothing`, `::test_load_only_returns_the_workspaces_chunks`; `test_workspaces_db.py::test_get_and_list_filter_by_owner`, `::test_delete_by_another_user_changes_nothing`; `test_documents_db.py::test_reads_filter_by_owner`, `::test_status_changes_are_owner_only`; `test_topic_profiles_db.py::test_other_users_cannot_touch_a_profile_through_link_or_remove`. Unit: `test_*_api.py::test_other_users_*_is_404`, `test_documents_api.py::test_upload_into_another_users_workspace_is_404`. The DB tests also run in CI's `migrations` job.
- [x] **Unrelated upload triggers a warning:** `test_documents_api.py::test_check_warns_about_an_unrelated_document_and_stores_nothing`, `::test_linking_an_unrelated_ready_document_warns`; `test_topic_profiles_db.py::test_link_warns_then_overrides`; real papers (`*_calibrate_compatibility_*.json`): off-topic 0.788 / 0.685 < threshold 0.83 < lowest on-topic 0.870.
- [x] **NFR-02 measured and recorded:** Space (HF CPU basic, prod): 28.8 s, upload 4.6 s, parsing from 5.4 s, embedding from 20.0 s (2026-10-03T211926Z_measure_ingestion_f5ee8ee.json).
- [x] **CPU latency of embedding, reranker, NLI on the deployed tier, with the NFR-01 risk note:** Space table under Measurements (task 1a startup benchmark, CPU basic, 2 torch threads); risk in Known issues ("NLI latency threatens NFR-01"). That run predates the experiment log, so it has no JSON.

## Phase 2 exit criteria (SRS §22)

Evidence from the Space (HF CPU basic, prod, demo keys) on 2026-10-07: smoke test (SETUP §9 step 8) and `measure_qa` on 12 test-split items (`2026-10-07T174426Z_measure_qa_09f134b.json`).

- [x] **Answers stream with validated citations:** 10/10 answerable items streamed `status` → `claims` → `citations` → `done` with at least one citation each (1–7 claims, 1–7 citations); every run went through A3 verification. Smoke test on 2303.11051 also answered with citations; runs visible in LangSmith (`research-assistant-prod`).
- [x] **Unanswerable questions abstain:** 2/2 on the Space (test-046, test-051) and the smoke-test question, each after `approval_required` → resume `corpus_only`. The full graph has not been run over all 10 unanswerable test items yet (C2 abstained on 10/10).
- [x] **Approval prompt pauses and resumes correctly:** 3 runs paused (test-038, 046, 051); each resumed with `corpus_only` and ended with the correct outcome; resume took 0.4 s to an abstention and 15.1 s to an answer.
- [x] **Baseline C1/C2 results in `backend/eval/reports/`:** `2026-10-06T150917Z_eval_C1_test_0062878.*`, `2026-10-06T154320Z_eval_C2_test_0062878.*` (task #10 table).
- [x] **Average LLM calls per corpus-only question (NFR-13):** mean 3.67, max 8 (limit 10 on average), from `agent_runs`.
- [x] **NFR-01 (measured here, required from Phase 2 on):** first event max 0.39 s (≤ 2 s); answered p50 6.77 s, p90 20.36 s (≤ 25 / 45 s).

## Phase 3 exit criteria (SRS §22)

Evidence from 2026-10-08/09 on the deployed app (Vercel from `main`, HF Space, prod Supabase).

- [x] **Playwright E2E passes on the deployed environment (upload → ask → open highlighted citation):** workflow **E2E** run 37840452429 on `dev` (commit `7618720`), `E2E_BASE_URL` = the Vercel production URL, prod E2E user; passed in about 2 min (the Space was already awake). The test deletes its workspace.
- [x] **Manual UI check:** the team ran the checklist on the deployed site (landing, auth, library, chat, source viewer) on 2026-10-09; functional first, visual polish deferred to the UI polish pass (D-075).
- Interim release before the E2E test (D-076): tasks 1–6 were deployed first (PR #53, prod migrated to 0006).
- Still open from the release checklist (SETUP §10 step 5): NFR-02 ingestion time re-measured on the Space; the 28.8 s figure predates Phase 2's DOI lookup and metadata step.

## Team actions (humans)

- [x] Create Supabase **dev** project (Data API off, automatic RLS on; D-040)
- [x] Create Supabase **prod** project with the same settings as dev (Data API off, automatic RLS on)
- [x] Create Vercel project and Hugging Face Space (Hugging Face PRO, Protected visibility; D-043)
- [x] Add secrets to GitHub, Vercel, and Hugging Face (following `docs/SETUP.md`)
- [ ] Start collecting the benchmark corpus (15–20 open-access tissue-engineering papers)
- [x] Phase 2 keys: free Groq and Gemini API keys in `backend/.env`; Gemini free-tier limits checked in AI Studio
- [x] LangSmith key; all Phase 2 keys as Space secrets before the Phase 2 deploy
- [x] Demo-only Groq and Gemini API keys for the Space, never used for development, tests, or evaluations (D-070)
- [ ] Phase 4 release: prod `alembic upgrade head` (migration 0007).
- [ ] Phase 3 release (docs/SETUP.md §10, built up as tasks land): prod migration 0006, Vercel Supabase env vars, prod auth URLs, E2E secrets
- [x] Phase 2 release (docs/SETUP.md §9): prod at 0005 with checkpoint tables, Space secrets, release PR, deploy, smoke test, `measure_qa`, results PR, tag `phase-2-done`
- [x] Phase 1 release (docs/SETUP.md §8): prod bucket, Space secrets, prod JWT key type, prod migration `0001 → 0003`, release PR `dev` → `main`, deploy, health checks, NFR-02 on the Space, tag `phase-1-done`

## Completed

- Pre-Phase 0 review of CLAUDE.md and SRS; 24 decisions recorded (D-001 to D-024); SRS updated to v1.2.
- Task #2 `p0/backend-skeleton`: uv project (Python 3.11) in `backend/`, SRS §21.1 `app/` layout, pydantic-settings config (CORS origins, provider selection defaulting to `fake`, optional `DATABASE_URL`), `.env.example`, text/JSON logging, domain error model with a single `{"error": {...}}` envelope, `GET /api/v1/health` and `GET /api/v1/health/ready` (503 unless the database answers `SELECT 1`). 30 unit tests; ruff, ruff format, and mypy (strict) clean. One integration test (`uv run pytest -m integration`) checks readiness against the real database. Decisions D-025 to D-029.
  - **Manual checks for the team:**
    - Run `uv sync`, then `uv run pytest` (from `backend/`).
    - Run `uv run uvicorn app.main:app --reload`, then open `/api/v1/health` → 200 and `/docs`.
    - With no `DATABASE_URL`, `/api/v1/health/ready` → 503 `not_configured`.
    - With the Supabase dev `DATABASE_URL` in `backend/.env` (session pooler, `postgresql+psycopg://`), `/api/v1/health/ready` → 200, and `uv run pytest -m integration` passes. Verified against the dev project on 2026-09-30 (during task #4).
  - Development moved to WSL2 (D-030); both Windows known issues are resolved.
- Task #3 `p0/providers`: provider interfaces in `app/providers/` (LLM with validated structured output, embedding, reranker, NLI, parser, scholarly search, web search); deterministic fakes in `app/providers/fakes/`; `build_providers()` selects implementations from config at startup and fails fast on unimplemented ones. Config: `LLM_PROVIDER` replaced by fast/strong tier settings; `WEB_SEARCH_PROVIDER` and `EMBEDDING_DIMENSION` added. 89 new unit tests (119 total); ruff, ruff format, and mypy clean. Decisions D-031 to D-037; SRS v1.3.
  - **Manual checks for the team:**
    - `uv run pytest` (from `backend/`) → all pass, no network needed.
    - `uv run uvicorn app.main:app --reload` → `/api/v1/health` returns 200 with all-fake providers.
    - `LLM_FAST_PROVIDER=groq uv run uvicorn app.main:app` → startup fails with "LLM (fast) provider 'groq' is not implemented yet (planned for Phase 2)".
    - Anyone with a local `backend/.env`: rename `LLM_PROVIDER` to `LLM_FAST_PROVIDER`/`LLM_STRONG_PROVIDER` (the old name is now ignored).
    - Read the fake behaviours in `app/providers/fakes/` docstrings; later phases write their tests against them.
- PR #5 `p0/claude-permissions` (outside the task list): project `.claude/settings.json` for Claude Code. It allows routine commands without prompting (`uv run pytest/ruff/mypy/uvicorn`, `uv sync`, `git status/diff/log/add/commit/branch/checkout`, `gh pr view`) and denies destructive ones (`git push --force`/`-f`, `git reset --hard`, `git checkout --`, `git branch -D`, `rm -rf`/`rm -fr`).
- Task #6 `p0/ci` (backend part, PR #6, merged): `.github/workflows/ci.yml` with a `backend` job. It installs uv 0.12.21 and uv-managed Python from `backend/.python-version` (3.11.16 on CI), runs `uv sync --locked` (fails if `uv.lock` is stale), `ruff check`, `ruff format --check`, `mypy app`, and the unit tests (integration tests deselected by pyproject `addopts`). Triggers: push to any branch, pull requests into `dev`/`main`, and manual dispatch. Actions are pinned to commit SHAs, the runner is `ubuntu-24.04`, the setup-uv cache (dependencies and managed Python) is keyed on `backend/uv.lock`, the token is read-only, and no secrets are used. CI results: push, pull_request, and manual runs all green, 119 passed / 1 deselected, about 25–30 s per job; a cache hit was confirmed on a repeat run (Python restored in under 0.1 s). The frontend lint/build job is added by task #5.
  - Follow-ups approved during review: Dependabot for GitHub Actions (D-038); uv version pinned via `required-version` in `backend/pyproject.toml`, which CI reads (D-039); `.claude/settings.local.json` added to `.gitignore`.
  - **Manual checks for the team:**
    - On PR #6, the `CI / backend` check is green for both the push and pull_request runs.
    - Optional: add branch protection (or a ruleset) on `dev` and `main` requiring `CI / backend` to pass before merging.
    - Everyone: run `uv self update 0.12.21` if `uv --version` differs. Other versions now fail with "Required uv version `==0.12.21` does not match".
    - After merge: under GitHub → Insights → Dependency graph → Dependabot, confirm `github-actions` updates are listed. Dependabot PRs target `dev`.
    - Anyone with a local `.claude/settings.local.json`: it is now ignored by git.

- Task #4 `p0/alembic` (PR #7, merged): Alembic 1.20 in `backend/` (`alembic.ini`, `alembic/env.py`, empty baseline revision `0001`).
  - `env.py` reads `DATABASE_URL` through app settings and reuses the app's async engine factory. There is no URL in `alembic.ini`.
  - Autogenerate reflects only `public` and skips the LangGraph checkpoint tables (`app/models/migration_scope.py`).
  - `Base` and its constraint naming convention are in `app/models/base.py`.
  - Tooling: new revision files are run through ruff by a post-write hook, and ruff's isort treats `alembic` as third-party.
  - Tests: 18 new unit tests (137 total) cover naming, the scope filter, a single head, and the baseline. One new integration test runs `alembic check` against dev.
  - Decisions: D-040 (backend is the only DB client, Data API off, automatic RLS) and D-041 (Alembic setup); SRS v1.4.
  - **Verified against Supabase dev (PostgreSQL 17.11):**
    - `alembic upgrade head` → `downgrade base` → `upgrade head` all succeed.
    - `alembic check` reports "No new upgrade operations detected" on the fresh database.
    - Exclusion test in a rolled-back transaction: with dummy `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`, and `stray_table` tables in `public`, autogenerate reports only `remove_table stray_table`.
    - Auto-RLS: every table created in `public` gets `relrowsecurity = true`, including `alembic_version`, and `postgres` (BYPASSRLS) still reads and writes it.
    - Integration tests: `uv run pytest -m integration` → 2 passed (readiness and migrations).
    - Live readiness: `/api/v1/health/ready` → 200 `{"status":"ready","checks":{"database":"ok"}}`.
  - **Manual checks for the team:**
    - `uv sync`, then `uv run pytest` (from `backend/`) → all pass.
    - With the dev `DATABASE_URL` in `backend/.env`: `uv run alembic current` → `0001 (head)`, and `uv run alembic check` → "No new upgrade operations detected". `uv run pytest -m integration` → 2 passed.
    - Without `DATABASE_URL`: `uv run alembic current` fails with a message saying `DATABASE_URL` is not set.
    - In the Supabase dashboard (dev): Table Editor shows only `alembic_version` in `public`, with RLS enabled. Settings → API shows the Data API disabled.
    - Read `alembic/env.py` and `app/models/migration_scope.py`. From Phase 1 on, every model module must be imported in `app/models/__init__.py`, or autogenerate won't see it.

- Task #5 `p0/frontend-skeleton` (PR #9, merged): Next.js 16 (App Router, TS strict), Tailwind 4, shadcn/ui, ESLint + Prettier; Node 24 LTS pinned in `frontend/.node-version`.
  - `npm run gen:api` dumps the backend OpenAPI with `uv run` (no server needed) and writes `src/lib/api/schema.d.ts` (committed). Calls go through `openapi-fetch` (`src/lib/api/client.ts`), base URL from `NEXT_PUBLIC_API_BASE_URL`.
  - `/` shows the result of `GET /api/v1/health`. CI has a `frontend` job: `npm ci`, `npm run lint`, `npm run build`.
  - Verify manually: backend `uv run uvicorn app.main:app` + `npm run dev` in `frontend/`; http://localhost:3000 shows "ok" and the version. With the backend stopped it shows "unreachable".
- Task #7 `p0/deploy` (PR #10, merged): `backend/Dockerfile` (Python 3.11.16 slim, uv 0.12.21, `uv sync --locked --no-dev`, user 1000, port 7860, `ENVIRONMENT=prod`, JSON logs), `backend/.dockerignore`, `backend/README.md` (Space metadata). `.github/workflows/deploy-backend.yml` uploads `backend/` to the Space on push to `main`. `frontend/vercel.json` builds only `main`. `docs/SETUP.md` covers every manual step. 4 new unit tests (141 total) keep the Dockerfile in step with `pyproject.toml`, `.python-version`, and the Space README. Decision D-042.
  - Docker is not installed locally, so the image itself is first built on Hugging Face. The same install (`uv sync --locked --no-dev --no-install-project`) and start command were run locally: `/api/v1/health` → 200, CORS header returned for the configured origin, JSON logs.
  - Space region check (2026-10-01): `*.hf.space` resolves to AWS addresses in Ashburn, VA (us-east-1), so Supabase prod should be East US (North Virginia).
  - **Manual steps for the team:** follow `docs/SETUP.md` steps 1–7. After merging to `main`, run **Actions → Deploy backend** once, then tick the first two Phase 0 exit criteria.
- Task #1 `p1/local-models`: `app/providers/local/` (sentence-transformers embedder, cross-encoder reranker with sigmoid scores, NLI with labels read from the model config). Weights load lazily or at startup (`PRELOAD_MODELS`); inference runs in worker threads behind `LOCAL_INFERENCE_CONCURRENCY` (default 1). The embedding dimension is checked from the cached model config at startup without loading weights, or when the model loads. torch 2.14.1+cpu from the PyTorch CPU index (no `nvidia-*` packages in `uv.lock`). The Dockerfile bakes the three models (~2.2 GB) into `/opt/hf` in a layer that depends only on `app/core/config.py`, then sets `HF_HUB_OFFLINE=1`, `PRELOAD_MODELS=true`, and the local providers. Scripts: `scripts/download_models.py`, `scripts/bench_cpu.py`, `scripts/compare_embeddings.py` (16-question set over 3 arXiv scaffold papers in `scripts/data/embedding_comparison/`; PDFs not committed). 174 unit tests, 3 new integration tests.
  - **Manual checks for the team:**
    - Update your `backend/.env`: `EMBEDDING_DIMENSION=768` (startup now fails on a mismatch with a local embedder).
    - `uv sync`, `uv run pytest`; `uv run python -m scripts.download_models`, then `uv run pytest -m integration -k local_models` → 3 passed.
    - `uv run python -m scripts.bench_cpu` prints the latency table.
    - After the Space rebuilds (task #9): the image builds, startup logs show the models loading, and `/api/v1/health` is 200.
- Task #2 `p1/schema`: migration `0002` adds the following.
  - Tables: workspaces, documents, workspace_documents, chunks (`vector(384)`, HNSW `vector_cosine_ops`, generated `tsv` + GIN, unique `(document_id, chunk_index)`), and topic_profiles. All timestamps are `timestamptz`, and links and children cascade on delete.
  - pgvector in the `extensions` schema.
  - Explicit RLS on every table, including `alembic_version`.
  - `REVOKE` for `anon`/`authenticated` on everything in `public`, including `ALTER DEFAULT PRIVILEGES FOR ROLE postgres`. Downgrade never grants these back.
  - Models are in `app/models/`. CI job `migrations` runs on a pgvector 0.8.2 container (D-052). 193 unit tests; 10 integration tests.
  - **Verified on Supabase dev:** before the migration the schema tests failed (anon had privileges). `upgrade head` → `check` → `downgrade base` → `upgrade head` all succeeded, and the downgrade left anon with no privileges. Dev is at `0002`.
  - **Manual checks for the team:**
    - `uv sync`; with the dev `DATABASE_URL`: `uv run alembic current` → `0002 (head)`, `uv run pytest -m integration` → all pass.
    - Supabase dashboard (dev): the five tables exist with RLS enabled.
    - Prod: run `uv run alembic upgrade head` against prod before the Phase 1 `dev` → `main` merge (D-042).
    - On the PR: the `CI / migrations` check is green. Add it to branch protection if you use it.
- **Phase 0 complete:** all exit criteria verified in production — the Vercel frontend shows backend health ok, the Space's `/api/v1/health/ready` reports the database ok, and CI is green on `main`. The Space runs on Hugging Face PRO with Protected visibility (D-043).

- Task #1 `p2/llm-providers` (Phase 2): `LangChainLLM` (`app/providers/live/llm.py`) for Groq (`openai/gpt-oss-20b`, fast) and Gemini (`gemini-3.5-flash-lite`, strong); structured output via `json_schema`, validated by `parse_structured`; LangChain retries off, own 2 retries with backoff on 429/5xx/timeouts/connection errors, then `LLMProviderError` (502). `RateLimiter` per (provider, model): one-minute window over requests + tokens, rolling daily request cap; at the cap or on a provider per-day 429 → `LLMQuotaExceededError` (`llm_quota_exhausted`) without retries. `track_usage()` counts calls, tokens, and failed attempts per run. `demo` provider (`[DEMO OUTPUT]`, refused in prod). LangSmith settings copied into `LANGSMITH_*` at startup. Keys are `SecretStr`; logs carry only the exception type. websockets went 17.1 → 16.1.1 (google-genai pin). D-062. 591 unit tests; 2 integration tests pass with real keys (one structured call each).
  - **Free-tier quotas** (team's AI Studio, 2026-10-04): every non-lite Gemini Flash (3.8/3.7/3.6/3.5/3/2.5) 5 RPM / 250K TPM / **20 RPD**; Gemini 3.5 and 3.1 Flash Lite 15 / 250K / 500; Gemma 4 26B/31B 30 / 16K / 14.4K. Groq docs: gpt-oss-20b and -120b 30 RPM / 8K TPM / 1K RPD each.
  - **Manual checks for the team:** `uv run pytest -m integration tests/integration/test_llm_providers.py` (from `backend/`) → 2 passed; `LLM_FAST_PROVIDER=demo ENVIRONMENT=prod uv run uvicorn app.main:app` fails at startup; with `LANGSMITH_TRACING=true` and a key, the integration calls appear in LangSmith.
- Task #2 `p2/chat-schema` (Phase 2): migration 0004 adds conversations, messages, claims, evidence, citations, approvals, agent_runs, eval_runs and eval_results, with explicit RLS. `ConversationRepository`/`ConversationService` and four endpoints: `GET/POST /workspaces/{id}/conversations`, `GET /conversations/{id}/messages` (limit/offset), `GET /messages/{id}/claims`. A corpus_web conversation is logged as an approval. `save_answer` stores the message, claims, evidence and citations and finishes the run in one transaction; on any failure it rolls back. Citations keep a snapshot of their source. D-064, SRS v1.13. 623 unit tests; 10 new DB integration tests (also in CI's pgvector job). On dev: `upgrade` → `downgrade 0003` → `upgrade` succeed and `alembic check` is clean.
  - **Manual checks for the team:** `uv run alembic upgrade head` on dev (prod waits for the Phase 2 release). `uv run pytest -m integration tests/integration/test_conversations_db.py` → 10 passed. In `/docs`, create a conversation in a workspace and list it; another user's token gets 404.
- Task #3 `p2/query-analyzer` (Phase 2): A1 `QueryAnalyzer` (`app/agents/query_analyzer.py`, prompt `app/prompts/agents/query_analyzer.v1.md`, loaded by `app.prompts.load_prompt`) returns a validated `QueryPlan`: one of 8 intents, at most 4 sub-questions with search keywords, `depends_on` only on earlier ids, and named papers as `paper_refs`. A `simple_qa` plan is reduced to one sub-question, the question itself; `out_of_scope` has none. S6: `check_question` (cleaned, empty/oversized rejected; retrieval reuses it), `data_block` (delimited prompt data, closing tag defused), `out_of_scope_reply`. 655 unit tests; live Groq test: 9 of 9 questions classified correctly (~1 s and ~950 input + 220–420 output tokens per call).
  - **Manual checks for the team:** `uv run pytest -m integration tests/integration/test_query_analyzer_live.py` → 9 passed (about 3 min: the 8K tokens/min Groq limit throttles back-to-back calls). Read the prompt file and check the intent examples fit the domain.
- Task #4 `p2/sufficiency-gate` (Phase 2): S3 `SufficiencyGate` (`app/services/sufficiency.py`, prompt `app/prompts/services/sufficiency_check.v1.md`): score ≥ 0.97 → covered; other sub-questions with evidence → one batched strong-tier check (8 chunks each) → covered/partial/insufficient + reason; no evidence → insufficient. Benchmark v1 calibration split (53 items: 33 Phase 1 answerable + 20 new unanswerable, all `drafted_by=claude`, none verified) in `backend/eval/data/`. D-065, SRS v1.14. 670 unit tests.
  - Calibration on dev (`2026-10-04T180502Z_calibrate_sufficiency_203a1e8.json`, gemini-3.5-flash-lite): answerable judged insufficient **1 of 33** (cal-032, gold passage not retrieved); unanswerable judged covered **0 of 20**, partial 2 (cal-042, cal-052); 12 answerable fast-passed, 41 LLM-checked. Score-only baseline: best threshold 0.888 → 13 of 33 false insufficient (`2026-10-04T172700Z_…`). With 4 check chunks: 5 of 33 (gold at rank 6 in three; `2026-10-04T175648Z_…`).
  - **Manual checks for the team:** review cal-034…cal-053 (unanswerable) and set `verified_by`; **cal-042 is mislabelled**: the chitosan paper says precursor solutions can be autoclave-sterilised, so it is partly answerable (fix or replace it). Then re-run `RECORD_EXPERIMENT=1 uv run pytest -m integration tests/integration/test_sufficiency_supabase.py -s` (~7 min, ~41 Gemini calls) and recalibrate the fast pass.
- Task #5 `p2/synthesis-citations` (Phase 2): S5 `EvidenceSet` + `CitationService` (`app/services/citations.py`) and A2 `SynthesisAgent` (`app/agents/synthesis.py`, prompt `synthesis.v1`, strong tier). A2 returns `DraftAnswer` sentences (`evidence` with labels / `gap` / `general`), takes an optional `Revision` for the A3 loop; S5 maps labels to `CitationDraft`s. `CITATION_QUOTE_MAX_CHARS` (300). D-066, SRS v1.15. 689 unit tests.
  - Live check on dev (`tests/integration/test_synthesis_live.py`, gemini-3.5-flash-lite): 6 answerable calibration questions (3 per corpus), all sufficient, every sentence cites valid labels, cited pages within 1 of gold. cal-019 mixed results from several studies into one answer; A3 (task #6) checks this kind of drift.
  - **Manual checks for the team:** `uv run pytest -m integration tests/integration/test_synthesis_live.py -s` (~4 min, 12 Gemini calls) and read the printed answers.

- Task #6 `p2/verification` (Phase 2): A3 `VerificationAgent` (`app/agents/verification.py`, judge prompt `verification_judge.v1`). Claims are A2 sentences that cite passages (no extraction call). NLI scores each claim over 120-word sentence windows of its cited chunks: entailment ≥ 0.9 with no contradiction ≥ 0.5 → supported. Every other claim, and `gap` sentences with citations, goes to one batched judge call. NLI alone never rejects. `general` sentences → `uncertain`, never checked. `revision()` builds A2's `Revision` from unsupported/partial claims; `finalize()` drops unsupported claims and flags abstention. `VERIFICATION_*` settings; default NLI `cross-encoder/nli-deberta-v3-xsmall`. `scripts/compare_nli.py` and 102 claim–evidence pairs (`eval/data/verifier_pairs_v1.jsonl`, calibration split, `drafted_by=claude`, unverified). Live tests share `tests/integration/live_corpora.py`. D-067, SRS v1.16. 726 unit tests.
  - NLI comparison (`2026-10-04T201501Z_compare_nli_3311491.json`; all four models in `…195915Z…`): windows beat whole chunks for every model (AUC xsmall 0.91 vs 0.74, base 0.96 vs 0.82, small 0.86 vs 0.65, MiniLM2 0.82 vs 0.53). xsmall auto-accepts 12 of 34 supported claims with 0 false accepts at 607 ms/claim. Every model scores some supported claims near 0, so NLI-only rejection was dropped.
  - Live check on dev (`tests/integration/test_verification_live.py`): 6 calibration questions, 13 claims (5 accepted by NLI, 8 by the judge), no revisions needed, no abstentions; 1–2 LLM calls and 2.0–11.6 s per question for A2 + A3 (laptop).
  - **Manual checks for the team:** review the 102 pairs in `eval/data/verifier_pairs_v1.jsonl` (labels, set `verified_by`); then `uv run python -m scripts.compare_nli` (~15 min) and adjust `VERIFICATION_SUPPORTED_SCORE` if needed. `uv run pytest -m integration tests/integration/test_verification_live.py -s` (~6 min, ~12 Gemini calls) and read the verdicts. Update `NLI_MODEL` in your `backend/.env` if it still says `nli-deberta-v3-base`.

- Task #7 `p2/qa-graph` (Phase 2): the QA graph (`app/graphs/qa.py`) has these steps:
  - A1 runs first. An out-of-scope question gets the S6 refusal.
  - S2 runs per sub-question in dependency waves (`Send`), limited to named papers when they resolve to workspace documents. A1's keywords are added to the full-text query only.
  - S3 runs next. S4 then decides: sufficient → A2; a corpus_web conversation → the external-research stub; otherwise `interrupt()` with the reason, coverage, closest passages, and three options.
  - A2 → A3, with up to `VERIFICATION_MAX_REVISIONS` (2) revisions. `finalize` applies S5 citations and the S6 general-knowledge label, or abstains (`abstention_reply`).
  - Staying corpus-only with no coverage abstains without an LLM call. A general-knowledge claim is always `uncertain`.

  `QARunner` (`app/graphs/qa_runner.py`):
  - Stores the question and the run.
  - Runs the graph in its own task, so the answer is saved even if the client leaves.
  - Emits typed events: `status`, `approval_required`, `claims`, `citations`, `error`, `done`.
  - Pauses with a pending approval and resumes it atomically: non-owned → 404, not waiting → 409, option not offered → 422.
  - Stores latency, LLM calls, and tokens per segment.
  - Marks failures `failed` in a separate transaction.
  - Deletes a run's checkpoints once it ends.
  - A sweep at startup and every 5 min fails `running` runs older than `QA_RUN_STALE_MINUTES`. Interrupted runs wait.

  Checkpoints use `AsyncPostgresSaver` in the `langgraph` schema:
  - Migration 0005 creates the schema with no client-role access; `scripts/setup_checkpointer.py` creates the tables (RLS on).
  - Connections come from a pool with `search_path` set per connection.
  - The graph state is plain JSON, read back with the strict serializer.

  Other changes and tests:
  - `ChunkRepository.match_documents` matches titles as whole words, or the DOI.
  - 772 unit tests.
  - DB tests (CI pgvector job): run lifecycle, named papers, and restart-and-resume through Postgres.
  - Dev is at `0005` with the checkpoint tables set up.
  - **Live on dev** (`test_qa_graph_live.py`, Groq + Gemini, laptop):

    | Item | Outcome | Time | LLM calls | Tokens |
    |---|---|---:|---:|---:|
    | cal-001 | answered | 25.0 s | 4 | 12 026 |
    | cal-002 | answered | 11.1 s | 4 | 7 561 |
    | cal-003 | answered | 8.3 s | 3 | 7 361 |
    | cal-034 (unanswerable) | approval → abstained | 5.8 s | 2 | 4 097 |

    The mean is 3.2 LLM calls per question. Task #11 measures NFR-13 on the benchmark.
  - **Manual checks for the team:**
    - `uv sync`; `uv run alembic upgrade head` (dev is already at 0005), then `uv run python -m scripts.setup_checkpointer`.
    - `uv run pytest -m integration tests/integration/test_qa_checkpointer_db.py tests/integration/test_conversations_db.py`.
    - `uv run pytest -m integration -s tests/integration/test_qa_graph_live.py` (~3 min, ~14 LLM calls); read the abstention text.
    - Read the S4 reason and abstention wording in `app/services/knowledge_boundary.py` and `app/services/guardrails.py`.

- Task #8 `p2/chat-sse` (Phase 2): `POST /conversations/{id}/messages` and `POST /runs/{run_id}/resume` stream the `QARunner` events over SSE.
  - Uses FastAPI's built-in `EventSourceResponse`, so no new dependency. It sends a `: ping` keepalive every 15 s.
  - Each event's `data` is JSON with a `type` discriminator, and the OpenAPI item schema is typed for `gen:api`.
  - The run starts in a dependency. A rejected request (401/404/409/422/503) gets a JSON error before the stream opens, and OpenAPI documents those errors as `application/json`.
  - A client that disconnects stops only its stream; the run finishes and saves its answer.
  - D-036 confirmed: there is no `token` event (SRS v1.17).
  - The QA test harness moved to `tests/unit/graphs/qa_harness.py`. 778 unit tests.
  - **Manual checks for the team:**
    - Run uvicorn against dev, create a conversation in `/docs`, then `curl -N -X POST localhost:8000/api/v1/conversations/{id}/messages -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"content": "..."}'`. You should see `status` events, then `claims`, `citations`, and `done`.
    - Ask an unanswerable question, then `POST /runs/{run_id}/resume` with `{"decision": "corpus_only"}`; the stream should end with an abstention.

- Task #9 `p2/llm-metadata-keywords` (Phase 2, D-068, SRS v1.18):
  - FR-04: without a confirmed DOI, the fast tier reads page 1 (`FirstPageExtractor`, `first_page_metadata.v1`) for title, authors, year, and venue. It never supplies a DOI, and a failure keeps the PDF metadata.
  - S7: `TopicSummaryService` (`topic_summary.v1`, strong tier) writes `topic_profiles.keywords`/`summary` in the background after ingestion, link, and removal. Refreshes of one workspace run one at a time. `GET /workspaces` responses include `keywords` and `summary`. No migration.
  - Measured on the 6 Phase 1 papers (Groq gpt-oss-20b, page 1 only): 6/6 titles, years, and venues correct, authors plausible. Two titles keep PDF glyph quirks ("ChitosanBased", curly quotes).
  - Live test `test_metadata_keywords_live.py` passed (arXiv 2303.11051: LLM title/authors/year/venue, 5 keywords, 2-sentence summary). 804 unit tests.
  - **Manual checks for the team:**
    - Upload a paper without a DOI through `/docs`; once `ready`, check its title/authors, then `GET /workspaces/{id}` for `keywords` and `summary`.
    - Read the prompts `app/prompts/services/first_page_metadata.v1.md` and `topic_summary.v1.md`.
    - `npm run gen:api` in `frontend/` picks up the new workspace fields.
- Task #10 `p2/eval-harness` (Phase 2, D-069, SRS v1.19):
  - Benchmark v1 test split: 54 items over the six papers (36 single, 5 multi, 3 comparison, 10 unanswerable), `drafted_by=claude`, unverified; snippets checked against the parsed pages. `eval/dataset.py` replaces the loaders in `scripts/calibrate_sufficiency.py`.
  - `uv run --group eval python -m eval.run --condition C1|C2 [--limit N] [--corpus X] [--no-ragas]`: C1 LLM-only; C2 dense top 8 (`RetrievalService.retrieve_dense`) + one answer-from-context prompt. Writes `eval_runs`/`eval_results` and `eval/reports/*.json` + `.md`. Ragas faithfulness/relevancy go through `LLMProvider` with the `EVAL_JUDGE_*` model (Groq gpt-oss-120b). CI installs the `eval` group. 843 unit tests; `test_eval_runs_db.py` in CI's pgvector job.
  - **Baselines on the test split** (gemini-3.5-flash-lite; all items unverified, so provisional):

    | Metric | C1 LLM-only | C2 conventional RAG |
    |---|---:|---:|
    | Abstention accuracy (unanswerable) | 0.80 (8/10) | 1.00 (10/10) |
    | False abstention (answerable) | 0.30 (13/44) | 0.14 (6/44) |
    | Retrieval R@5 / R@8 / MRR (by page) | – | 0.845 / 0.879 / 0.671 |
    | Retrieval R@5 / R@8 / MRR (by snippet) | – | 0.754 / 0.799 / 0.566 |
    | Ragas faithfulness | – | 0.957 (n=19 of 38) |
    | Ragas answer relevancy | 0.944 (n=33) | 0.911 (n=19 of 38) |
    | Latency p50 | 1.7 s | 2.3 s |
    | LLM calls / tokens per question | 1 / 248 | 1 / 3291 |

  - C1 abstains on most unanswerable items because they name specific studies, not because it is grounded. C2's 6 false abstentions: 4 are retrieval misses (test-012, 013, 036, 041); test-007 and 009 had the passage but abstained. Dense retrieval misses at least one gold passage in 5 of 8 multi/comparison items.
  - **Manual checks for the team:** review the 54 test items in `eval/data/benchmark_v1.jsonl` (especially the 10 unanswerable) and set `verified_by`; read `eval/reports/*_eval_C2_test_*.md`; read the prompts in `eval/prompts/`. Rerun with `LLM_STRONG_PROVIDER=gemini LLM_FAST_PROVIDER=groq EVAL_JUDGE_PROVIDER=groq` (C2 ≈ 35 min).

- Task #11 `p2/phase-2-done` (Phase 2, D-071):
  - The Dockerfile sets `LLM_FAST_PROVIDER=groq` and `LLM_STRONG_PROVIDER=gemini` after the model layer, so the weights are not downloaded again. Without the keys the Space refuses to start instead of answering with the fake LLM.
  - `scripts/measure_qa.py` measures NFR-01 and NFR-13 over the API:
    - It ingests the corpora and asks each question in a new conversation.
    - It parses the SSE stream (first event, total time, outcome, claims and citations) and resumes paused runs with `corpus_only`.
    - LLM calls and tokens come from `agent_runs` (read through `DATABASE_URL` as the token's user, before the workspaces are deleted).
    - The default is a 12-item test sample.
  - `eval.metrics.percentile` is now public. `docs/SETUP.md` §9 is the Phase 2 release checklist. 859 unit tests.
  - Local check (dev, laptop, 2 items): test-001 answered in 14.5 s, test-046 paused and abstained in 9.8 s; first event ≤ 1.1 s; 2 LLM calls each. Not recorded; the Space run is the measurement.
  - **Manual checks for the team:** read `scripts/measure_qa.py` and SETUP §9; follow §9 for the release.
  - Release 2026-10-07: see Phase 2 exit criteria and the Measurements table "QA on the Space".

- Phase 3 task #6 `p3/source-viewer` (FR-13): clicking a workspace citation chip opens a side panel (`source-viewer.tsx`, `react-pdf` 11, client-only) with the PDF from `getDocumentFileUrl` at `page_start`, page navigation, and the quote marked in the text layer.
  - `pdf-highlight.ts` matches the quote by words over the whole page text (split items, line-end hyphens, tags, "…" ignored) and marks the longest run, so a quote crossing a page break marks each part. If nothing matches, the stored quote is shown above the page.
  - Checked against pdf.js text of 3 arXiv papers: 26/26 real `CitationService` quotes highlighted, nearly all in full. Frontend unit tests via `npm test` (Node `node --test`, no new dependency; not in CI yet).
  - **Verify manually:** ask a question, click a citation chip → panel opens on the cited page with the passage in yellow and scrolled into view; prev/next work; Esc closes; on a phone width the panel is full screen.

- Phase 3 task #7 `p3/e2e` (SRS §22): Playwright spec `frontend/e2e/source-viewer.spec.ts` — sign in, create a workspace, upload Pang 2023 (downloaded from arXiv into the git-ignored `e2e/.data/`), wait for `ready`, ask, click a citation chip, expect a highlighted `<mark>` in the viewer; the workspace is deleted afterwards (a cleanup failure fails the test). `npm run e2e` reads `E2E_BASE_URL`, `E2E_EMAIL`, `E2E_PASSWORD`; trace and video on.
  - Runs from the manual workflow `.github/workflows/e2e.yml` (separate from `ci.yml` so it never runs on push); artifacts `playwright` (report, trace, video).
  - Verified locally against the dev project (backend + `npm run dev`, a throwaway dev user, deleted afterwards): passed in 3.8–4.3 min; no workspace, document, conversation or run left. Not yet run on the deployed app.
  - Local run needs Chromium's system libraries (`libnspr4`, `libnss3`, `libasound2`); without `sudo` they can be unpacked from `apt-get download` into a folder on `LD_LIBRARY_PATH`.
  - **To finish Phase 3:** merge this PR, run **Actions → E2E → Run workflow** on `dev`/`main`, then tag `phase-3-done` once it passes.

## Measurements

**Local CPU inference** (task #1, development laptop: i5-1240P under WSL2, 8 torch threads, ~400-token passages; the Space numbers come in task #9):

| Model | Workload | p50 (ms) | p95 (ms) |
|---|---|---|---|
| bge-base-en-v1.5 | 1 query | 65 | 68 |
| bge-base-en-v1.5 | 32 passages | 18 940 | 20 620 |
| bge-reranker-base | 1 query × 20 passages | 11 504 | 11 578 |
| bge-reranker-base | 1 query × 30 passages | 17 672 | 18 028 |
| bge-reranker-base | 1 query × 60 passages | 35 540 | 35 706 |
| nli-deberta-v3-base | 8 pairs | 7 130 | 9 279 |

**Embedding comparison** (D-048; 3 papers, 147 chunks, 16 questions, so only large differences count):

| Model | Hit by | R@1 | R@5 | R@10 | MRR | Embed 147 chunks |
|---|---|---|---|---|---|---|
| bge-small-en-v1.5 | snippet | 0.56 | 0.81 | 0.94 | 0.67 | 25.5 s |
| bge-small-en-v1.5 | page | 0.56 | 0.88 | 0.94 | 0.70 | 25.5 s |
| bge-base-en-v1.5 | snippet | 0.44 | 0.88 | 0.94 | 0.63 | 75.8 s |
| bge-base-en-v1.5 | page | 0.50 | 0.94 | 1.00 | 0.70 | 75.8 s |

bge-base is not clearly worse, so it stays the default under D-048. It is about 3× slower to embed. (Reversed by D-050.)

**Reranker quality** (task 1a, `scripts/compare_rerankers.py`; bge-small dense top 30 + BM25 top 30 → RRF → top 20 reranked; Recall@5):

| Question set | Stage | R@5 snippet | R@5 page | Rerank s/question |
|---|---|---|---|---|
| embedding_comparison (16 q, 147 chunks) | RRF only | 0.81 | 0.94 | – |
| | bge-reranker-base | 0.88 | 0.94 | 11.2 |
| | ms-marco-MiniLM-L-6-v2 | 0.88 | 0.94 | 1.3 |
| embedding_check_v1 (17 q, 128 chunks) | RRF only | 0.94 | 1.00 | – |
| | bge-reranker-base | 0.82 | 0.88 | 11.2 |
| | ms-marco-MiniLM-L-6-v2 | 0.76 | 0.94 | 1.3 |

MiniLM is not clearly worse (tied on one set; one question lower by snippet but higher by page on the other), so D-051 stands. On embedding_check_v1, plain RRF beat both rerankers.

**Local CPU inference with the new defaults** (task 1a, same laptop, from the startup benchmark log):

```
CPUs (os.cpu_count): 16 · torch threads: 8
Models: BAAI/bge-small-en-v1.5, cross-encoder/ms-marco-MiniLM-L-6-v2, cross-encoder/nli-deberta-v3-base · load 6.1 s
```

| Model | Workload | p50 (ms) | p95 (ms) |
|---|---|---|---|
| embedding | 1 query | 20 | 27 |
| embedding | 20-page paper (40 chunks) | 6 630 | 7 075 |
| reranker | 1 query × 20 passages | 1 734 | 2 099 |
| reranker | 1 query × 30 passages | 2 581 | 2 686 |
| NLI | 8 pairs | 7 511 | 7 767 |
| NLI | 24 pairs | 24 219 | 40 007 |

**Deployed tier: CPU inference on the Space** (task 1a defaults; CPU basic, 2 torch threads; ~300-word passages; startup benchmark):

| Model | Workload | p50 |
|---|---|---|
| bge-small-en-v1.5 | 1 query | 32 ms |
| bge-small-en-v1.5 | 20-page paper (40 chunks) | 5.1 s |
| ms-marco-MiniLM-L-6-v2 | 1 query × 20 passages | 1.3 s |
| ms-marco-MiniLM-L-6-v2 | 1 query × 30 passages | 2.0 s |
| nli-deberta-v3-base | 8 pairs | 5.6 s |
| nli-deberta-v3-base | 24 pairs | 16.6 s |

**Deployed tier with the Phase 2 NLI model** (task #11 release, 2026-10-07; CPU basic, 2 torch threads, ~300-word passages, 3 timed runs; startup benchmark log, no JSON):

| Model | Workload | p50 (ms) | p95 (ms) |
|---|---|---|---|
| bge-small-en-v1.5 | 1 query | 22 | 23 |
| bge-small-en-v1.5 | 20-page paper (40 chunks) | 5 304 | 5 400 |
| ms-marco-MiniLM-L-6-v2 | 1 query × 20 passages | 1 415 | 1 449 |
| ms-marco-MiniLM-L-6-v2 | 1 query × 30 passages | 2 147 | 2 151 |
| nli-deberta-v3-xsmall | 8 pairs | 2 027 | 2 105 |
| nli-deberta-v3-xsmall | 24 pairs | 6 950 | 7 350 |

NLI is ~2.5–2.8× faster than nli-deberta-v3-base on the same tier (5.6 s / 16.6 s); embedding and reranking match Phase 1.

**QA on the Space** (task #11 release, 2026-10-07; HF CPU basic, prod DB; Groq gpt-oss-20b fast, Gemini 3.5 Flash-Lite strong, NLI deberta-v3-xsmall; times measured from the client; `2026-10-07T174426Z_measure_qa_09f134b.json`):

| Item | Type | Outcome | Paused | First event (s) | Total (s) | LLM calls | Tokens |
|---|---|---|---|---:|---:|---:|---:|
| test-001 | single | answered | no | 0.32 | 4.51 | 2 | 4360 |
| test-008 | single | answered | no | 0.31 | 6.05 | 4 | 10079 |
| test-014 | single | answered | no | 0.39 | 6.00 | 4 | 10212 |
| test-020 | single | answered | no | 0.30 | 7.28 | 4 | 9596 |
| test-025 | single | answered | no | 0.32 | 6.26 | 4 | 9514 |
| test-031 | single | answered | no | 0.31 | 32.25 | 4 | 10491 |
| test-033 | single | answered | no | 0.30 | 5.98 | 3 | 5716 |
| test-039 | multi | answered | no | 0.30 | 15.61 | 8 | 23886 |
| test-042 | multi | answered | no | 0.31 | 11.77 | 3 | 10746 |
| test-038 | comparison | answered | yes | 0.29 | 20.36 | 4 | 16819 |
| test-046 | unanswerable | abstained | yes | 0.29 | 5.49 | 2 | 4971 |
| test-051 | unanswerable | abstained | yes | 0.30 | 4.70 | 2 | 5111 |

12/12 correct outcomes, 0 errors. NFR-01: first event max 0.39 s; answered p50 6.77 s / p90 20.36 s. NFR-13: 3.67 LLM calls per question on average (max 8), ~10.1K tokens. test-039 is the only run with A3 revisions (two A2 rewrites → 8 calls).

- Task #3 `p1/auth-workspaces`: Supabase JWT verification against the JWKS (`app/core/auth.py`: ES256/RS256 only, issuer, audience `authenticated`, 30 s leeway on `exp`/`nbf`, keys cached 10 min, unknown `kid` refetches at most every 30 s, rejection reason logged without the token); `SUPABASE_URL` required in prod, 503 when unconfigured elsewhere. FR-02 endpoints `GET/POST /workspaces` (limit 50/max 100, offset), `GET/PATCH/DELETE /workspaces/{id}`; non-owned → 404; DELETE per D-046 (Storage deletion hook for task #6 in `WorkspaceService.delete`). Frontend types regenerated. 75 new unit tests (268 total); 7 repository integration tests (also in CI, D-053) pass on Supabase dev; the two-user auth test is written but not yet run (needs test users).
  - **Manual checks for the team:**
    - Create two dev test users and fill the `backend/.env` entries from `docs/SETUP.md` ("Supabase dev test users"), then `uv run pytest -m integration tests/integration/test_auth_supabase.py` → 2 passed.
    - Check **Project Settings → JWT Keys** in dev and prod: the current signing key must be ES256 or RS256.
    - **Before the next deploy:** add the `SUPABASE_URL` secret on the Space (the Dockerfile sets `ENVIRONMENT=prod`, so the app will not start without it).
    - With `SUPABASE_URL` in `backend/.env`, open `/docs`, **Authorize** with a dev access token, and try the workspace endpoints.
- Task #4 `p1/pdf-parser`: `PyMuPDF4LLMParser` (per-page Markdown, OCR off, page = PDF index per D-054, scanned check < 100 non-space chars/page average); `page_cleanup` removes short lines repeated on ≥ 3 pages and ≥ 50% of pages (digits folded except in headings, table rows kept, removals logged at DEBUG); `chunking` (heading sections carried across pages, 350–450 model tokens via `count_tokens` (D-055), ~12% overlap within a section, sha256 per chunk; chunks under `CHUNK_MERGE_BELOW_TOKENS` (80) merge into a same-section neighbour, capped at `CHUNK_HARD_MAX_TOKENS` (510)). `scripts/parse_papers.py` reports on real papers. Whitespace stripped from all settings; unit tests never read `backend/.env` or shell config variables.
  - Real papers (bge-small tokenizer; parse time on the dev machine):

    | Paper | Pages | Avg chars/page | Chunks | Tokens min / median / max | Under 80 | Parse |
    |---|---:|---:|---:|---|---:|---:|
    | Advancements_in_Surface_Modification | 28 | 1412 | 43 | 4 / 375 / 449 | 2 | 5.2 s |
    | Architected_Hydrogels_for_Functional_Tissue | 33 | 2374 | 85 | 4 / 395 / 461 | 7 | 9.3 s |
    | Hydrogels_for_Biomedical_Applications | 17 | 1826 | 37 | 3 / 408 / 450 | 6 | 5.6 s |
    | Plasmonic_Nanomaterials (two-column) | 11 | 3687 | 42 | 8 / 408 / 451 | 7 | 4.5 s |
    | Repurposing_biomedical_muscle_tissue_engineering (NIH) | 34 | 2631 | 78 | 21 / 426 / 450 | 12 | 9.7 s |
    | Tissue_Regeneration (ChemRxiv) | 29 | 1885 | 49 | 8 / 419 / 449 | 2 | 7.3 s |

  - **Manual checks for the team:** `uv run python -m scripts.parse_papers --show-chunks Plasmonic_Nanomaterials.pdf --start 5 --count 4` and read the column order; `uv run pytest tests/unit/test_real_papers.py` (~40 s, skipped without the papers).
- Task #5 `p1/metadata-doi`: `MetadataService` (`app/services/document_metadata.py`): PDF title/authors (mojibake → missing, Braille-block junk stripped), title fallback = first top-level heading on pages 1–2; DOI candidates from the raw text of pages 1–2 (line-end matches first, trailing punctuation stripped), each confirmed by `LiveScholarlySearch.get_by_doi` (Crossref, then OpenAlex; `CONTACT_EMAIL` polite pool; 5 s timeout). Lookup fields win, the PDF fills gaps; only confirmed DOIs are stored, so an outage keeps the PDF metadata with no DOI (D-056). No LLM calls.
  - Six papers, live lookup: all six DOIs found and confirmed by Crossref, with title, authors, year and venue (ChemRxiv preprints get "ChemRxiv" from a DOI-prefix map; Crossref has no container title for them). The expected Advancements DOI `…t0vm91` is not registered; the paper's DOI is `10.26434/chemrxiv-2023-t0vm9`.
  - **Manual checks for the team:** set `CONTACT_EMAIL` in `backend/.env` (a team address), then `uv run python -m scripts.extract_metadata` and `uv run pytest -m integration tests/integration/test_crossref.py` (skips if Crossref or OpenAlex returns 5xx or times out).
  - **For task #6:** `documents.doi` holds only confirmed DOIs (D-056), so no extra column is needed. A document ingested during a lookup outage keeps no DOI (there is no re-lookup yet).

- Task #6 `p1/ingestion`: `POST/GET /workspaces/{id}/documents`, `PUT`/`DELETE /workspaces/{id}/documents/{doc_id}`, `GET /documents/{id}`, `GET /documents/{id}/file` (signed URL, 300 s). Upload: 25 MB cap while reading (413), `%PDF-` in the first 1 KB (415), SHA-256 duplicate per user → 200 `duplicate: true` with `linked`; a failed duplicate is re-ingested. Migration 0003: unique `(user_id, content_hash)`, insert `ON CONFLICT DO NOTHING` (D-057). Storage through its REST API with the secret key (`app/repositories/storage.py`); the workspace-delete hook now deletes files. Background pipeline (`app/services/ingestion.py`): parsing → embedding → ready / failed with reason, behind `INGESTION_CONCURRENCY`; stale sweep at startup and every `INGESTION_SWEEP_INTERVAL_MINUTES` for documents older than `INGESTION_STALE_MINUTES` that this process is not still processing (D-058). Title/authors/venue: tags and entities removed. S6 input: NUL, control characters, and lone surrogates removed before chunking and from metadata. Dockerfile sets `PARSER_PROVIDER=pymupdf4llm`. 474 unit tests; 36 integration tests pass on dev (`test_documents_db.py`, incl. the concurrent-upload race, also runs in CI's pgvector job).
  - **NFR-02, local** (i5-1240P, WSL2, models preloaded): 20-page arXiv 2303.11051 → `ready` in 31.9 s (52 chunks; parse ~12 s, embed ~16 s). Over HTTP, a 17-page paper uploaded behind it waited in `uploaded` and was ready at 51.6 s. The Space number is task #9.
  - **Manual checks for the team:**
    - `uv sync`; dev: `uv run alembic upgrade head` → `0003` (already applied to dev). Prod: before the Phase 1 merge.
    - Space secrets: `SUPABASE_SECRET_KEY` (required in prod, else startup fails), `CONTACT_EMAIL`, variable `SEARCH_PROVIDER=live`; create the prod `documents` bucket (docs/SETUP.md).
    - `uv run pytest -m integration tests/integration/test_ingestion_supabase.py -s` prints the time to `ready`.
    - `/docs`: upload a PDF, poll `GET /documents/{id}` to `ready`, open the `/file` URL; another user gets 404.

- Task #7 `p1/retrieval`: `ChunkRepository` (`app/repositories/chunks.py`): every query requires `user_id` + `workspace_id` and sees only `ready` documents linked to the user's workspace. Dense: exact cosine in a `MATERIALIZED` CTE, filtered by the current `embedding_model`. Lexical: OR of `plainto_tsquery` lexemes, `ts_rank_cd` (D-059). `RetrievalService` (S2): embed → dense 30 + lexical 30 → RRF (k 60) → rerank 20 → top 8, each result with page/section provenance and per-stage ranks/scores; empty or > 1000-char queries → 422. `POST /workspaces/{id}/retrieval/debug` returns every candidate and per-stage timings. 499 unit tests; `test_retrieval_db.py` (isolation, EXPLAIN has no HNSW scan with a positive control, small-workspace top-k, operator/stopword queries) runs in CI's pgvector job.
  - **Retrieval quality on dev** (real parser, bge-small, MiniLM reranker; `test_retrieval_supabase.py`):

    | Set | Snippet R@5 / R@8 / MRR | Page R@5 / R@8 / MRR | Latency p50 (local) |
    |---|---|---|---|
    | embedding_comparison (16 q, 3 papers) | 0.88 / 0.88 / 0.68 | 0.94 / 0.94 / 0.82 | 1.9 s |
    | embedding_check_v1 (17 q, 3 papers) | 0.82 / 1.00 / 0.73 | 0.82 / 1.00 / 0.82 | 1.9 s |

    The one miss ("Why is the polylactide used in the inks amorphous?") returns the Introduction instead of the methods passage.
  - **Manual checks for the team:** `uv run pytest -m integration tests/integration/test_retrieval_db.py tests/integration/test_retrieval_supabase.py -s` (needs the PDFs in `scripts/data/`); in `/docs`, `POST /workspaces/{id}/retrieval/debug` on a workspace with ready papers shows page/section per result; another user gets 404.
- Task #8 `p1/compatibility`: S7 (`app/services/topic_profile.py`, `app/repositories/topic_profiles.py`): document vector = normalized mean of the first 4 chunks; workspace centroid updated incrementally (row locked) when a document becomes ready (score stored on the link), is linked with `PUT` (409 `compatibility_warning` below threshold unless `override=true`), or is removed. `POST /workspaces/{id}/documents/compatibility` parses only the first 3 pages (`max_pages` on the parser), stores nothing, skips empty workspaces; upload takes `override`. Threshold 0.83 from `scripts/calibrate_compatibility.py`: on-topic 0.870–0.926 (Plasmonic 0.870 lowest), off-topic 0.685/0.788 (D-060). 532 unit tests; `test_topic_profiles_db.py` added to CI's pgvector job.
- Task #9 `p1/phase-1-done`: `scripts/experiment_log.py` — every measurement script (compare_embeddings, compare_rerankers, calibrate_compatibility, bench_cpu, measure_ingestion; the retrieval evaluation with `RECORD_EXPERIMENT=1`) writes `docs/experiments/<UTC time>_<name>_<sha7>.json`: date, commit and dirty flag, models, an allow-list of settings, script parameters, dataset, hardware, per-item results, summary. Writing refuses if any `SecretStr` setting or a passed secret (the token) appears. `scripts/measure_ingestion.py` (NFR-02 over the API; stage times = first poll that saw each status). `docs/SETUP.md` §8 Phase 1 release checklist. 17 new unit tests (549 total).
  - Re-runs reproduce the earlier tables (embeddings, rerankers, calibration, retrieval). The local CPU benchmark was ~1.5× slower than task 1a (on battery, under load; `*_bench_cpu_*.json`); the deployed-tier numbers are unchanged. The JSONs show `git_dirty: true` only because of an uncommitted `CLAUDE.md` edit.
  - Fixed on the way: `test_retrieval_supabase.py` did not pass the `profiles` argument `DocumentService` needs since task #8 (mypy error; the test could not run).
  - **Manual checks for the team:** `uv run pytest tests/unit/scripts`; open a JSON in `docs/experiments/` and compare with the PROGRESS tables; follow docs/SETUP.md §8.

- Phase 3 task #1 `p3/chat-history-api` (D-072): fixes two gaps that block the chat UI.
  - `GET /conversations/{id}/messages` now returns each answer's claims, evidence, and citations, in a fixed number of queries.
  - The question message stores its `run_id`. New `GET /runs/{run_id}` returns status, error, timestamps, and, while paused, the full `ApprovalRequest` read from the checkpoint (falls back to the logged reason and options). Other users get 404.
  - Tests: 865 unit (new: history with claims, reload → `getRun` → resume, checkpoint fallback, cross-user 404, 503); integration on dev: `test_conversations_db.py` 17 passed, `test_qa_checkpointer_db.py` 3 passed (`getRun` after a restart). Frontend types regenerated.
  - **Verify manually:** ask an unanswerable question in `/docs`, then `GET /conversations/{id}/messages` → the question has `run_id`; `GET /runs/{run_id}` → `interrupted` with `approval.sub_questions`; resume → `GET /runs/{run_id}` → `completed`, `approval: null`.

## Known issues

- **Knowledge graph NLI shares the CPU slot with chat** (D-083): graph validation runs the local NLI model, which shares `LOCAL_INFERENCE_CONCURRENCY=1` with chat's reranker and NLI, so a chat question during a graph job may wait for one NLI batch. To be measured in the Phase 4 quality run.
- **Knowledge graph thresholds and limits are provisional** (D-083): graph tier limits, chunk selection, batch size and NLI thresholds are unmeasured until the model check and Phase 4.
- **Contradictions and synthesis lean on abstracts** (seen in Phase 4 manual testing, Huebsch 2010 vs. Khetan 2013): the known pair was detected ("Depends on context"), but every finding cited p.1. The topic is one query per paper with `synthesis_top_k=4`, and the abstract outranks results passages, so findings lack exact conditions and the uncited context note used details (alginate) from passages it does not show. Possible fix: raise `synthesis_top_k` to ~8 or have the findings prompt prefer results passages. Not done.
- **Compare handles review papers inconsistently** (seen in Phase 4 manual testing, 3 reviews): Zauchner 2022 got "Not reported" for methodology and materials, while Samandari 2023 and Mukherjee 2025 got the methods/materials they discuss; Mukherjee's objective came from one section, not the abstract. Cause: `ATTRIBUTE_QUERIES` are worded for experimental studies ("…used in the study") with `compare_top_k=3`, and `comparison.v1.md` has no rule for reviews. Possible fix: neutral queries and a v2 prompt rule ("for a review, report what it covers"). Not done.
- **Gap report lists per-paper limitations, not gaps** (seen in Phase 4 manual testing): most entries state a limitation ("X suffers from…") rather than what is missing, and limitations shared across papers (weak animal-free scaffolds in Samandari, weak hydrogels in Mukherjee) were not merged, although `gap_analysis.v1.md` rule 1 puts recurring ones first. Every gap is still cited (exit criterion met). Possible fix: `gap_analysis.v2.md` phrasing gaps as open questions and merging shared ones. Not done.
- **Body text labelled "References"** (seen in Phase 4 manual testing): in Samandari 2023 (Trends Biotechnol.), p.14 chunks with real content (regulation, bioreactor scale, consumer acceptance; likely the "Outstanding questions" box) carry the section `References`, because the parser reads them after that heading. Citations still point to the right page; only the section label is wrong. Ingestion also never drops reference-list chunks, so those can be retrieved as evidence. Fix would be in the parser/chunker (re-ingest needed); not done.
- **Many listed open-access PDFs cannot be downloaded** (D-077 live check, 2026-10-15): of 7 OpenAlex results with a listed open-access PDF, 2 downloaded; Wiley and MDPI answered 403 to any automated client and one IOP link returned HTML. Discover therefore probes each listed PDF at search time and shows the rest as link only, so fewer OpenAlex results are importable than "open access" suggests. arXiv's own PDFs are reliable. Not fixable without bypassing publisher bot protection (out of scope); Europe PMC's PDF links also return 403 and the NCBI PMC OA service now redirects to HTML (checked 2026-10-15, D-079). The "Importable PDFs only" filter (OpenAlex `open_access.is_oa:true`) raised verified PDFs from 24 to 35 in 80 results across eight fields; coverage varies by field (physics 9/10, economics 0/10).
- **"Timed out." on import (fixed in D-079)** (manual testing, 2026-10-15): the message came from the import-time paper lookup (5 s, no retry), and its raw text reached the UI; a live run also showed OpenAlex searches exceeding 5 s. Discover now uses a 15 s timeout with one retry, and the UI maps errors to plain reasons.
- **OpenAlex keyless quota** (D-080): about 100 searches a day per IP address (shared by every user of the Space). Set `OPENALEX_API_KEY` (free) for about 1,000. When it is used up, Discover shows arXiv results only with a notice.
- **arXiv search ANDs every word** (D-077): long queries can return no arXiv results (e.g. 5 specific words), while OpenAlex still answers. Stopwords are dropped; a looser query (OR fallback) is not built.
- **Later questions appeared only with their answer (fixed in `p3/fix-perf`)** (seen after Phase 3): the chat hid the live block while the previous answer's id was in the history, so from the second question on the question showed up ~10 s late. The answer id now belongs to the live run; regression test `live.test.ts`.
- **Upload takes about a minute on the Space** (seen after Phase 3): parse → metadata (LLM + DOI lookups) → embedding ran one after another, one document at a time. `p3/fix-perf` runs the metadata lookup during embedding; the time on the Space still needs re-measuring (SETUP §10 step 5).

- **Chunk text can contain `<mark>` tags** (seen in Phase 3 task #6): pymupdf4llm writes PDF highlight annotations (e.g. Pang 2023) as `<mark>…</mark>`, so stored chunks and quotes carry the tags and the citation hover preview shows them literally. The source viewer ignores them when matching. Fix would be in ingestion cleaning (re-ingest needed); not done.

- **General-knowledge approval still abstained (fixed in `p3/fix-gk-abstain`)** (seen in Phase 3 task #5): after a `general_knowledge` approval, A2 wrote only `gap` sentences for uncovered parts, so no claims were left and the run abstained. Synthesis prompt v2 requires `general` sentences after each gap in that mode; live regression test `test_general_knowledge_mode_answers_what_the_papers_do_not_cover`. The abstention also printed "?." after a question; fixed with a unit test.

- **No browser for Playwright on the dev machine** (Phase 3 task #2b): Playwright's bundled browsers don't support Ubuntu 26.04, and `sudo` is needed to install Google Chrome from its `.deb`. Workaround used for the landing screenshots: the `.deb` (plus `libnss3`, `libnspr4`, `libasound2t64` from `apt-get download`) extracted without root and passed to `playwright-core` as `executablePath`. For task #7, either install the `.deb` once (`sudo apt install ./google-chrome-stable_current_amd64.deb`) and use `channel: "chrome"`, or run E2E only in the planned `workflow_dispatch` job on `ubuntu-24.04`.
- ~~DESIGN.md §10 checks pending~~ (task #2b): Impeccable and `review-animations` are now in `.claude/skills/`; the checks are DESIGN.md §12 (D-088).
- **Knowledge graph page has no "Experimental" label** (found in the D-088 docs audit): the page asks users to check each passage but doesn't say the feature is experimental (D-087). Added with the app shell (DESIGN.md §13 step 1).
- **Flaky message order (fixed in PR #43)** (from Phase 3 task #1): `messages.created_at` defaulted to `now()`, the transaction start time, so messages saved in one transaction tied and the history order fell back to the random id. `test_history_loads_each_answers_claims_and_citations` failed in CI about half the time (PR #42 push run). Migration 0006 sets the default to `clock_timestamp()`; regression test `test_messages_saved_in_one_transaction_keep_insert_order`. Prod still needs `alembic upgrade head` at the next release.
- **`GET /chunks/{id}` not built** (Phase 3 task #1, D-072): listed in SRS §16.1. Not needed for the source viewer: each citation carries the page range and a verbatim `quote` from the chunk. The quote comes from PyMuPDF4LLM Markdown, so the viewer must match it loosely against the PDF text layer.
- **`corpus_web` approval does nothing until Phase 5** (Phase 3 task #1): resuming with it answers corpus-only and appends "External research search is not available yet…" to the answer. The UI disables that option until Phase 5.
- **Ragas judge quota** (task #10): the Groq free tier also caps tokens per day; C2 used it up after 19 of 38 answers, so the C2 Ragas numbers cover half the answers (`judge_error` = `LLMQuotaExceededError` on the rest). The client limiter counts only requests per day. The rerun moves to Phase 8 with the final model (D-070).
- **Live tests need a real fast tier** (task #10, from task #9): ingestion reads paper metadata with the fast tier, so `test_synthesis_live.py`/`test_verification_live.py` fail at ingestion when `LLM_FAST_PROVIDER=fake` (`live_settings` does not set it). Before task #10 the workspace was silently empty; the shared helper now raises. Fix: set the fast tier in `live_settings` (needs approval).
- **Dev bucket accepts any MIME type**: `GET /storage/v1/bucket/documents` reports `allowed_mime_types: null` (25 MB limit is set). The backend checks the PDF header anyway; set `application/pdf` in the dashboard to match docs/SETUP.md.
- **Latency outlier test-031** (task #11): 32.3 s with 4 LLM calls and no revision, while every other single-paper question took 4.5–7.3 s. The cause (slow Gemini response or NLI over its 4 citations) is not known yet; check its LangSmith trace. NFR-01 still holds (p90 20.4 s), but 12 items give a rough p90.
- **Answerable comparison asked for web approval** (task #11): test-038 paused at S3 (sufficiency `partial`), then answered after `corpus_only` with 2 claims. Comparisons may often stop for approval; recheck with the full comparison set in Phase 4/8.
- **A3 judge strictness is untested on real rejections** (task #6): in the live check the judge marked all 8 claims it saw supported, and the 102 verifier pairs are unverified and test NLI only. The verifier agreement study (Phase 8) measures the judge; until then the judge prompt is unvalidated.

- **Reference lists become chunks** (for Phase 2): 88 of 334 chunks (26%) across the six papers are in a "References" section; they may add retrieval noise. Not filtered now; decide in Phase 2 with the retrieval evaluation.
- **Short chunks** (task #4): after merging, 36 of 334 chunks are under 80 tokens (39 before), and every one is the only chunk of its section: front matter (journal banner, affiliations, a title heading repeated on the cover page) and one-paragraph sections. Merging never crosses sections, so they stay; revisit with the retrieval evaluation.
- **Strong-tier model quality** (task #1): `gemini-3.5-flash-lite` was chosen for its 500 requests/day; non-lite Flash models allow 20/day on the free tier. The comparison moves to Phase 8, together with the choice of a paid final model (D-070). It ignores `temperature`, so runs are not bit-reproducible.
- **Compatibility margin is thin** (task #8): only two off-topic papers (arXiv 2006.04992, 2502.05186), gap 0.788–0.870. Re-check with more off-topic and borderline papers when the benchmark corpus grows.
- **`agent_runs.trace_url` stays empty** (task #7): LangSmith traces carry `agent_run_id` and `conversation_id` metadata, so a run's trace can be found by filter, but resolving the URL needs a LangSmith API call per run. Decide in task #11 whether to add it.
- **Paused runs keep document text after deletion** (task #7): the checkpoints of an `interrupted` run hold its chunk text. Deleting the workspace removes the run (cascade) but not its checkpoints in `langgraph`. Finished runs delete theirs. Fix with an orphan-thread cleanup in the stale sweep if needed.
- **Named papers match titles only** (task #7): references by author and year ("Smith et al. 2023") do not resolve, and retrieval then searches every paper. Authors are stored, so this can be added if the benchmark shows a need.
- **A1 tokens vs Groq TPM** (task #3): ~1.2–1.4K tokens per A1 call against 8K tokens/min on the free tier, so A1 alone allows about 6 questions per minute.
- **Fast-pass cutoff is provisional** (task #4, D-065): 0.97 rests on an unverified split with one unanswerable question at 0.926; recalibrate after human review. Two answerable questions miss retrieval entirely (cal-030 printing speed by snippet, cal-032 amorphous PLA), a retrieval issue for task #10.

**Resolved**
- ~~NLI latency threatens NFR-01~~ (Phase 1, measured again on the Space in task #11): nli-deberta-v3-xsmall costs ~0.25–0.29 s per pair on the Space (24 pairs in 7.0 s vs 16.6 s for base), and answered questions take p50 6.8 s / p90 20.4 s on CPU basic, within NFR-01.
- ~~Failed answer save leaves the run `running`~~ (task #2): the runner marks the run `failed` in its own transaction, and a sweep fails `running` runs older than `QA_RUN_STALE_MINUTES` that the process is not executing (task #7).
- ~~Named papers are not yet filters~~ (task #3): A1's `paper_refs` resolve to workspace documents and limit S2 (task #7).
- ~~Space image build fails~~ (found during the Phase 1 release): the model download step ran with `ENVIRONMENT=prod`, whose settings require `SUPABASE_URL`, but Space secrets are not available at build time. That step now runs as `local` (D-061); a CI job builds the image on PRs into `main`.
- ~~Filtered vector search can return fewer than top-k~~ (task #7): dense search is exact within the workspace (D-059); regression test with a small workspace among 400 closer chunks.
- ~~Interrupted ingestion can stay in progress~~ (task #6): the sweep now also runs every `INGESTION_SWEEP_INTERVAL_MINUTES` (5) and skips documents this process still has queued or running, so a stuck document becomes `failed` and a re-upload re-ingests it (D-058).
- ~~HTML markup in metadata titles~~ (task #5, found in task #6): title, authors, and venue are unescaped and stripped of tags before saving, from the PDF or the lookup; escaped `&amp;` no longer splits author names.
- ~~Windows Smart App Control blocks unsigned compiled modules~~ (found in task #2: `sqlalchemy/engine/_row_cy.cp311-win_amd64.pyd` was blocked). Resolved by moving development to WSL2 (D-030); the policy does not apply to Linux binaries.
- ~~Windows event loop for async psycopg~~ (D-025). Resolved by moving development to WSL2 (D-030); uvicorn on Linux uses a selector-based loop.

## Knowledge graph: future scope (experimental feature, D-087)

Not implemented; recorded so the experimental status is not mistaken for the finished feature.

- **Semantic extraction:** choose the extraction model (Gemma v2 is provisional); recall beyond quotes that name both entities.
- **Relationship accuracy:** measure precision on a human-verified sample against the 0.8 target (`eval/data/kg_judge_v1.jsonl` labels are still unverified drafts).
- **Entity consolidation:** acronym, alias, and evidence-backed embedding merges; today only exact normalized names merge.
- **Cross-paper connections:** shared entities and relationships across papers (none in the 3-paper dev run).
- **Interface:** filters by entity type and number of supporting papers; the graph re-skin in the UI redesign (DESIGN.md §13 step 4, no behaviour change).
- **Deployment:** the graph tier is off by default (`LLM_GRAPH_PROVIDER=fake`); turning it on in a deployment needs the `LLM_GRAPH_*` variables and approval.

## Planned scope additions

Approved database hardening from task #4 (PR #7), added on top of the SRS scope.

- Phase 1:
  - Every table migration runs `ALTER TABLE … ENABLE ROW LEVEL SECURITY` explicitly; an integration test asserts RLS on every `public` table.
  - The first migration revokes default table privileges in `public` from `anon` and `authenticated`.
  - A CI job runs `alembic upgrade head`, `alembic check`, and `downgrade base` against a throwaway `pgvector/pgvector:pg17` container.
- Phase 2:
  - LangGraph checkpoint tables live in their own `langgraph` schema; autogenerate excludes them by schema.

## Open questions

- Confirm or reverse D-036 (send the verified answer whole instead of token-streaming the draft) in Phase 2.
