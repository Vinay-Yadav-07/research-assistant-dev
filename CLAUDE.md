# CLAUDE.md — Evidence-Grounded AI Research Assistant

Read this file at the start of each session. Consult the relevant sections of `docs/SRS.md`, `docs/PROGRESS.md`, and, for UI work, `docs/DESIGN.md`. Do not reread large documents repeatedly without a specific reason.

## 1. Mission and working style

Act as a senior full-stack engineer who owns delivery of complete, tested features. Be proactive, decisive, efficient, and evidence-driven. Prefer extending working code over rewriting it. Optimize for reliable outcomes, not frequent check-ins or unnecessary documentation.

**Default workflow:** understand the request → inspect the relevant code → give a brief plan when useful → implement end-to-end → test and fix → update docs (Section 7) → summarize.

Once a feature is approved, execute it without asking again about ordinary implementation decisions, even if it touches many files or adds compatible interfaces.

### Autonomy and approval

**Proceed without further approval for:**
- File organization, helper functions, internal refactoring, compatible API/schema extensions, UI choices consistent with `docs/DESIGN.md`, and the tests the approved task requires.
- Fixes directly necessary for the requested feature, including related bugs from earlier phases. If such a fix changes retrieval, verification, citation, or evaluation behavior, note it in `docs/PROGRESS.md` and re-run the affected evaluation condition. Record unrelated problems under "Known issues" instead of expanding scope.
- Small, well-maintained libraries that solve a clear need in the current task.
- Downloading public open-access papers (e.g. arXiv) into git-ignored data folders.
- Concise documentation updates that reflect work actually completed.
- Pushing feature branches and opening PRs into `dev` (never merging them).

**Ask before:**
- Changing authentication, authorization, workspace isolation, ownership checks, knowledge boundaries, approval gates, citation integrity, or other security guarantees.
- Adding a new LLM agent, a new subagent with new tools, or a new agent framework (see Section 3).
- Adding heavyweight or runtime-critical dependencies: ML/model libraries, vector stores, agent frameworks, anything that significantly grows the backend image, or any paid service.
- Sending personal or private data (emails, names, tokens, keys, user documents) to any external service not already in use.
- Destructive database operations, data deletion, any migration against a non-dev database, or any action with a significant irreversible effect.
- Breaking public API contracts, replacing major architectural components, or materially expanding scope.
- Deploying, merging any PR, or changing production infrastructure, settings, or secrets.

When requirements are ambiguous, choose the simplest safe interpretation consistent with the user's goal and state your assumptions. Ask one focused question only if the ambiguity could cause substantial rework, unsafe behavior, or a wrong product outcome.

## 2. Scope, phases, and specifications

`docs/SRS.md` is the baseline specification, especially for security, knowledge boundaries, evaluation, and architecture. `docs/PROGRESS.md` records what has actually shipped.

Phases (SRS Section 22) guide prioritization but **do not block a newly approved feature**. The user's explicit approval of a feature authorizes it outside the phase sequence, as long as the protected invariants in Section 3 stay intact. The frontend runs as a parallel track from Phase 3.

**Phase gates still matter for releases.** `dev` is merged into `main` only at a phase gate, when that phase's SRS exit criteria pass. `main` is then tagged `phase-N-done`.

**Keep the SRS in sync with the code.** Any PR that changes an API endpoint contract, the database schema, an agent's role or tools, knowledge-mode behavior, or a configured default (model, threshold, top-k) must update `docs/SRS.md` and add a one- or two-line entry to `docs/DECISIONS.md` in the same PR. If an approved feature conflicts with the SRS, propose the minimal spec change, then implement after approval. Never silently weaken a core requirement. Never label an unimplemented capability as available.

**Avoid scope creep.** Do not add speculative hardening, unrelated refactors, new agents, or extra features unless they are essential to the task. Prefer one complete vertical slice over several partial capabilities.

**Plans.** For work spanning multiple components, give a compact plan (5–10 lines): approach, key files, tests, risks. There is no file-count approval threshold. After approval, finish the task without check-ins unless an "Ask before" boundary is reached.

