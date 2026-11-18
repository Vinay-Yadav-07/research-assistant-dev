# Setup: accounts, secrets, and deployment

Everything in this file is done by hand, once, by the team (SRS §15.3). The code side is already in
the repository:

| Piece | Where | What it does |
|---|---|---|
| Backend image | `backend/Dockerfile`, `backend/README.md` (Space metadata) | Python 3.11, uv 0.12.21, `uv sync --locked`, user 1000, port 7860 |
| Backend deploy | `.github/workflows/deploy-backend.yml` | On push to `main` (changes under `backend/`), uploads `backend/` to the Space, which rebuilds the image |
| Frontend deploy | `frontend/vercel.json` | Vercel builds only the `main` branch |
| CORS | `CORS_ORIGINS` setting (`backend/app/core/config.py`) | Allowed frontend origins, set as a Space secret |

Follow the steps in order. The URLs depend on each other: the Supabase region depends on where the Space runs, Vercel needs the Space URL, and the Space needs the Vercel URL.

Placeholders used below:

- `<hf-user>`: the Hugging Face user or organization that owns the Space.
- `<space-name>`: the Space name, e.g. `research-assistant-api`.
- `<space-url>`: `https://<hf-user>-<space-name>.hf.space`. All lowercase; `_` and `.` become `-`. The exact URL is in the Space under **⋮ → Embed this Space → Direct URL**.
- `<vercel-url>`: the Vercel production URL, e.g. `https://research-assistant.vercel.app`.

---

## 1. Find the region the Space runs in

Hugging Face does not show the region of a Space. The `*.hf.space` addresses all point to the same hosting, so you can look up the addresses of any Space, including one you haven't created yet:

```bash
# WSL / Linux / macOS
nslookup huggingface-projects-llama-2-7b-chat.hf.space   # or your own <space-url> host later
curl -s https://ipinfo.io/<one-of-the-IPv4-addresses>     # look at "city", "region", "org"
```

On Windows PowerShell, use `Resolve-DnsName <host>`, then open `https://ipinfo.io/<ip>` in a browser.

