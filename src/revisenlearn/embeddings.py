"""Local embeddings (spec §2, §7.2).

`fastembed` with `BAAI/bge-small-en-v1.5` — ONNX, ~130MB, no PyTorch. Runs
locally, so concept identity and semantic search never depend on the network
(spec §16).

The model is loaded lazily and once: constructing a `TextEmbedding` reads the
ONNX file off disk, which is far too slow to do per call.
"""

from __future__ import annotations

import logging
import threading
from typing import Protocol, Sequence

import numpy as np

log = logging.getLogger(__name__)

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIM = 384
#: Stored little-endian float32 so a vector written on one machine reads back
#: identically on another.
DTYPE = np.dtype("<f4")


class Embedder(Protocol):
    """Swappable so tests can run without loading a 130MB model."""

    model_name: str
    dim: int

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Return an ``(n, dim)`` float32 array of L2-normalised vectors."""
        ...


class FastEmbedEmbedder:
    """The real thing."""

    model_name = MODEL_NAME
    dim = DIM

    def __init__(self) -> None:
        self._model = None
        self._lock = threading.Lock()

    def _ensure(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from fastembed import TextEmbedding

                    log.info("Loading embedding model %s", MODEL_NAME)
                    self._model = TextEmbedding(model_name=MODEL_NAME)
        return self._model

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        texts = list(texts)
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        vectors = np.array(list(self._ensure().embed(texts)), dtype=np.float32)
        return l2_normalise(vectors)


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = FastEmbedEmbedder()
    return _embedder


def set_embedder(embedder: Embedder | None) -> None:
    """Override the embedder. Tests use this to avoid the model download; the
    application never calls it."""
    global _embedder
    _embedder = embedder


# --------------------------------------------------------------------------
# Vector helpers
# --------------------------------------------------------------------------

def l2_normalise(vectors: np.ndarray) -> np.ndarray:
    """Unit-length rows, so cosine similarity is a plain dot product."""
    vectors = np.asarray(vectors, dtype=np.float32)
    if vectors.ndim == 1:
        vectors = vectors.reshape(1, -1)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    # A zero vector has no direction; leave it alone rather than dividing by 0.
    norms[norms == 0] = 1.0
    return (vectors / norms).astype(np.float32)


def to_blob(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=DTYPE).reshape(-1).tobytes()


def from_blob(blob: bytes, dim: int = DIM) -> np.ndarray:
    vector = np.frombuffer(blob, dtype=DTYPE)
    if vector.size != dim:
        raise ValueError(f"Expected {dim} floats, got {vector.size}")
    return vector.astype(np.float32)


def cosine_against(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Cosine similarity of one unit vector against a matrix of unit vectors.

    Brute-force numpy over every concept in the subject is correct at this
    scale; spec §7.2 is explicit that no vector index should be added.
    """
    if matrix.size == 0:
        return np.zeros((0,), dtype=np.float32)
    query = l2_normalise(query)[0]
    return (l2_normalise(matrix) @ query).astype(np.float32)


def embed_concept_text(name: str, definition: str | None) -> str:
    """Spec §7.2 embeds ``"{name}. {definition}"``."""
    return f"{name}. {definition or ''}".strip()
