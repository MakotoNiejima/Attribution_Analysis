"""检索器：根据分析问题和关键发现，从文档库中检索相关片段。"""

from app.rag.embedder import embed_query
from app.rag.store import get_rag_store, RetrievedChunk


def retrieve_context(
    query: str,
    key_findings: list[dict] | None = None,
    top_k: int = 5,
) -> tuple[list[RetrievedChunk], str]:
    """检索与分析相关的文档片段。

    Args:
        query: 用户问题或问题描述
        key_findings: extract_findings 节点的输出（可选，用于扩展检索词）
        top_k: 返回的最大片段数

    Returns:
        (chunks, formatted_text) — 原始 chunk 列表和格式化后的文本
    """
    store = get_rag_store()

    # 如果没有文档，直接返回空
    if store.get_document_count() == 0:
        return [], ""

    # 组合检索词：问题 + 前3个 finding 的描述
    search_parts = [query]
    if key_findings:
        for f in key_findings[:3]:
            dim = f.get("dimension", "")
            group = f.get("group", "")
            effect = f.get("effect", 0)
            search_parts.append(f"{dim} {group} 效应{effect*100:+.2f}%")

    combined_query = " ".join(search_parts)

    # 编码 + 检索
    query_emb = embed_query(combined_query)
    chunks = store.search(query_emb, top_k=top_k)

    if not chunks:
        return [], ""

    # 格式化为可注入提示词的文本
    lines = []
    for i, chunk in enumerate(chunks, 1):
        source_tag = f"[来源: {chunk.source_file}"
        if chunk.source_detail:
            source_tag += f", {chunk.source_detail}"
        source_tag += "]"

        lines.append(f"### 文档片段 {i} {source_tag}\n{chunk.text}")

    formatted = "\n\n".join(lines)
    return chunks, formatted