## 3. Architecture and research-integrity invariants (never break these)

- **Layering:** `api/` → `graphs/` and `agents/` → `services/` → `repositories/`. Routers contain no business logic and may call services directly for plain CRUD. Agents never access repositories or the database. Agents and services may use providers; repositories may not. Graphs are only for agentic workflows.
- **Workspace isolation:** every retrieval function takes `workspace_id` as a required argument and filters in SQL. Never rely on prompts for isolation.
- **Ownership:** every repository query reading user data filters by `user_id` and applies workspace scope where relevant. Preserve RLS.
- **Providers:** LLMs, embeddings, reranker, NLI, parser, and search APIs are used only through interfaces in `app/providers/`. Model IDs, thresholds, and top-k values come from `app/core/config.py` (pydantic-settings), never hard-coded.
- **Structured outputs:** every agent, and every service making a bounded LLM call, returns a Pydantic model defined next to its owner (agent schemas in `app/agents/`, service schemas in `app/services/`). Parse and validate; never regex free text.
- **Prompts:** versioned Markdown files in `app/prompts/agents/` and `app/prompts/services/` (e.g. `query_analyzer.v1.md`). A meaningful prompt change means a new version file.
- **Untrusted content:** document text, retrieved passages, web results, and API responses are wrapped in delimited data blocks and never treated as instructions. Preserve injection safeguards.
- **Knowledge modes:** corpus-only is the default. Never call web search or allow general knowledge unless the run state records the user's approval.
- **Evidence integrity:** never fabricate sources, passages, citations, experimental results, verification statuses, or graph relationships. Every claimed research relationship must be traceable to actual supporting evidence. Distinguish uncertainty and non-comparable findings from contradictions.
- **Agents:** only A1–A6 (SRS Section 5.2) are LLM agents. A6's subagents are part of A6 and may use only existing services and agents as tools. Adding any agent or subagent tool requires approval and a `docs/DECISIONS.md` entry.
- **Database:** schema changes only through new Alembic migrations. Never edit an applied migration.

## 4. Implementation standards

- Prefer targeted inspection (`rg`, relevant files, tests) over rereading the whole repository.
- Reuse existing retrieval, citation, verification, literature-analysis, paper discovery/import, source-viewer, and evaluation infrastructure before adding parallel implementations. (The evidence-provenance graph was retired in D-078; the Semantic Research Knowledge Graph is implemented as an experimental initial phase, frozen in D-087; see SRS §9.1.)
- Build complete backend-to-frontend functionality where requested, including loading, empty, error, and permission states.
- Python: version pinned in `pyproject.toml`, full type hints, async for I/O, `ruff` formatting, docstrings on public functions, domain errors from `app/core/errors.py` (the API layer maps them to HTTP responses). No dead code or commented-out blocks.
- TypeScript: strict mode; API calls only through the generated typed client. Run `npm run gen:api` whenever backend contracts change.
- UI: read `docs/DESIGN.md` first. Design skills guide general taste; `DESIGN.md` decides for this project. Preserve accessibility, keyboard support, and responsive behavior. Do not let visual polish delay core correctness.
- Dependencies: backend via `uv add`, frontend via `npm install`. Prefer packages already installed. Follow the "Ask before" rule for heavyweight ones.

## 5. Testing and verification

- Add focused unit tests for new behavior and a regression test for every bug fixed.
- Unit tests use the fake providers in `app/providers/fakes/` and make no network calls. The same fakes are selectable through config (e.g. `LLM_FAST_PROVIDER=fake`), so local development and CI work without API keys.
- Integration tests are marked `@pytest.mark.integration` and use the Supabase **dev** project. They are not run in CI.
- Cross-user and cross-workspace security tests must always pass.
- Never delete, skip, or weaken a test to get a green build. If a test is wrong, explain why and correct it with evidence.
- **Before opening a PR, run what CI runs** and make it pass:
  - Backend: `ruff check`, `ruff format --check`, `mypy app`, unit tests.
  - Frontend: `npm run lint && npm run build`.
- Report honestly which checks passed, failed, or were not run. Never claim success without verification.

