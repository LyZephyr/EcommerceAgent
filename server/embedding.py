"""Embedding function selection for ChromaDB."""

from __future__ import annotations

import threading

import numpy as np
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from config import EMBEDDING_MODEL


class QuietSentenceTransformerEmbeddingFunction(SentenceTransformerEmbeddingFunction):
    """SentenceTransformer embedding function without tqdm progress bars."""

    def __call__(self, input):
        embeddings = self._model.encode(
            list(input),
            convert_to_numpy=True,
            normalize_embeddings=self.normalize_embeddings,
            show_progress_bar=False,
        )
        return [np.array(embedding, dtype=np.float32) for embedding in embeddings]


_embedding_function = None
_embedding_function_lock = threading.Lock()


def get_embedding_function():
    """Return the configured ChromaDB embedding function."""
    global _embedding_function
    if _embedding_function is None:
        with _embedding_function_lock:
            if _embedding_function is None:
                _embedding_function = QuietSentenceTransformerEmbeddingFunction(
                    model_name=EMBEDDING_MODEL.strip()
                )
    return _embedding_function
