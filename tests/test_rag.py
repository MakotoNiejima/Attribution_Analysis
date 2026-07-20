"""
RAG 模块单元测试：parser / chunker / store / documents API

不依赖真实的 embedding 模型（mock 掉），验证解析、分块、存储和 API 的正确性。
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.rag.parser import parse_file
from app.rag.chunker import chunk_text, Chunk
from app.rag.store import RagStore, RetrievedChunk


# ============================================================
# 文档解析器测试
# ============================================================

class TestParser:
    """parse_file 单元测试"""

    def test_parse_txt(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("第一段内容。\n\n第二段内容。", encoding="utf-8")
        result = parse_file(f)
        assert "第一段内容" in result
        assert "第二段内容" in result

    def test_parse_md(self, tmp_path):
        f = tmp_path / "readme.md"
        f.write_text("# 标题\n\n正文内容。", encoding="utf-8")
        result = parse_file(f)
        assert "标题" in result
        assert "正文" in result

    def test_parse_empty_file_returns_empty(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")
        result = parse_file(f)
        assert result == ""

    def test_unsupported_extension_raises(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text('{"key": "value"}', encoding="utf-8")
        with pytest.raises(ValueError, match="不支持"):
            parse_file(f)


# ============================================================
# 文本分块器测试
# ============================================================

class TestChunker:
    """chunk_text 单元测试"""

    def test_short_text_single_chunk(self):
        text = "这是一段短文本。"
        chunks = chunk_text(text, source_file="test.txt")
        assert len(chunks) == 1
        assert chunks[0].text == text
        assert chunks[0].source_file == "test.txt"
        assert chunks[0].chunk_index == 0

    def test_long_text_multiple_chunks(self):
        # 每段100字，共6段 = 600字，chunk_size=200 应该切成多块
        paragraphs = ["段落" + "内容" * 49 for _ in range(6)]
        text = "\n\n".join(paragraphs)
        chunks = chunk_text(text, source_file="big.txt", chunk_size=200, overlap=50)
        assert len(chunks) > 1
        # 每个 chunk 都有来源信息
        for c in chunks:
            assert c.source_file == "big.txt"

    def test_page_marker_preserved(self):
        # 用足够长的文本让 chunker 分成多块，每块携带各自的页码标记
        para1 = "[第1页]\n" + "内容A" * 100
        para2 = "[第2页]\n" + "内容B" * 100
        text = para1 + "\n\n" + para2
        chunks = chunk_text(text, source_file="doc.pdf", chunk_size=200, overlap=50)
        details = [c.source_detail for c in chunks]
        # 至少应有一个 chunk 带有页码标记
        assert any("第1页" in d or "第2页" in d for d in details)

    def test_empty_text_returns_empty(self):
        assert chunk_text("", source_file="x.txt") == []
        assert chunk_text("   ", source_file="x.txt") == []

    def test_chunk_index_sequential(self):
        paragraphs = ["段落" + "字" * 100 for _ in range(4)]
        text = "\n\n".join(paragraphs)
        chunks = chunk_text(text, source_file="seq.txt", chunk_size=150, overlap=30)
        for i, c in enumerate(chunks):
            assert c.chunk_index == i


# ============================================================
# FAISS 存储测试（mock embedding）
# ============================================================

@pytest.fixture
def rag_store(tmp_path, monkeypatch):
    """创建一个使用临时目录的 RagStore，并 mock 掉 embedding 调用。"""
    # 重定向存储路径到临时目录
    import app.rag.store as store_module
    monkeypatch.setattr(store_module, "_UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(store_module, "_DB_PATH", tmp_path / "rag_store.db")

    s = RagStore()
    yield s
    s.clear_all()


def _mock_embed_texts(texts):
    """返回随机但确定的向量。"""
    rng = np.random.RandomState(42)
    return rng.randn(len(texts), 512).astype(np.float32)


def _mock_embed_query(query):
    rng = np.random.RandomState(99)
    return rng.randn(512).astype(np.float32)


class TestRagStore:
    """RagStore 集成测试"""

    @patch("app.rag.store.embed_texts", side_effect=_mock_embed_texts)
    def test_add_and_list_document(self, mock_emb, rag_store, tmp_path):
        f = tmp_path / "活动方案.txt"
        f.write_text("这是一份活动方案。\n\n抖音渠道投放计划。", encoding="utf-8")
        result = rag_store.add_document(f)
        assert result["doc_id"] > 0
        assert result["chunk_count"] >= 1
        assert result["filename"] == "活动方案.txt"

        docs = rag_store.list_documents()
        assert len(docs) == 1
        assert docs[0]["filename"] == "活动方案.txt"

    @patch("app.rag.store.embed_texts", side_effect=_mock_embed_texts)
    def test_delete_document(self, mock_emb, rag_store, tmp_path):
        f = tmp_path / "临时文件.txt"
        f.write_text("临时内容用于测试删除。", encoding="utf-8")
        result = rag_store.add_document(f)
        doc_id = result["doc_id"]

        assert rag_store.get_document_count() == 1
        assert rag_store.delete_document(doc_id) is True
        assert rag_store.get_document_count() == 0
        assert rag_store.delete_document(9999) is False  # 不存在的文档

    @patch("app.rag.store.embed_texts", side_effect=_mock_embed_texts)
    @patch("app.rag.store.embed_query", side_effect=_mock_embed_query)
    def test_search_returns_results(self, mock_query, mock_emb, rag_store, tmp_path):
        f = tmp_path / "投放记录.txt"
        f.write_text("抖音投放预算10万。\n\n效果分析：ROI 2.5。", encoding="utf-8")
        rag_store.add_document(f)

        query_emb = _mock_embed_query("抖音投放")
        results = rag_store.search(query_emb, top_k=3)
        assert len(results) >= 1
        assert all(isinstance(r, RetrievedChunk) for r in results)
        assert results[0].source_file == "投放记录.txt"
        assert rag_store._uses_faiss is False

    @patch("app.rag.store.embed_texts", side_effect=_mock_embed_texts)
    def test_search_empty_store(self, mock_emb, rag_store):
        query_emb = _mock_embed_query("测试")
        results = rag_store.search(query_emb, top_k=5)
        assert results == []


# ============================================================
# 文档 API 测试
# ============================================================

@pytest.fixture
def doc_client(monkeypatch, tmp_path):
    """使用 mock RAG store 的测试客户端。"""
    import app.rag.store as store_module

    # 创建一个 mock store
    mock_store = MagicMock(spec=RagStore)
    mock_store.get_document_count.return_value = 0
    mock_store.list_documents.return_value = []
    mock_store.add_document.return_value = {
        "doc_id": 1, "filename": "test.txt",
        "file_type": ".txt", "file_size": 100, "chunk_count": 3,
    }
    mock_store.delete_document.return_value = True

    monkeypatch.setattr("app.api.documents.get_rag_store", lambda: mock_store)

    from app.main import app
    return TestClient(app), mock_store


class TestDocumentsAPI:
    """文档上传/列表/删除 API 测试"""

    def test_upload_txt_file(self, doc_client):
        client, mock_store = doc_client
        import io
        content = "测试文档内容。\n\n第二段。".encode("utf-8")
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("测试.txt", io.BytesIO(content), "text/plain")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "片段" in data["message"]

    def test_upload_unsupported_extension(self, doc_client):
        client, _ = doc_client
        import io
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("data.json", io.BytesIO(b'{"a":1}'), "application/json")},
        )
        assert response.status_code == 400
        assert "不支持" in response.json()["detail"]

    def test_upload_empty_file(self, doc_client):
        client, _ = doc_client
        import io
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("empty.txt", io.BytesIO(b""), "text/plain")},
        )
        assert response.status_code == 400

    def test_list_documents(self, doc_client):
        client, mock_store = doc_client
        mock_store.list_documents.return_value = [
            {"doc_id": 1, "filename": "a.txt", "file_type": ".txt", "file_size": 100, "chunk_count": 2, "created_at": "2026-07-20"},
        ]
        response = client.get("/api/v1/documents")
        assert response.status_code == 200
        assert response.json()["total"] == 1

    def test_delete_document(self, doc_client):
        client, mock_store = doc_client
        response = client.delete("/api/v1/documents/1")
        assert response.status_code == 200
        mock_store.delete_document.assert_called_once_with(1)

    def test_delete_nonexistent_document(self, doc_client):
        client, mock_store = doc_client
        mock_store.delete_document.return_value = False
        response = client.delete("/api/v1/documents/999")
        assert response.status_code == 404


# ============================================================
# 独立运行
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
