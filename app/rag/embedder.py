"""Embedding 模型封装：使用 BGE-small-zh 生成文本向量。"""

import numpy as np
from functools import lru_cache


# BGE-small-zh-v1.5 推荐的查询前缀
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


@lru_cache(maxsize=1)
def _load_model():
    """惰性加载模型，只加载一次。"""
    from sentence_transformers import SentenceTransformer
    import torch

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer("BAAI/bge-small-zh-v1.5", device=device)
    return model


def embed_texts(texts: list[str], batch_size: int = 32) -> np.ndarray:
    """批量编码文本，返回 L2 归一化后的向量矩阵。

    Args:
        texts: 待编码文本列表
        batch_size: 批大小

    Returns:
        shape (len(texts), dim) 的 float32 数组
    """
    if not texts:
        return np.array([], dtype=np.float32).reshape(0, 512)

    model = _load_model()
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return embeddings.astype(np.float32)


def embed_query(query: str) -> np.ndarray:
    """编码查询文本（加 BGE query 前缀），返回 shape (dim,) 的向量。"""
    model = _load_model()
    embedding = model.encode(
        [QUERY_PREFIX + query],
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return embedding[0].astype(np.float32)