- If WSL prints NAT64 addresses such as `64:ff9b::625a:bdb`, the last 32 bits are the IPv4 address: `625a:0bdb` → `98.90.11.219`.
- **Result on 2026-10-01:** Amazon (AWS) addresses in Ashburn, Virginia, i.e. AWS `us-east-1`. Choose the Supabase region **East US (North Virginia)** (`us-east-1`).
- Check again after creating the Space (with `<space-url>`'s host). If it shows somewhere else, choose the Supabase region closest to that place.

## 2. Supabase prod project

Use the same settings as the dev project (D-040).

1. Go to <https://supabase.com/dashboard> → **New project**.
   - Name: `research-assistant-prod`.
   - Database password: click **Generate a password** and save it in your password manager. Passwords without special characters are easier, because characters like `@ : / ? # %` must be URL-encoded in the connection string.
   - Region: the one from step 1 (**East US (North Virginia)**).
   - **Security options:** untick **Enable Data API**, and tick **Enable automatic RLS**.
2. Wait until the project is ready, then check the settings:
   - **Project Settings → Data API**: the Data API is disabled. If it is on, turn it off.
   - **SQL Editor**: run `select evtname, evtenabled from pg_event_trigger where evtname = 'ensure_rls';` → one row. If there are no rows, automatic RLS was not ticked. The dashboard can't add it afterwards; recreate the project, because it is still empty.
3. Get the connection string: click **Connect** (top bar) → **Connection String** → **Method: Session pooler**. Copy the URI. It looks like:
   ```
   postgresql://postgres.<project-ref>:[YOUR-PASSWORD]@aws-1-us-east-1.pooler.supabase.com:5432/postgres
   ```
   - Use the **session** pooler (port 5432). The direct connection is IPv6-only and Hugging Face has no IPv6. The transaction pooler (port 6543) breaks psycopg prepared statements (D-026).
   - Change the scheme to `postgresql+psycopg://` and put in the password (URL-encoded if needed). This is the **prod `DATABASE_URL`**. It is secret: never commit it or paste it into chat.
4. Run the migrations against prod from your machine (from `backend/`). An environment variable takes precedence over `backend/.env`, so your dev settings stay as they are:
   ```bash
   cd backend
   read -rs PROD_DB && export DATABASE_URL="$PROD_DB"   # paste the prod URL; nothing is echoed or saved in history
   uv run alembic upgrade head
   uv run alembic current        # → 0001 (head)
   uv run alembic check          # → No new upgrade operations detected.
   unset DATABASE_URL PROD_DB
   ```
   From now on, repeat this step **before** each `dev` → `main` merge that adds a migration (D-042).
   From migration 0005 on, also create the QA graph's checkpoint tables in the `langgraph` schema with the same `DATABASE_URL`: `uv run python -m scripts.setup_checkpointer` → `Checkpoint tables (RLS enabled): checkpoint_blobs, checkpoint_migrations, checkpoint_writes, checkpoints`. It is idempotent; run it again after every langgraph upgrade. The app never creates these tables itself.
5. **Table Editor** shows only `alembic_version` in `public`, with RLS enabled.

## 3. Hugging Face Space

Since July 2026, Docker Spaces require a **Hugging Face PRO** subscription (about ₹800/month; D-043).

1. Create a Hugging Face account at <https://huggingface.co/join>, if you don't have one, and subscribe to **PRO** at <https://huggingface.co/subscribe/pro> with the account that will own the Space.
2. Go to <https://huggingface.co/new-space>:
   - Owner `<hf-user>`, Space name `<space-name>`.
   - **SDK: Docker**, template **Blank**.
   - Hardware **CPU basic**.
   - Visibility **Protected**. The app at `<space-url>` stays publicly reachable, so the browser can call the API without a token. The Space's files (code, Dockerfile) stay private. Secrets are hidden in either case.
3. **Settings → Variables and secrets**. Use **New secret** for each:

   | Name | Value |
   |---|---|
   | `DATABASE_URL` | the prod `DATABASE_URL` from step 2.3 |
   | `CORS_ORIGINS` | `<vercel-url>` (no trailing slash). Until step 6, use `http://localhost:3000` |
   | `SUPABASE_URL` | the prod project URL, `https://<prod-ref>.supabase.co` (no trailing slash). Required: with `ENVIRONMENT=prod` the app refuses to start without it |
   | `SUPABASE_SECRET_KEY` | the prod **secret** key (**Project Settings → API Keys**, `sb_secret_…`). Required in prod. Server-side only: never put it in Vercel or the frontend |
   | `CONTACT_EMAIL` | a team address for Crossref/OpenAlex (needed with `SEARCH_PROVIDER=live`) |
   | `GROQ_API_KEY` | from Phase 2: the **demo-only** Groq key (D-070), never the development key. Required: the image uses Groq for the fast tier |
   | `GEMINI_API_KEY` | from Phase 2: the **demo-only** Gemini key (D-070). Required: the image uses Gemini for the strong tier |
   | `LANGSMITH_API_KEY` | from Phase 2: a LangSmith API key, for tracing (FR-28) |

   Also add the **variable** `SEARCH_PROVIDER` = `live`, so uploaded papers get confirmed DOIs (D-056). Without it the DOI lookup is skipped and only PDF metadata is stored. From Phase 2, also add the variables `LANGSMITH_TRACING` = `true` and `LANGSMITH_PROJECT` = `research-assistant-prod`.

   The Dockerfile sets `LLM_FAST_PROVIDER=groq` and `LLM_STRONG_PROVIDER=gemini` (D-071), so the app refuses to start without both keys instead of answering with the fake LLM.

   `ENVIRONMENT=prod`, `LOG_JSON=true`, `PRELOAD_MODELS=true`, `PARSER_PROVIDER=pymupdf4llm`, and the local model providers (`EMBEDDING_PROVIDER=sentence_transformers`, `RERANKER_PROVIDER=cross_encoder`, `NLI_PROVIDER=cross_encoder`) are already set in the Dockerfile. Don't override those three providers in the Space settings: the CPU benchmark refuses to run with a fake provider. The other settings keep their defaults.
4. Optional: repeat the region check from step 1 with your own host (`<hf-user>-<space-name>.hf.space`).

### Supabase Storage bucket (dev and prod)

In each project: **Storage → New bucket**, name `documents`, **Public bucket off**, **Restrict file size** 25 MB, **Restrict MIME types** `application/pdf`. Add no policies: only the backend's secret key reads and writes it (NFR-09, D-049). The app never creates buckets. For local development put the dev secret key in `backend/.env` as `SUPABASE_SECRET_KEY`.

### Supabase dev test users (auth integration test)

`tests/integration/test_auth_supabase.py` signs in two real users. In the **dev** project: **Authentication → Users → Add user → Create new user**, twice, with **Auto Confirm User** ticked. Then add to `backend/.env` (never commit it):

```bash
SUPABASE_URL=https://<dev-ref>.supabase.co
SUPABASE_PUBLISHABLE_KEY=<dev publishable key, Project Settings → API Keys>
TEST_USER_A_EMAIL=...
TEST_USER_A_PASSWORD=...
TEST_USER_B_EMAIL=...
TEST_USER_B_PASSWORD=...
```

The dev project must sign tokens with an asymmetric key (**Project Settings → JWT Keys**: current key ES256 or RS256). Tokens signed with the legacy HS256 secret are rejected.

## 4. Hugging Face token for GitHub Actions

1. <https://huggingface.co/settings/tokens> → **Create new token** → **Fine-grained**.
   - Name: `github-deploy-research-assistant`.
   - Under **Repositories permissions**, search for and select the Space `<hf-user>/<space-name>`, and tick **Write access to contents/settings of selected repos**. Leave every other permission unticked.
   - Create the token and copy it (it is shown once).
2. In the GitHub repository go to **Settings → Secrets and variables → Actions**.
   - **Secrets** tab → **New repository secret**: name `HF_TOKEN`, value the token.
   - **Variables** tab → **New repository variable**: name `HF_SPACE_ID`, value `<hf-user>/<space-name>`.
3. First deploy: **Actions → Deploy backend → Run workflow** (branch `main`, after this task's PR reaches `main`). After that, every push to `main` that changes `backend/` deploys automatically.
4. In the Space, the **Logs** button (Build / Container) shows the image build, then the JSON startup logs. When the status badge says **Running**:
   - `<space-url>/api/v1/health` → `{"status":"ok","version":"0.1.0"}`
   - `<space-url>/api/v1/health/ready` → `{"status":"ready","checks":{"database":"ok"}}`

### Benchmark the Space's CPU (Phase 1)

The CPU benchmark can run once at startup and write its table to the Space logs. Requests are still served while it runs, but local inference may queue behind it.

1. In the Space: **Settings → Variables and secrets → New variable**: `RUN_BENCHMARK_ON_STARTUP` = `true`. The Space restarts.
2. To benchmark a branch that is not on `main` yet: GitHub **Actions → Deploy backend → Run workflow**, choose the branch under **Use workflow from**, then **Run workflow**. **This replaces what the Space is running (production)** until `main` is deployed again. The Space commit message names the branch.
3. **Logs → Container**: wait for `CPU benchmark started`, then `CPU benchmark results` with the table. The first line shows the CPU count and torch threads. If you see `CPU benchmark not run: fake provider configured for …` instead, a Space variable is overriding a provider (see step 3.3).
4. Copy the table into `docs/PROGRESS.md` → Measurements.
5. Delete the `RUN_BENCHMARK_ON_STARTUP` variable. If you deployed a branch, run **Deploy backend** on `main` again.

## 5. Vercel project

1. Go to <https://vercel.com/new>, sign in with GitHub, and **Import** the GitHub repository. Allow the Vercel GitHub app access to it.
2. On the configure screen:
   - **Root Directory:** `frontend` (click **Edit**). Framework preset **Next.js** is detected; keep the default build and install commands.
   - **Environment Variables:** `NEXT_PUBLIC_API_BASE_URL` = `<space-url>` (no trailing slash).
   - Click **Deploy**.
3. **Settings → Environments → Production → Branch Tracking**: the production branch is `main`. Vercel defaults it to the repository's default branch, which is `dev`, so change it here.
4. `frontend/vercel.json` cancels builds for every other branch, so there are no preview deployments. They would fail CORS against the prod Space anyway. Such builds show as **Canceled** by the Ignored Build Step; that is expected.
5. Node.js version: Vercel follows `"engines": {"node": ">=24"}` in `frontend/package.json` (24.x). Under **Settings → Build and Deployment → Node.js Version**, check that it says 24.x.
6. `NEXT_PUBLIC_API_BASE_URL` is inlined at build time. After changing it, open **Deployments → ⋮ → Redeploy** on the latest production deployment.
7. **Sign-in (Phase 3):** add `NEXT_PUBLIC_SUPABASE_URL` = `https://<prod-ref>.supabase.co` and `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` = the prod publishable key (**Project Settings → API Keys**), then redeploy (step 6). In the prod project, **Authentication → URL Configuration**: Site URL = `<vercel-url>`, and add `<vercel-url>/auth/callback` to **Redirect URLs** (the sign-up confirmation link lands there). For local development put the dev values in `frontend/.env.local` (see `frontend/.env.example`) and add `http://localhost:3000/auth/callback` to the dev project's Redirect URLs.

## 6. Connect frontend and backend (CORS)

1. Copy the production domain from Vercel (**Project → Domains**, e.g. `https://research-assistant.vercel.app`).
2. In the Space **Settings → Variables and secrets**, edit `CORS_ORIGINS` to `<vercel-url>`. Several origins can be given comma-separated, e.g. `https://research-assistant.vercel.app,http://localhost:3000`. The Space restarts by itself.

## 7. Verify the Phase 0 exit criteria

- [ ] Open `<vercel-url>`: the "Backend health" card shows `<space-url>`, an **ok** badge, and `version 0.1.0`. The browser DevTools console shows no CORS error.
- [ ] `<space-url>/api/v1/health/ready` → 200 with `"database":"ok"`.
- [ ] GitHub **Actions**: the latest `CI` run on `main` and the `Deploy backend` run are green.

## 8. Phase 1 release checklist

Do these in order. Work from `backend/`. Never paste a prod secret into chat or commit it.

1. **Prod Storage bucket:** create `documents` in the prod project as in "Supabase Storage bucket" above (private, 25 MB, `application/pdf`, no policies).
2. **Space secrets and variables** (**Settings → Variables and secrets**, step 3 table): secrets `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `CONTACT_EMAIL`; variable `SEARCH_PROVIDER` = `live`. Remove `RUN_BENCHMARK_ON_STARTUP` if it is still set.
3. **Prod JWT key type:** prod **Project Settings → JWT Keys** → the current signing key is **ES256** or **RS256** (HS256 tokens are rejected).
4. **Migrate prod**, with `DATABASE_URL` set for each command only (nothing is exported, so `backend/.env` stays the dev target):
   ```bash
   read -rs PROD_DB                                     # paste the prod URL; nothing is echoed
   DATABASE_URL="$PROD_DB" uv run alembic current       # → 0001
   DATABASE_URL="$PROD_DB" uv run alembic upgrade head  # runs 0002, 0003
   DATABASE_URL="$PROD_DB" uv run alembic current       # → 0003 (head)
   DATABASE_URL="$PROD_DB" uv run alembic check         # → No new upgrade operations detected.
   unset PROD_DB
   ```
   Prod **Table Editor**: workspaces, documents, workspace_documents, chunks, topic_profiles exist with RLS enabled.
5. **Release PR:** GitHub → **New pull request**, base `main` ← compare `dev`, title "Phase 1 release". Wait for `CI / backend`, `CI / frontend`, and `CI / migrations` to be green, then merge.
6. **Deploy:** the merge starts **Actions → Deploy backend** (run it by hand if it doesn't). Space **Logs → Container** shows the models loading and no startup error.
7. **Health checks:** `<space-url>/api/v1/health` → 200; `<space-url>/api/v1/health/ready` → 200 with `"database":"ok"`; the Vercel page still shows **ok**.
8. **Measure NFR-02 on the Space.** In prod **Authentication → Users → Add user** (Auto Confirm), a measurement user with no documents. Then:
   ```bash
   read -rs PW                                          # the measurement user's password
   export MEASURE_TOKEN=$(curl -s "https://<prod-ref>.supabase.co/auth/v1/token?grant_type=password" \
     -H "apikey: <prod publishable key>" -H "Content-Type: application/json" \
     -d "{\"email\":\"<measurement-user-email>\",\"password\":\"$PW\"}" \
     | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
   unset PW
   uv run python -m scripts.measure_ingestion --base-url <space-url> \
     --pdf scripts/data/embedding_comparison/2303.11051.pdf --server-hardware "HF Spaces CPU basic"
   unset MEASURE_TOKEN
   ```
   The script prints the time to `ready` and the stage timings, deletes its workspace, and writes `docs/experiments/*_measure_ingestion_*.json`. Commit that file on a `p1/…` branch and record the number in `docs/PROGRESS.md` (NFR-02: within 90 s).
9. **Tag:** on an up-to-date `main`: `git tag phase-1-done && git push origin phase-1-done`.

## 9. Phase 2 release checklist

Do these in order. Work from `backend/`. Never paste a prod secret into chat or commit it. ★ needs someone with prod access.

1. ★ **Keys:** create **demo-only** Groq and Gemini API keys (D-070; never used for development, tests, or evaluations) and a LangSmith API key.
2. ★ **Task PR:** merge the `p2/phase-2-done` PR into `dev` once CI is green.
3. ★ **Migrate prod and create the checkpoint tables** (before the release merge):
   ```bash
   read -rs PROD_DB                                                  # paste the prod URL; nothing is echoed
   DATABASE_URL="$PROD_DB" uv run alembic current                    # → 0003
   DATABASE_URL="$PROD_DB" uv run alembic upgrade head               # runs 0004, 0005
   DATABASE_URL="$PROD_DB" uv run alembic current                    # → 0005 (head)
   DATABASE_URL="$PROD_DB" uv run alembic check                      # → No new upgrade operations detected.
   DATABASE_URL="$PROD_DB" uv run python -m scripts.setup_checkpointer
   # → Checkpoint tables (RLS enabled): checkpoint_blobs, checkpoint_migrations, checkpoint_writes, checkpoints
   ```
   Keep `PROD_DB` for step 9. Prod **Table Editor**: conversations, messages, claims, evidence, citations, approvals, agent_runs, eval_runs, eval_results exist with RLS enabled.
4. ★ **Space secrets and variables** (step 3 table): secrets `GROQ_API_KEY`, `GEMINI_API_KEY` (demo keys), `LANGSMITH_API_KEY`; variables `LANGSMITH_TRACING` = `true`, `LANGSMITH_PROJECT` = `research-assistant-prod`, and `RUN_BENCHMARK_ON_STARTUP` = `true` (this deploy only, for the NLI latency on the Space). The Space restarts on the old image; that is fine.
5. ★ **Release PR:** GitHub → **New pull request**, base `main` ← compare `dev`, title "Phase 2 release". Wait for `CI / backend`, `CI / frontend`, `CI / migrations`, and `CI / docker-build` to be green, then merge.
6. **Deploy:** the merge starts **Actions → Deploy backend**. Space **Logs → Container**: the models load (the NLI model is `cross-encoder/nli-deberta-v3-xsmall`), no startup error, then `CPU benchmark results` with its table.
7. **Health checks:** `<space-url>/api/v1/health` → 200; `<space-url>/api/v1/health/ready` → 200 with `"database":"ok"`; the Vercel page still shows **ok**.
8. **Smoke test** with the prod measurement user (§8 step 8 shows how to get `MEASURE_TOKEN`). In `<space-url>/docs`, **Authorize**, create a workspace, upload `scripts/data/embedding_comparison/2303.11051.pdf`, and poll `GET /documents/{id}` to `ready`. Create a conversation, then:
   ```bash
   curl -N -X POST <space-url>/api/v1/conversations/<id>/messages -H "Authorization: Bearer $MEASURE_TOKEN" \
     -H 'Content-Type: application/json' -d '{"content": "How does the lactide-to-glycolide ratio affect how fast PLGA degrades?"}'
   ```
   It should stream `status` events, then `claims`, `citations`, and `done`. Ask something the paper does not cover (e.g. "What fatigue life did the scaffolds reach under cyclic compression?"): `approval_required`; then `POST /runs/<run_id>/resume` with `{"decision": "corpus_only"}` ends with an abstention. The runs appear in LangSmith under `research-assistant-prod`. Delete the workspace.
9. **Measure NFR-01 and NFR-13** (12 questions, about 45 LLM calls on the demo keys, ~10–15 min; it ingests both benchmark corpora first):
   ```bash
   DATABASE_URL="$PROD_DB" uv run python -m scripts.measure_qa --base-url <space-url> \
     --server-hardware "HF Spaces CPU basic"
   unset PROD_DB MEASURE_TOKEN
   ```
   `DATABASE_URL` must be prod: the LLM call counts are read from its `agent_runs`. The script prints a table and the NFR verdicts, deletes its workspaces, and writes `docs/experiments/*_measure_qa_*.json`. Copy the CPU benchmark table from the Space logs, then delete the `RUN_BENCHMARK_ON_STARTUP` variable.
10. **Record the results:** on a `p2/phase-2-results` branch, commit the JSON and update `docs/PROGRESS.md` (Phase 2 exit criteria, Measurements, Known issues). Open a PR into `dev`. After it merges, open a docs-only `dev` → `main` PR ("Phase 2 results"); it does not touch `backend/`, so nothing is redeployed.
11. ★ **Tag:** on an up-to-date `main`: `git tag phase-2-done && git push origin phase-2-done`.

## 10. Phase 3 release checklist

Collected while Phase 3 tasks land; each task adds its items here. ★ needs someone with prod access.

1. ★ **Migrate prod** `0005 → 0006` (task #1a, `messages.created_at` default), same commands as §9 step 3 (`alembic current` → 0005, `upgrade head`, `current` → 0006, `check`).
2. ★ **Sign-in (task #3):** Vercel env vars `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` (prod values); prod Supabase **Authentication → URL Configuration**: Site URL = `<vercel-url>`, Redirect URLs include `<vercel-url>/auth/callback`; confirm email confirmation is on and sign-up is off (§5 step 7).
3. ★ **E2E secrets (task #7; added 2026-10-08):** GitHub secrets `E2E_BASE_URL`, `E2E_EMAIL`, `E2E_PASSWORD`; the E2E user is created in the prod dashboard with **Auto Confirm User**. Run it from **Actions → E2E → Run workflow**; it signs in on `E2E_BASE_URL`, uploads a paper, asks one question (a few demo-key LLM calls), and deletes its workspace.
4. ★ **Release PR** `dev` → `main` once CI is green (interim release before task #7, D-076: no `phase-3-done` tag yet), then the deploy and health checks as in §9 steps 5–7, and a browser smoke test: sign in with a team account at `<vercel-url>/login`, see `/workspaces`, sign out.
5. **Re-measure ingestion (NFR-02) on the Space** after the deploy: the 28.8 s figure predates Phase 2's DOI lookup and LLM metadata step. Run `scripts.measure_ingestion` against `<space-url>` (as in §8) and record the result in `docs/PROGRESS.md`.

## 11. Discover release notes (D-077; added 2026-10-15)

Nothing here has been deployed. Items for the next release that includes `feat/research-discovery`. ★ needs someone with prod access.

1. **No new secrets or services.** Discover uses the existing `SEARCH_PROVIDER=live` and `CONTACT_EMAIL` (step 3 table). With `SEARCH_PROVIDER=fake`, search returns the fake catalog, all marked link only.
2. **Optional variables** (defaults are fine): `DISCOVER_MAX_RESULTS` (10), `ARXIV_REQUESTS_PER_MINUTE` (20), `DISCOVER_PDF_CHECK_SECONDS` (4), `DISCOVER_TIMEOUT_SECONDS` (15), `IMPORT_MAX_REDIRECTS` (3), `IMPORT_TIMEOUT_SECONDS` (30), `IMPORT_DOWNLOAD_DEADLINE_SECONDS` (90), `IMPORT_BUDGET_SECONDS` (120). See `backend/.env.example`.
7. **OpenAlex API key (recommended, D-080).** Without a key, OpenAlex allows 1,000 credits a day per IP address and a search costs 10, so about 100 Discover searches a day for everyone using the Space; after that, Discover shows "OpenAlex's free daily search limit has been reached" and returns arXiv results only. A free key gives 10× that ([OpenAlex docs](https://help.openalex.org/how-to-use-the-api/rate-limits-and-authentication), checked 2026-10-15).
   - ★ Create an account at openalex.org and copy the key from openalex.org/settings/api.
   - ★ Add it as the Space **secret** `OPENALEX_API_KEY` (and to `backend/.env` for local development). It stays on the backend; nothing is needed on Vercel.
8. **Dev environment:** run `uv sync --all-groups` (not plain `uv sync`), or the `eval` group (Ragas) is removed from the virtualenv.
3. **New backend dependency:** `defusedxml` (pure Python, parses arXiv's Atom feed). `uv sync` installs it; the Space image picks it up from `uv.lock` on rebuild.
4. **Outbound network:** the Space must reach `export.arxiv.org`, `arxiv.org`, `api.openalex.org`, and any open-access PDF host over HTTPS/HTTP on ports 443/80. Hugging Face Spaces allow this by default. Downloads to private, loopback or link-local addresses are refused by design.
5. **No migration.** `documents.source` already allows `import` and `source_url` exists.
6. **Frontend:** no new env vars. The Discover page is at `/discover` and requires sign-in, like `/workspaces`.

## Free-tier behaviour and waking things up before a demo

- **Hugging Face Space (CPU basic):** sleeps after 48 hours without traffic. The first request then gets a "Space is sleeping/starting" page until the container starts (about 1–2 minutes). Before a demo, open `<space-url>/api/v1/health` and wait for JSON.
- **Supabase free project:** paused after a week without activity. Resume it under **Project → Restore/Resume** in the dashboard (a few minutes), then check `/api/v1/health/ready`.
- **Vercel:** no sleep.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Deploy job fails with 401/403 | `HF_TOKEN` is missing, expired, or not granted write access to this Space |
| Deploy job fails with 404 / "Repository not found" | `HF_SPACE_ID` is wrong (must be `<hf-user>/<space-name>`) |
| Space build fails at `uv sync --locked` | `backend/uv.lock` is out of date; run `uv lock` and commit (CI fails on this too) |
| Card shows "unreachable" (`Failed to fetch`) | The Space is asleep or building, `CORS_ORIGINS` doesn't match the Vercel origin exactly (scheme, no trailing slash), or `NEXT_PUBLIC_API_BASE_URL` was changed without a redeploy |
| `/health/ready` → 503 `not_configured` | `DATABASE_URL` secret is not set on the Space |
| Space crashes at startup: "SUPABASE_URL is required when ENVIRONMENT=prod" | `SUPABASE_URL` is not set on the Space |
| Space crashes at startup: "GROQ_API_KEY is required…" or "GEMINI_API_KEY is required…" | The LLM key secret is not set on the Space (D-071) |
| Every question ends with an `error` event, or the logs show missing `agent_runs` or `langgraph` checkpoint tables | Prod is not at migration 0005, or `scripts.setup_checkpointer` was not run on prod (§9 step 3) |
| Every authenticated request → 401 | Token from a different Supabase project than `SUPABASE_URL`, or the project still signs with the legacy HS256 secret (see the backend log line "Access token rejected: …") |
| `/health/ready` → 503 `unavailable` | Wrong password or URL encoding, direct/transaction connection string instead of the session pooler, or the Supabase project is paused |
