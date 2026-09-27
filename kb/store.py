"""Vector store wrapper. PHASE 2.

ChromaDB in persistent local mode: one directory on disk, no server to
install or secure at a customer site, trivial to back up or hand over.
FAISS plus a SQLite metadata table is the fallback if Chroma proves heavy;
kb/retrieve.py hides the difference from everything above it.
"""

from __future__ import annotations

from config import resolve_path


def client():
    import chromadb

    return chromadb.PersistentClient(path=str(resolve_path("knowledge_base")))


def collection(name: str = "default"):
    return client().get_or_create_collection(name)
