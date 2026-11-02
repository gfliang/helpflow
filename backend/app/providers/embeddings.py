"""Embedding providers.

The production path uses a local BGE Chinese model through ``fastembed`` so no
external embedding API is required. ``fastembed`` runs ONNX Runtime and works on
Intel macOS, where the PyTorch wheels required by ``sentence-transformers`` are
not published.

If the model cannot be loaded (no cache and no network, or a constrained CI
machine), ``auto`` degrades to a deterministic 512-dimension hashed embedding so
the API stays available. The fallback is logged and exposed through ``name`` so
evaluation results never misrepresent it as a real semantic model.
"""

import hashlib
import logging
import math
import re
import threading
from typing import Protocol

from app.core.config import settings

logger = logging.getLogger(__name__)

TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]+|[a-zA-Z0-9_]+")


def tokenize(text: str) -> list[str]:
    """Split Latin words and CJK bigrams so short Chinese queries stay distinguishable."""
    tokens: list[str] = []
    for match in TOKEN_PATTERN.findall(text.lower()):
        if "\u4e00" <= match[0] <= "\u9fff":
            tokens.extend(match[index : index + 2] for index in range(max(1, len(match) - 1)))
        else:
            tokens.append(match)
    return tokens


def _normalize(vector: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    return [value / magnitude for value in vector] if magnitude else vector


class EmbeddingProvider(Protocol):
    name: str
    dimensions: int

    def embed(self, text: str) -> list[float]: ...

    def embed_many(self, texts: list[str]) -> list[list[float]]: ...


class LocalHashEmbeddingProvider:
    """Deterministic fallback used for tests and offline environments."""

    name = "hash"

    def __init__(self, dimensions: int | None = None) -> None:
        self.dimensions = dimensions or settings.embedding_dimensions

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[bucket] += 1.0 if digest[4] % 2 else -1.0
        return _normalize(vector)

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


class BGEEmbeddingProvider:
    """Local BGE embedding model loaded lazily through ONNX Runtime."""

    name = "bge"

    def __init__(self) -> None:
        self.dimensions = settings.embedding_dimensions
        self._model = None
        self._lock = threading.RLock()

    def _ensure_model(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from fastembed import TextEmbedding

                    cache_dir = settings.embedding_cache_dir.strip() or None
                    self._model = TextEmbedding(
                        model_name=settings.embedding_model,
                        cache_dir=cache_dir,
                    )
        return self._model

    def _encode(self, texts: list[str]) -> list[list[float]]:
        model = self._ensure_model()
        vectors = [
            _normalize([float(value) for value in vector])
            for vector in model.embed(texts, batch_size=settings.embedding_batch_size)
        ]
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise RuntimeError(
                    f"Embedding dimension mismatch: model returned {len(vector)}, "
                    f"expected {self.dimensions}"
                )
        return vectors

    def embed(self, text: str) -> list[float]:
        with self._lock:
            return self._encode([text])[0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with self._lock:
            return self._encode(texts)


class LazyEmbeddingProvider:
    """Resolve the configured backend once, on first use, never at import time."""

    def __init__(self) -> None:
        self._impl: EmbeddingProvider | None = None
        self._lock = threading.Lock()

    def _resolve(self) -> EmbeddingProvider:
        if self._impl is not None:
            return self._impl
        with self._lock:
            if self._impl is not None:
                return self._impl
            backend = settings.embedding_backend.strip().lower()
            if backend == "hash":
                self._impl = LocalHashEmbeddingProvider()
            elif backend == "bge":
                self._impl = BGEEmbeddingProvider()
            else:
                try:
                    self._impl = BGEEmbeddingProvider()
                    # Force a load so a missing model is detected before the first query.
                    self._impl.embed("HelpFlow 向量模型自检")
                except Exception as error:  # noqa: BLE001 - fallback is intentional
                    logger.warning(
                        "BGE embedding unavailable (%s); falling back to deterministic hash "
                        "vectors. Set EMBEDDING_BACKEND=bge to fail fast instead.",
                        error,
                    )
                    self._impl = LocalHashEmbeddingProvider()
            return self._impl

    @property
    def name(self) -> str:
        return self._resolve().name

    @property
    def dimensions(self) -> int:
        return self._resolve().dimensions

    def embed(self, text: str) -> list[float]:
        return self._resolve().embed(text)

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return self._resolve().embed_many(texts)


embedding_provider = LazyEmbeddingProvider()
