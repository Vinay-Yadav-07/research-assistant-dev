# Multi-Agent RAG-Based AI Research Assistant
> **Knowledge-Boundary Enforcement & Claim-Level Verification for Scientific Literature Analysis**

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.142+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16.3-black?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev/)
[![LangGraph](https://img.shields.io/badge/LangGraph-State_Orchestration-FF6F00?style=flat-square&logo=langchain&logoColor=white)](https://www.langchain.com/langgraph)
[![Supabase](https://img.shields.io/badge/Supabase-PostgreSQL_%2B_pgvector-3ECF8E?style=flat-square&logo=supabase&logoColor=white)](https://supabase.com/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-v4-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white)](https://tailwindcss.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](LICENSE)

---

## Overview

Large Language Models (LLMs) generate fluent responses, but in academic and scientific research they present critical risks: **hallucination**, **parametric leakage** (blending pretraining memories into domain papers), **unverifiable citations**, and an **inability to decline answering** when sources lack evidence.

The **Evidence-Grounded AI Research Assistant** is a full-stack, agentic research platform engineered around strict **knowledge-boundary enforcement**. Responses originate exclusively from a user-defined scientific corpus. Every factual statement is isolated into an atomic claim, verified through a two-phase verification process (local CPU Natural Language Inference + batched LLM judge), and linked directly to its exact page and passage in the source PDF. When evidence is insufficient, the system abstains honestly or halts for explicit human-in-the-loop permission before accessing outside knowledge.

---

## Core Capabilities

- **Strict Knowledge Boundary:** Answers originate only from the user's workspace documents by default. Cross-workspace and external knowledge leakage is prevented in SQL queries with PostgreSQL Row-Level Security (RLS).
- **Section-Aware Ingestion:** Validates PDFs up to 25 MB, rejects scanned documents lacking text layers, extracts page-by-page Markdown via `PyMuPDF4LLM`, strips repeated headers/footers, resolves DOIs via Crossref and OpenAlex, and segments text into section-aware chunks (350–450 tokens).
- **Workspace Compatibility Gate:** Evaluates incoming papers against the workspace semantic centroid using dense embeddings; warns the user if cosine similarity is below `0.83`.
- **Hybrid Search & Cross-Encoder Reranking:**
  - Dense vector similarity (`BAAI/bge-small-en-v1.5`, 384 dimensions)
  - PostgreSQL full-text search (`tsvector` cover density)
  - Reciprocal Rank Fusion (RRF, $k=60$) merging candidates down to top 20
  - Cross-encoder reranking (`ms-marco-MiniLM-L-6-v2`) selecting top 8 evidence passages
- **Calibrated Sufficiency Gate:** Automatically accepts queries with a reranker score $\ge 0.97$; borderline queries are screened via a batched LLM check to prevent false responses.
- **Human-in-the-Loop (HITL) Approval Gate:** When evidence is incomplete, LangGraph pauses execution (`interrupt()`), checkpoints state in PostgreSQL, and prompts the user to either maintain corpus-only boundaries (abstaining) or grant one-time general knowledge permission.
- **Two-Phase Claim Verification Loop:**
  - *Phase 1 (Local CPU NLI):* `nli-deberta-v3-xsmall` cross-encoder evaluates claims against 120-word windows of cited passages (entailment $\ge 0.9$, contradiction $< 0.5$).
  - *Phase 2 (LLM Judge):* Borderline claims are evaluated in a batched LLM judge pass.
  - *Revision Engine:* Unsupported claims trigger up to 2 automated revision rounds with the Synthesis Agent; unbacked claims are excised.
- **In-PDF Highlighted Source Viewer:** Clicking on any citation chip immediately navigates to the exact page of the PDF in-browser and highlights the verbatim quote.
- **Multi-Paper Comparative Analysis:**
  - 6-attribute comparison matrix (Objective, Methodology, Materials, Setup, Findings, Limitations)
  - Thematic synthesis across related documents
  - NLI-driven contradiction screening between findings
  - Corpus gap discovery highlighting unaddressed research areas
- **Live Paper Discovery:** Direct integration with arXiv and OpenAlex APIs to search literature, inspect open-access PDF availability, and import papers into workspaces in one click.
- **Semantic Knowledge Graph (Experimental):** Extracts research entities (`concept`, `method`, `dataset`, `metric`, `task`, `tool`, `finding`) and grounded relationships backed by exact textual passages.

---

## Architecture & Workflow

### 1. Architectural Layers

| Layer | Component | Description |
|---|---|---|
| **Client UI** | Next.js 16 (App Router) | React 19, TypeScript, Tailwind CSS v4, shadcn/ui, react-pdf, React Flow |
| **API Layer** | FastAPI (Python 3.11) | Asynchronous REST and Server-Sent Events (SSE) streaming with JWT authentication |
| **Agent Orchestration** | LangGraph State Machine | Multi-agent execution graph with PostgreSQL state checkpointing (`AsyncPostgresSaver`) |
| **Database & Vector Store**| Supabase PostgreSQL | `pgvector` exact cosine distance, Full-Text Search indices, Row-Level Security (RLS) |
| **File Storage** | Supabase Private Storage | Secured PDF document storage with time-limited signed URLs (300s TTL) |
| **Local CPU Models** | PyTorch / Transformers | `bge-small-en-v1.5` (embeddings), `MiniLM-L-6-v2` (reranker), `nli-deberta-v3-xsmall` (NLI) |
| **Cloud LLM Providers** | Groq & Google Gemini | Fast tier (`gpt-oss-20b`) for query analysis; Strong tier (`Gemini 3.5 Flash-Lite`) for synthesis & judging |

### 2. End-to-End Pipeline

1. **Query Analysis (A1):** The user's prompt is parsed into structured intent, identifying sub-questions, keywords, dependencies, and targeted papers.
2. **Hybrid Retrieval (S2):** Dense vector search and PostgreSQL lexical search run concurrently within the workspace boundaries, merged using Reciprocal Rank Fusion (RRF) and rescored by a local cross-encoder.
3. **Sufficiency Evaluation (S3 & S4):** Reranker scores and batched sufficiency checks determine if evidence is sufficient. Missing evidence triggers an interactive approval card or an honest abstention.
4. **Grounded Synthesis (A2):** The synthesis agent drafts responses citing labeled evidence spans (`E1`, `E2`, etc.) in delimited data blocks.
5. **Two-Stage Verification (A3):**
   - Each cited sentence is scored against source passage windows using the local NLI model.
   - Ambiguous claims are checked by the strong LLM judge.
   - Unsupported assertions are sent back for revision (up to 2 loops); failing statements are excised.
6. **Citation Grounding (S5):** Labels are mapped to document metadata, page numbers, and exact text quotes for interactive rendering in the web interface.

---

## Technology Stack

```
Frontend:            Next.js 16  |  React 19  |  TypeScript  |  Tailwind CSS v4  |  shadcn/ui
Backend API:         FastAPI  |  Python 3.11  |  Pydantic v2  |  SQLAlchemy 2.0  |  Alembic
Orchestration:       LangGraph  |  LangChain  |  AsyncPostgresSaver
Database & Auth:     PostgreSQL 17  |  pgvector  |  Supabase Auth (JWKS)  |  Supabase Storage
Local Inference:     sentence-transformers  |  PyTorch (CPU-optimized)
Cloud LLMs:          Groq API  |  Google Gemini API  |  LangSmith Tracing
External Services:   arXiv API  |  OpenAlex API  |  Crossref API
Testing & Quality:   pytest  |  Playwright E2E  |  Ragas  |  Ruff  |  Mypy
```

---

## Repository Structure

```
research-assistant-dev/
├── backend/
│   ├── alembic/                 # Database migrations (0001 through 0008)
│   ├── app/
│   │   ├── agents/              # LangGraph agents (Query Analyzer, Synthesis, Verification, Analysis)
│   │   ├── api/                 # FastAPI REST routes and Server-Sent Event handlers
│   │   ├── core/                # App configuration, security, errors, database engines
│   │   ├── graphs/              # LangGraph workflow definitions and checkpointing
│   │   ├── models/              # SQLAlchemy database models
│   │   ├── prompts/             # Versioned prompt templates for agents and services
│   │   ├── providers/           # Model abstractions (Groq, Gemini, local models, scholarly search, fakes)
│   │   ├── repositories/        # Database access layer with workspace and user scoping
│   │   └── services/            # Deterministic logic (ingestion, hybrid retrieval, verification, citations)
│   ├── eval/                    # Benchmark harness and evaluation datasets
│   ├── tests/                   # Extensive test suites (>900 unit and integration tests)
│   ├── Dockerfile               # Container definition for CPU-based cloud deployment
│   └── pyproject.toml           # Python dependencies and tool configs (uv-managed)
├── frontend/
│   ├── src/
│   │   ├── app/                 # Next.js App Router (workspaces, chat, analysis, discover, graph)
│   │   ├── components/          # Reusable UI components (PDF viewer, chat, landing, analysis tables)
│   │   └── lib/                 # Type-safe API client, Supabase utilities, helpers
│   ├── package.json             # Node dependencies and build scripts
│   └── tsconfig.json            # TypeScript strict mode configuration
├── docs/                        # Complete technical documentation, specifications, and architecture records
│   ├── SRS.md                   # Software Requirements Specification
│   ├── PROGRESS.md              # Milestone tracking and verified metrics
│   ├── DECISIONS.md             # Architecture Decision Records (D-001 through D-087)
│   ├── DESIGN.md                # Design system, styling rules, and accessibility standards
│   └── SETUP.md                 # Full deployment and environment setup instructions
├── .github/
│   └── workflows/               # CI/CD pipelines (test, lint, typecheck, migrations, deploy)
└── README.md                    # Project documentation
```

---

## Getting Started

### Prerequisites

- **Python 3.11** (recommended package manager: [`uv`](https://github.com/astral-sh/uv))
- **Node.js $\ge$ 20** and **npm $\ge$ 10**
- A **Supabase** account (Free tier includes PostgreSQL with pgvector, Auth, and Storage)
- Free API keys from [Groq](https://console.groq.com) and [Google AI Studio](https://aistudio.google.com/) *(optional for offline testing; mock providers run out of the box)*

---

### Backend Setup

1. Change directory to `backend/`:
   ```bash
   cd backend
   ```

2. Copy the sample environment file:
   ```bash
   cp .env.example .env
   ```
   *Note: Defaults use mock providers (`LLM_FAST_PROVIDER=fake`, `LLM_STRONG_PROVIDER=fake`), allowing all tests and the server to run locally without external API keys.*

3. To connect live services, supply your credentials in `.env`:
   ```dotenv
   ENVIRONMENT=local
   DATABASE_URL=postgresql+psycopg://postgres:<password>@<db-host>:5432/postgres
   SUPABASE_URL=https://<project-ref>.supabase.co
   SUPABASE_SECRET_KEY=sb_secret_...
   GROQ_API_KEY=gsk_...
   GEMINI_API_KEY=AIzaSy...
   LLM_FAST_PROVIDER=groq
   LLM_STRONG_PROVIDER=gemini
   ```

4. Install dependencies:
   ```bash
   uv sync --group dev --group eval
   ```

5. Apply database migrations:
   ```bash
   uv run alembic upgrade head
   ```

6. Start the API development server:
   ```bash
   uv run uvicorn app.main:app --reload --port 8000
   ```
   Interactive API docs are available at `http://localhost:8000/docs`.

---

### Frontend Setup

1. Change directory to `frontend/`:
   ```bash
   cd frontend
   ```

2. Configure environment variables:
   ```bash
   cp .env.example .env.local
   ```
   Configure your URLs:
   ```dotenv
   NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
   NEXT_PUBLIC_SUPABASE_URL=https://<project-ref>.supabase.co
   NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=eyJ...
   ```

3. Install packages:
   ```bash
   npm install
   ```

4. Launch the Next.js development server:
   ```bash
   npm run dev
   ```
   Access the web application at `http://localhost:3000`.

---

### Testing & Verification

- **Backend Unit Tests (>900 tests via offline mocks):**
  ```bash
  cd backend
  uv run pytest
  ```
- **Code Formatting & Type Checking:**
  ```bash
  cd backend
  uv run ruff check .
  uv run ruff format --check .
  uv run mypy app
  ```
- **Frontend Unit Tests:**
  ```bash
  cd frontend
  npm test
  ```
- **Frontend Lint & Build:**
  ```bash
  cd frontend
  npm run lint
  npm run build
  ```

---

## Experimental Benchmarks

The system was evaluated against baseline conditions on a benchmark comprising 54 scientific test questions:
- **C1 (LLM-Only):** Direct model generation with zero retrieval context.
- **C2 (Conventional RAG):** Dense top-8 passage retrieval with a standard "answer from context" prompt.
- **Proposed System:** Hybrid retrieval + RRF + Cross-encoder reranking + Sufficiency gate + Approval gate + Two-phase claim verification + In-PDF citation grounding.

| Evaluation Metric | C1 (LLM-Only) | C2 (Conventional RAG) | Full Deployed System |
|---|:---:|:---:|:---:|
| **Abstention Accuracy (Unanswerable Questions)** | 80.0% (8/10) | **100.0%** (10/10) | **100.0%** (via S3/S4 gates) |
| **False Abstention Rate (Answerable Questions)** | 29.5% (13/44) | 13.6% (6/44) | **Significantly Reduced** |
| **Page-Level Recall@8** | N/A | 87.9% | **94.0% – 100.0%** |
| **MRR (Mean Reciprocal Rank)** | N/A | 0.671 | **0.730 – 0.820** |
| **Ragas Faithfulness** | N/A | 95.7% | **100% verified claims grounded** |
| **First Response Event (SSE)** | ~1.7 s | ~2.3 s | **0.39 s** |
| **Median End-to-End Latency** | ~1.7 s | ~2.3 s | **6.77 s** (on basic CPU instance) |
| **Average LLM Calls / Question** | 1.0 | 1.0 | **3.67** |

---

## Project Team & Academic Credits

This project was developed as a Final Year B.Tech Major Project in the **Department of Information Technology** at **Vidyalankar Institute of Technology (VIT)**, Mumbai (Affiliated to the University of Mumbai).

- **Project Guide:** Dr. Rugved Deolekar
- **Group Members:**
  - **Vinay Yadav** (23101B0020)
  - **Tejas Sonawane** (23101B0016)
  - **Punit Jadhav** (23101B0064)
  - **Shreyas Desai** (23101B0074)

**Research Publications & Exhibitions:**
- *Conference Paper:* "Multi-Agent RAG-Based AI Research Assistant with Knowledge-Boundary Enforcement and Claim-Level Verification for Automated Literature Analysis" (Submitted to ACCT).
- *Project Exhibition:* Exhibited at *Navonmesh 2026*, Department of Information Technology, VIT Mumbai.

---

## License

This project is licensed under the [MIT License](LICENSE).
