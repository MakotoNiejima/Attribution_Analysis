"""检索文档节点"""

from app.agent.state import AnalysisState
from app.rag.retriever import retrieve_context


def retrieve_documents(state: AnalysisState) -> AnalysisState:
    """
    检索文档

    根据分析结果从 RAG 系统中检索相关文档片段
    """
    print("[节点] 检索文档...")

    try:
        # 准备检索查询
        query = state.parsed_problem or state.user_question
        
        # 添加关键发现作为检索上下文
        if state.key_findings:
            findings_text = "\n".join([
                f"- {f['dimension']}-{f['group']}: 效应{f['effect']*100:+.2f}%"
                for f in state.key_findings[:3]
            ])
            query = f"{query}\n\n关键发现:\n{findings_text}"

        # 检索相关文档
        chunks, formatted_text = retrieve_context(query, top_k=5)
        
        state.retrieved_docs = [
            {"text": c.text, "source_file": c.source_file, "source_detail": c.source_detail}
            for c in chunks
        ]
        state.retrieved_docs_text = formatted_text

        if chunks:
            print(f"  检索到 {len(chunks)} 个相关文档片段")
        else:
            print("  未检索到相关文档")

    except Exception as e:
        print(f"  [警告] 检索文档异常: {e}")
        state.retrieved_docs = []
        state.retrieved_docs_text = ""

    return state
