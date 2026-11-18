---
title: Research Assistant API
emoji: 📚
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Research Assistant API

FastAPI backend of the Evidence-Grounded AI Research Assistant. The YAML header configures the
Hugging Face Docker Space; `backend/` is deployed as the Space root on every push to `main`.

- Health: `/api/v1/health`, readiness: `/api/v1/health/ready`, API docs: `/docs`.
- Setup and secrets: `docs/SETUP.md` in the main repository.
