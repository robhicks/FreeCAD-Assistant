# SPDX-License-Identifier: LGPL-2.1-or-later

import json
import math
import os
import sqlite3
import struct


def _user_data_dir():
    """Return path to FreeCAD user data directory for the addon."""
    try:
        import FreeCAD
        base = FreeCAD.getUserAppDataDir()
    except Exception:
        base = os.path.join(os.path.expanduser("~"), ".local", "share", "FreeCAD")
    path = os.path.join(base, "Mod", "AIAssistant")
    os.makedirs(path, exist_ok=True)
    return path


def _pack_vector(vector):
    """Pack a list of floats into a bytes blob (float32)."""
    return struct.pack(f"{len(vector)}f", *vector)


def _unpack_vector(blob):
    """Unpack a bytes blob into a list of floats."""
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _cosine_similarity(a, b):
    """Pure Python cosine similarity between two float lists."""
    dot = math.fsum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(math.fsum(x * x for x in a))
    mag_b = math.sqrt(math.fsum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


class VectorStore:
    """SQLite-backed vector store with cosine similarity search and FTS5 fallback."""

    def __init__(self, db_path=None):
        if db_path is None:
            db_path = os.path.join(_user_data_dir(), "rag.db")
        self._db_path = db_path
        self._conn = None
        self._ensure_tables()

    def _get_conn(self):
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def _ensure_tables(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                metadata TEXT,
                embedding BLOB
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        # FTS5 for keyword fallback
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts "
                "USING fts5(id, text, content=chunks, content_rowid=rowid)"
            )
        except sqlite3.OperationalError:
            pass  # FTS5 not available
        conn.commit()

    def store_embedding(self, chunk_id, text, metadata, vector=None):
        """Store a chunk with optional embedding vector."""
        conn = self._get_conn()
        blob = _pack_vector(vector) if vector else None
        meta_json = json.dumps(metadata) if metadata else None
        conn.execute(
            "INSERT OR REPLACE INTO chunks (id, text, metadata, embedding) "
            "VALUES (?, ?, ?, ?)",
            (chunk_id, text, meta_json, blob),
        )
        # Update FTS index
        try:
            conn.execute(
                "INSERT OR REPLACE INTO chunks_fts (id, text) VALUES (?, ?)",
                (chunk_id, text),
            )
        except sqlite3.OperationalError:
            pass
        conn.commit()

    def store_batch(self, chunks, vectors=None):
        """Store multiple chunks at once. vectors is a parallel list or None."""
        conn = self._get_conn()
        for i, chunk in enumerate(chunks):
            vec = vectors[i] if vectors else None
            blob = _pack_vector(vec) if vec else None
            meta_json = json.dumps(chunk.get("metadata")) if chunk.get("metadata") else None
            conn.execute(
                "INSERT OR REPLACE INTO chunks (id, text, metadata, embedding) "
                "VALUES (?, ?, ?, ?)",
                (chunk["id"], chunk["text"], meta_json, blob),
            )
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO chunks_fts (id, text) VALUES (?, ?)",
                    (chunk["id"], chunk["text"]),
                )
            except sqlite3.OperationalError:
                pass
        conn.commit()

    def search(self, query_vector, top_k=5):
        """Search by cosine similarity. Returns list of (chunk_id, text, metadata, score)."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, text, metadata, embedding FROM chunks WHERE embedding IS NOT NULL"
        ).fetchall()

        scored = []
        for row_id, text, meta_json, blob in rows:
            vec = _unpack_vector(blob)
            score = _cosine_similarity(query_vector, vec)
            metadata = json.loads(meta_json) if meta_json else {}
            scored.append((row_id, text, metadata, score))

        scored.sort(key=lambda x: x[3], reverse=True)
        return scored[:top_k]

    def search_keyword(self, query, top_k=5):
        """FTS5 keyword search fallback. Returns list of (chunk_id, text, metadata, score)."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT c.id, c.text, c.metadata FROM chunks_fts f "
                "JOIN chunks c ON f.id = c.id "
                "WHERE chunks_fts MATCH ? LIMIT ?",
                (query, top_k),
            ).fetchall()
        except sqlite3.OperationalError:
            # FTS5 not available, do simple LIKE search
            terms = query.split()
            if not terms:
                return []
            where = " AND ".join(["text LIKE ?"] * len(terms))
            params = [f"%{t}%" for t in terms] + [top_k]
            rows = conn.execute(
                f"SELECT id, text, metadata FROM chunks WHERE {where} LIMIT ?",
                params,
            ).fetchall()

        results = []
        for row_id, text, meta_json in rows:
            metadata = json.loads(meta_json) if meta_json else {}
            results.append((row_id, text, metadata, 1.0))
        return results

    def get_meta(self, key, default=None):
        conn = self._get_conn()
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key, value):
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
        )
        conn.commit()

    def needs_rebuild(self):
        """Check if index needs rebuild (version changed or empty)."""
        try:
            import FreeCAD
            current_version = FreeCAD.Version()[0] + "." + FreeCAD.Version()[1]
        except Exception:
            current_version = "unknown"

        stored_version = self.get_meta("freecad_version")
        chunk_count = self._get_conn().execute(
            "SELECT COUNT(*) FROM chunks"
        ).fetchone()[0]

        return stored_version != current_version or chunk_count == 0

    def clear(self):
        """Remove all chunks for rebuild."""
        conn = self._get_conn()
        conn.execute("DELETE FROM chunks")
        try:
            conn.execute("DELETE FROM chunks_fts")
        except sqlite3.OperationalError:
            pass
        conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
