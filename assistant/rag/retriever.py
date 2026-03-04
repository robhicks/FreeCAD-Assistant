# SPDX-License-Identifier: LGPL-2.1-or-later

import FreeCAD

from assistant.rag.store import VectorStore
from assistant.rag.embeddings import EmbeddingClient
from assistant.rag.chunker import build_chunks


_retriever = None


class Retriever:
    """Top-level retriever: embed query, search store, return relevant chunks."""

    def __init__(self, store, embedding_client):
        self._store = store
        self._emb = embedding_client

    def retrieve(self, query, top_k=5):
        """Return top-K relevant chunks for the query.

        Uses vector search if embeddings are available, otherwise keyword fallback.
        """
        if self._emb and self._emb.supports_embeddings():
            try:
                query_vec = self._emb.embed(query)
                results = self._store.search(query_vec, top_k)
                return [
                    {"id": r[0], "text": r[1], "metadata": r[2], "score": r[3]}
                    for r in results
                ]
            except Exception:
                pass  # Fall through to keyword search

        # Keyword fallback
        results = self._store.search_keyword(query, top_k)
        return [
            {"id": r[0], "text": r[1], "metadata": r[2], "score": r[3]}
            for r in results
        ]

    def ensure_indexed(self):
        """Build/rebuild index if needed (first run or FreeCAD version change)."""
        if not self._store.needs_rebuild():
            return

        FreeCAD.Console.PrintMessage("AI Assistant: Building RAG index...\n")
        self._store.clear()

        chunks = build_chunks()
        if not chunks:
            FreeCAD.Console.PrintWarning(
                "AI Assistant: No chunks generated for RAG index.\n"
            )
            return

        # Embed chunks if provider supports it
        vectors = None
        if self._emb and self._emb.supports_embeddings():
            try:
                texts = [c["text"] for c in chunks]
                vectors = self._emb.embed_batch(texts)
            except Exception as e:
                FreeCAD.Console.PrintWarning(
                    f"AI Assistant: Embedding failed, using keyword search: {e}\n"
                )
                vectors = None

        self._store.store_batch(chunks, vectors)

        # Record version
        try:
            version = FreeCAD.Version()[0] + "." + FreeCAD.Version()[1]
        except Exception:
            version = "unknown"
        self._store.set_meta("freecad_version", version)

        FreeCAD.Console.PrintMessage(
            f"AI Assistant: RAG index built with {len(chunks)} chunks.\n"
        )


def get_retriever():
    """Get or create the singleton Retriever instance."""
    global _retriever
    if _retriever is None:
        store = VectorStore()
        emb_client = EmbeddingClient.from_preferences()
        _retriever = Retriever(store, emb_client)
    return _retriever