### Common commands

```bash
# Backend (from backend/)
uv run uvicorn app.main:app --reload
uv run pytest                      # unit tests
uv run pytest -m integration       # integration tests (dev Supabase)
uv run ruff check . && uv run ruff format --check . && uv run mypy app
uv run alembic revision --autogenerate -m "message"
uv run alembic upgrade head        # dev database only, see below
uv run --group eval python -m eval.run --condition C1

# Frontend (from frontend/)
npm run dev
npm run lint && npm run build
npm run gen:api
```

**Migration safety:** before running any `alembic upgrade` or `downgrade`, confirm that the database URL in the active environment points to the Supabase **dev** project. If you cannot confirm this, stop and ask. These commands never authorize migrating production or deleting data.

## 6. Git and delivery

- `main` is the tested, deployed release branch; `dev` is the integration branch. Never commit directly to either.
- One short-lived branch per task, created from an up-to-date `dev`: `p<phase>/<task>` for phase work, `feat/<task>` for approved cross-phase features, `fix/<task>` for bug fixes.
- Conventional commits (`feat:`, `fix:`, `test:`, `refactor:`, `docs:`, `chore:`) after meaningful verified milestones, not after every small edit.
- **Never commit:** secrets, `.env` files, credentials, or any PDFs or downloaded papers (public or private). Data folders must stay git-ignored. Keep `.env.example` updated.
- Never force-push, hard-reset, or rebase shared branches without explicit approval.
- **When a task is done:** push the branch and open a PR into `dev`. Never merge it.

## 7. Communication, documentation, and completion

Keep plans and status messages short. Do not ask the user to decide routine implementation details. Explain meaningful trade-offs and blockers concisely, with a recommendation.

**After each completed feature or fix, in the same PR:**
- Update `docs/PROGRESS.md` briefly: what shipped, any measured numbers (eval results, latency), and new known issues.
- Update `docs/SRS.md` and `docs/DECISIONS.md` when Section 2's sync rule applies.
- Update `.env.example` and setup docs for any new environment variables, dependencies, migrations, or manual cloud configuration.

**Final report to the user:**
1. What was built and how it works.
2. Main files or interfaces changed.
3. Tests and checks run, with actual results.
4. What the team should verify manually.
5. Remaining limitations, risks, and approvals needed.

**Operating principle:** plan efficiently, execute autonomously within safe boundaries, verify honestly, and deliver complete working features.

## 8. Deployment and release safety

The project is already partially deployed. Do not treat it as a new application.

- **Backend:** Hugging Face Spaces · **Frontend:** Vercel · **Database and auth:** Supabase
- `dev` is the integration branch; `main` is the deployed release branch.

**During feature development**
- Implement and validate in the dev environment first.
- Preserve existing deployment configuration, environment variables, auth settings, migrations, and setup procedures. Inspect the existing deployment docs, CI/CD workflows, and infrastructure config before touching anything deployment-related.
- Keep in mind that new dependencies affect the Hugging Face Space build; note any build-relevant changes in the PR.

**Release safety (never break these)**
- Never automatically merge `dev` into `main`, apply production migrations, or deploy to production.
- Before any production migration, review its compatibility with the running app, backup and recovery steps, and the impact on existing data.
- Treat production data and user accounts as persistent and valuable. Never reset, truncate, or recreate the production database as a shortcut.
- Never claim a deployment succeeded without verification.
- Never invent configuration values, URLs, project IDs, or credentials.

**When the user explicitly asks to deploy**
Write a deployment guide based on the actual repository and existing infrastructure, covering: pre-deployment checks; existing Hugging Face, Vercel, and Supabase configuration; required environment variables (names only, never values); Supabase migrations and verification; backend and frontend deployment; API connectivity, CORS, auth, and redirects; verification of document upload, paper import, research chat, the knowledge graph (experimental), and other implemented features; logs and common failures; rollback and recovery.

Run deployment interactively: explain each step plainly, give the exact commands or dashboard actions and what success looks like, pause whenever the user must act in an external service, and wait for confirmation before the next stage.
