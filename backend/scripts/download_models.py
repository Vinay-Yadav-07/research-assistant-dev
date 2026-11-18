"""Download the configured local models into the Hugging Face cache (`HF_HOME`).

The Docker build runs this so the container starts without network downloads (SRS §15.3). It
imports only `app.core.config`, so the image's model layer is rebuilt only when that file
changes. Locally: `uv run python -m scripts.download_models`.
"""

import time

from app.core.config import get_settings


def main() -> None:
    """Load each configured model once, which downloads only the files it needs."""
    from sentence_transformers import CrossEncoder, SentenceTransformer

    settings = get_settings()
    started = time.perf_counter()
    SentenceTransformer(settings.embedding_model, device="cpu")
    CrossEncoder(settings.reranker_model, device="cpu")
    CrossEncoder(settings.nli_model, device="cpu")
    models = ", ".join([settings.embedding_model, settings.reranker_model, settings.nli_model])
    print(f"Downloaded {models} in {time.perf_counter() - started:.1f} s")


if __name__ == "__main__":
    main()
