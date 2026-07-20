"""FAISS 向量存储 + SQLite 元数据。

文档上传后解析→分块→编码→写入 FAISS 索引和 SQLite。
查询时从 FAISS 检索 Top-K，再从 SQLite 取回文本和来源信息。
"""

import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from app.rag.chunker import Chunk, chunk_text
from app.rag.embedder import embed_texts, embed_query
from app.rag.parser import parse_file

# 存储目录
_UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads"
_DB_PATH = Path(__file__).parent.parent.parent / "rag_store.db"


@dataclass
class RetrievedChunk:
    """检索结果。"""
    text: str
    source_file: str
    source_detail: str
    chunk_index: int
    score: float

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "source_file": self.source_file,
            "source_detail": self.source_detail,
            "chunk_index": self.chunk_index,
            "score": round(self.score, 4),
        }


class RagStore:
    """文档向量存储。"""

    def __init__(self):
        self._lock = threading.Lock()
        # 优先使用 FAISS；在 Windows 等没有可用 FAISS wheel 的环境中，退回到
        # NumPy 的精确内积检索。演示数据规模很小，这个退化不会影响正确性。
        self._index = None
        self._uses_faiss = False
        self._chunk_ids: list[int] = []  # 索引行号 → chunk_id 映射
        self._index_dirty = True
        self._ensure_dirs()

    def _ensure_dirs(self):
        _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    def _get_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rag_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rag_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                source_detail TEXT NOT NULL DEFAULT '',
                embedding BLOB,
                FOREIGN KEY (doc_id) REFERENCES rag_documents(id) ON DELETE CASCADE
            )
        """)
        conn.commit()
        return conn

    # ================================================================
    # 文档管理
    # ================================================================

    def add_document(self, file_path: str | Path) -> dict[str, Any]:
        """解析文档→分块→编码→入库。返回文档摘要。"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")

        filename = path.name
        file_type = path.suffix.lower()
        file_size = path.stat().st_size

        # 1. 解析
        text = parse_file(path)
        if not text.strip():
            raise ValueError(f"文件内容为空: {filename}")

        # 2. 分块
        chunks = chunk_text(text, source_file=filename)
        if not chunks:
            raise ValueError(f"分块结果为空: {filename}")

        # 3. 编码
        embeddings = embed_texts([c.text for c in chunks])

        # 4. 写入 SQLite
        now = datetime.now(UTC).isoformat()
        with self._lock:
            conn = self._get_db()
            try:
                cursor = conn.execute(
                    "INSERT INTO rag_documents (filename, file_path, file_type, file_size, chunk_count, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (filename, str(path), file_type, file_size, len(chunks), now),
                )
                doc_id = cursor.lastrowid

                for i, chunk in enumerate(chunks):
                    emb_blob = embeddings[i].tobytes()
                    conn.execute(
                        "INSERT INTO rag_chunks (doc_id, chunk_index, text, source_detail, embedding) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (doc_id, chunk.chunk_index, chunk.text, chunk.source_detail, emb_blob),
                    )

                conn.commit()
            finally:
                conn.close()

        # 5. 标记索引需要重建
        self._index_dirty = True

        return {
            "doc_id": doc_id,
            "filename": filename,
            "file_type": file_type,
            "file_size": file_size,
            "chunk_count": len(chunks),
        }

    def list_documents(self) -> list[dict[str, Any]]:
        """列出所有已上传文档。"""
        conn = self._get_db()
        try:
            rows = conn.execute(
                "SELECT id, filename, file_type, file_size, chunk_count, created_at "
                "FROM rag_documents ORDER BY created_at DESC"
            ).fetchall()
            return [
                {
                    "doc_id": r[0],
                    "filename": r[1],
                    "file_type": r[2],
                    "file_size": r[3],
                    "chunk_count": r[4],
                    "created_at": r[5],
                }
                for r in rows
            ]
        finally:
            conn.close()

    def delete_document(self, doc_id: int) -> bool:
        """删除文档及其所有 chunk。"""
        with self._lock:
            conn = self._get_db()
            try:
                # 删除文件
                row = conn.execute("SELECT file_path FROM rag_documents WHERE id=?", (doc_id,)).fetchone()
                if row is None:
                    return False
                file_path = Path(row[0])
                if file_path.exists():
                    file_path.unlink()

                conn.execute("DELETE FROM rag_chunks WHERE doc_id=?", (doc_id,))
                conn.execute("DELETE FROM rag_documents WHERE id=?", (doc_id,))
                conn.commit()
            finally:
                conn.close()

        self._index_dirty = True
        return True

    def get_document_count(self) -> int:
        """返回文档总数。"""
        conn = self._get_db()
        try:
            row = conn.execute("SELECT COUNT(*) FROM rag_documents").fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    # ================================================================
    # 向量检索
    # ================================================================

    def _build_index(self):
        """从 SQLite 重建向量索引，并兼容没有 FAISS 的本地环境。"""

        conn = self._get_db()
        try:
            rows = conn.execute(
                "SELECT id, embedding FROM rag_chunks ORDER BY id"
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            self._index = None
            self._uses_faiss = False
            self._chunk_ids = []
            self._index_dirty = False
            return

        chunk_ids = []
        embeddings = []
        for chunk_id, emb_blob in rows:
            chunk_ids.append(chunk_id)
            embeddings.append(np.frombuffer(emb_blob, dtype=np.float32))

        matrix = np.stack(embeddings)
        backend = os.getenv("RAG_VECTOR_BACKEND", "numpy").strip().lower()
        if backend == "faiss":
            try:
                import faiss

                index = faiss.IndexFlatIP(matrix.shape[1])
                index.add(matrix)
                self._index = index
                self._uses_faiss = True
            except (ImportError, RuntimeError):
                # FAISS 缺失或初始化失败时使用 NumPy。某些平台的
                # FAISS wheel 在 search 时可能直接终止进程，因此默认不自动启用。
                self._index = matrix
                self._uses_faiss = False
        else:
            # 演示数据规模很小，精确内积检索的结果与 IndexFlatIP 一致。
            self._index = matrix
            self._uses_faiss = False
        self._chunk_ids = chunk_ids
        self._index_dirty = False

    def search(self, query_embedding: np.ndarray, top_k: int = 5) -> list[RetrievedChunk]:
        """检索最相关的 chunk。"""
        with self._lock:
            if self._index_dirty:
                self._build_index()

            if self._index is None or not self._chunk_ids:
                return []

            # query_embedding shape: (dim,) → (1, dim)
            query = query_embedding.reshape(1, -1).astype(np.float32)
            limit = min(max(1, top_k), len(self._chunk_ids))
            if self._uses_faiss:
                scores, indices = self._index.search(query, limit)
            else:
                # 编码器已经输出 L2 归一化向量，因此内积就是余弦相似度。
                all_scores = self._index @ query[0]
                ranked = np.argsort(-all_scores, kind="stable")[:limit]
                scores = all_scores[ranked].reshape(1, -1)
                indices = ranked.reshape(1, -1)

        # 从 SQLite 取回文本
        conn = self._get_db()
        try:
            results = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < 0:
                    continue
                chunk_id = self._chunk_ids[idx]
                row = conn.execute(
                    "SELECT c.text, c.source_detail, c.chunk_index, d.filename "
                    "FROM rag_chunks c JOIN rag_documents d ON c.doc_id = d.id "
                    "WHERE c.id = ?",
                    (chunk_id,),
                ).fetchone()
                if row:
                    results.append(RetrievedChunk(
                        text=row[0],
                        source_file=row[3],
                        source_detail=row[1],
                        chunk_index=row[2],
                        score=float(score),
                    ))
            return results
        finally:
            conn.close()

    def clear_all(self):
        """清空所有文档和索引（测试用）。"""
        with self._lock:
            conn = self._get_db()
            try:
                conn.execute("DELETE FROM rag_chunks")
                conn.execute("DELETE FROM rag_documents")
                conn.commit()
            finally:
                conn.close()
            self._index = None
            self._uses_faiss = False
            self._chunk_ids = []
            self._index_dirty = True


# 单例
_store: RagStore | None = None


def get_rag_store() -> RagStore:
    global _store
    if _store is None:
        _store = RagStore()
    return _store
