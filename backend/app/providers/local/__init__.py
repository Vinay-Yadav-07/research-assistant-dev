"""Local sentence-transformers models (embedding, reranker, NLI) run on CPU in worker threads.

`sentence_transformers` and `torch` are imported only when weights load, so building these
providers stays cheap (D-035).
"""

from app.providers.local.embedding import SentenceTransformerEmbedder
from app.providers.local.nli import CrossEncoderNLI
from app.providers.local.reranker import CrossEncoderReranker
from app.providers.local.runtime import LocalInference, LocalModel, cached_hidden_size

__all__ = [
    "CrossEncoderNLI",
    "CrossEncoderReranker",
    "LocalInference",
    "LocalModel",
    "SentenceTransformerEmbedder",
    "cached_hidden_size",
]
