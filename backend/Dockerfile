# Backend image for the Hugging Face Docker Space (SRS §15.3).
# The Space root is backend/ (uploaded by .github/workflows/deploy-backend.yml).
FROM python:3.11.16-slim-trixie

# Must equal [tool.uv] required-version in pyproject.toml (checked by a unit test).
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1

WORKDIR /app

# Dependencies first so code changes reuse this layer. --locked fails on a stale uv.lock.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

# Spaces run the container as UID 1000. It owns the model cache.
RUN useradd --create-home --uid 1000 user && mkdir /opt/hf && chown 1000 /opt/hf
USER 1000

# Production defaults; secrets (DATABASE_URL, CORS_ORIGINS) come from the Space settings.
ENV PATH="/app/.venv/bin:$PATH" \
    HF_HOME=/opt/hf \
    ENVIRONMENT=prod \
    LOG_JSON=true \
    EMBEDDING_PROVIDER=sentence_transformers \
    RERANKER_PROVIDER=cross_encoder \
    NLI_PROVIDER=cross_encoder \
    PRELOAD_MODELS=true

# Bake the model weights into the image (SRS §15.3). This layer depends only on the settings
# module, so ordinary code changes reuse it instead of downloading ~2 GB again.
COPY app/__init__.py ./app/
COPY app/core/__init__.py app/core/config.py ./app/core/
COPY scripts/__init__.py scripts/download_models.py ./scripts/
# Space secrets are not available at build time, so prod validation (SUPABASE_URL etc.) would
# fail here; this one command runs as local. The container still runs as prod.
# CI sets DOWNLOAD_MODELS=false to skip the ~2.2 GB download and only load the settings.
ARG DOWNLOAD_MODELS=true
RUN if [ "$DOWNLOAD_MODELS" = "true" ]; then \
        ENVIRONMENT=local python -m scripts.download_models; \
    else \
        ENVIRONMENT=local python -c "from app.core.config import get_settings; get_settings()"; \
    fi

# No network model downloads at runtime. The real PDF parser and the hosted LLMs are set here,
# after the model layer, so changing them does not invalidate the baked weights. The LLM keys
# are Space secrets; without them the app refuses to start instead of answering with the fake.
ENV HF_HUB_OFFLINE=1 \
    PARSER_PROVIDER=pymupdf4llm \
    LLM_FAST_PROVIDER=groq \
    LLM_STRONG_PROVIDER=gemini

COPY app ./app
# Benchmarks run inside the container too: `python -m scripts.bench_cpu`.
COPY scripts ./scripts

# Must equal app_port in README.md (checked by a unit test).
EXPOSE 7860

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--proxy-headers", "--forwarded-allow-ips", "*"]
