"""Embedding function selection for ChromaDB."""

from __future__ import annotations

from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from config import EMBEDDING_MODEL


def get_embedding_function():
    """Return the configured ChromaDB embedding function."""
    return SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL.strip())
