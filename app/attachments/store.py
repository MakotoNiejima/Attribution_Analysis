"""附件元数据的 SQLite 存储。"""

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

_DB_PATH = Path(__file__).parent.parent.parent / "attachments.db"
_UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads"


@dataclass
class AttachmentRecord:
    id: str
    conversation_id: str
    filename: str
    stored_path: str
    file_size: int
    file_type: str
    row_count: int
    columns_json: list[dict]
    preview_json: list[dict]
    uploaded_at: str
    status: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "filename": self.filename,
            "file_size": self.file_size,
            "file_type": self.file_type,
            "row_count": self.row_count,
            "columns": self.columns_json,
            "preview": self.preview_json,
            "uploaded_at": self.uploaded_at,
            "status": self.status,
        }


class AttachmentStore:
    def __init__(self):
        self._lock = threading.Lock()
        _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self._ensure_table()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_table(self):
        conn = self._conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS attachments (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    file_type TEXT NOT NULL,
                    row_count INTEGER NOT NULL DEFAULT 0,
                    columns_json TEXT NOT NULL DEFAULT '[]',
                    preview_json TEXT NOT NULL DEFAULT '[]',
                    uploaded_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'uploaded'
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_attachments_conversation "
                "ON attachments(conversation_id)"
            )
            conn.commit()
        finally:
            conn.close()

    def save(self, record: AttachmentRecord) -> None:
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "INSERT INTO attachments "
                    "(id, conversation_id, filename, stored_path, file_size, file_type, "
                    " row_count, columns_json, preview_json, uploaded_at, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        record.id,
                        record.conversation_id,
                        record.filename,
                        record.stored_path,
                        record.file_size,
                        record.file_type,
                        record.row_count,
                        json.dumps(record.columns_json, ensure_ascii=False),
                        json.dumps(record.preview_json, ensure_ascii=False),
                        record.uploaded_at,
                        record.status,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def get(self, attachment_id: str) -> AttachmentRecord | None:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT id, conversation_id, filename, stored_path, file_size, file_type, "
                " row_count, columns_json, preview_json, uploaded_at, status "
                "FROM attachments WHERE id = ?",
                (attachment_id,),
            ).fetchone()
            if row is None:
                return None
            return AttachmentRecord(
                id=row[0],
                conversation_id=row[1],
                filename=row[2],
                stored_path=row[3],
                file_size=row[4],
                file_type=row[5],
                row_count=row[6],
                columns_json=json.loads(row[7]),
                preview_json=json.loads(row[8]),
                uploaded_at=row[9],
                status=row[10],
            )
        finally:
            conn.close()

    def list_by_conversation(self, conversation_id: str) -> list[dict]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT id, filename, file_type, file_size, row_count, uploaded_at, status "
                "FROM attachments WHERE conversation_id = ? ORDER BY uploaded_at DESC",
                (conversation_id,),
            ).fetchall()
            return [
                {
                    "id": r[0], "filename": r[1], "file_type": r[2],
                    "file_size": r[3], "row_count": r[4],
                    "uploaded_at": r[5], "status": r[6],
                }
                for r in rows
            ]
        finally:
            conn.close()

    def delete(self, attachment_id: str) -> bool:
        with self._lock:
            conn = self._conn()
            try:
                row = conn.execute(
                    "SELECT stored_path FROM attachments WHERE id = ?", (attachment_id,)
                ).fetchone()
                if row is None:
                    return False
                path = Path(row[0])
                if path.exists():
                    path.unlink()
                conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
                conn.commit()
                return True
            finally:
                conn.close()


_store: AttachmentStore | None = None


def get_attachment_store() -> AttachmentStore:
    global _store
    if _store is None:
        _store = AttachmentStore()
    return _store
