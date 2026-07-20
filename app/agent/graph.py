"""
LangGraph 图编排

定义分析流程的状态图：
用户问题 → 解析 → 检查 → 分析 → 提取 → 报告 → 校验 → 输出
"""

from typing import Any, Callable

from langgraph.graph import StateGraph, END

from app.agent.state import AnalysisState
from app.agent.progress import reset_progress_callback, set_progress_callback
from app.agent.nodes import (
    parse_question,
    check_completeness,
    ask_clarification,
    build_request,
    run_analysis,
    extract_findings,
    query_attachments,
    retrieve_documents,
    generate_report,
    validate_report,
    finalize,
    handle_error,
)


def route_after_processing(state: AnalysisState) -> str:
    """请求构建、分析或报告生成失败后不再继续下游节点。"""
    if state.next_action == "clarify":
        return "clarify"
    return "error" if state.next_action == "error" else "continue"


def route_after_validation(state: AnalysisState) -> str:
    """只有通过证据校验的报告才能进入最终输出。"""
    return "valid" if state.is_valid and state.next_action != "error" else "error"


def create_analysis_graph():
    """
    创建分析流程图

    流程：
    用户问题
      ↓
    解析问题与时间范围
      ↓
    信息是否完整？ ──否──→ 追问用户
      ↓ 是
    构造 AnalysisRequest
      ↓
    调用 run_conversion_analysis
      ↓
    提取主要发现与证据
      ↓
    检索相关文档（RAG）
      ↓
    LLM生成报告草稿
      ↓
    证据校验：每条结论必须能对应 evidence
      ↓
    最终结构化报告
    """

    # 创建状态图
    workflow = StateGraph(AnalysisState)

    # 添加节点
    workflow.add_node("parse_question", parse_question)
    workflow.add_node("ask_clarification", ask_clarification)
    workflow.add_node("build_request", build_request)
    workflow.add_node("run_analysis", run_analysis)
    workflow.add_node("extract_findings", extract_findings)
    workflow.add_node("query_attachments", query_attachments)
    workflow.add_node("retrieve_documents", retrieve_documents)
    workflow.add_node("generate_report", generate_report)
    workflow.add_node("validate_report", validate_report)
    workflow.add_node("finalize", finalize)
    workflow.add_node("handle_error", handle_error)

    # 定义边
    # 入口：解析问题
    workflow.set_entry_point("parse_question")

    # 解析后：检查完整性
    workflow.add_conditional_edges(
        "parse_question",
        check_completeness,
        {
            "complete": "build_request",
            "clarify": "ask_clarification"
        }
    )

    # 追问后：结束（等待用户回复）
    workflow.add_edge("ask_clarification", END)

    # 构造请求后：运行分析或终止错误流程
    workflow.add_conditional_edges(
        "build_request",
        route_after_processing,
        {
            "continue": "run_analysis",
            "clarify": "ask_clarification",
            "error": "handle_error",
        }
    )

    # 分析后：提取发现或终止错误流程
    workflow.add_conditional_edges(
        "run_analysis",
        route_after_processing,
        {
            "continue": "extract_findings",
            "clarify": "ask_clarification",
            "error": "handle_error",
        }
    )

    # 提取后：查询附件或终止错误流程
    workflow.add_conditional_edges(
        "extract_findings",
        route_after_processing,
        {
            "continue": "query_attachments",
            "clarify": "ask_clarification",
            "error": "handle_error",
        }
    )

    # 附件查询后：检索文档（query_attachments 不会设置 error/clarify）
    workflow.add_edge("query_attachments", "retrieve_documents")

    # 检索后：生成报告（retrieve_documents 不会设置 error/clarify）
    workflow.add_edge("retrieve_documents", "generate_report")

    # 生成后：校验或终止错误流程
    workflow.add_conditional_edges(
        "generate_report",
        route_after_processing,
        {
            "continue": "validate_report",
            "clarify": "ask_clarification",
            "error": "handle_error",
        }
    )

    # 校验后：只有通过验证才输出最终报告
    workflow.add_conditional_edges(
        "validate_report",
        route_after_validation,
        {"valid": "finalize", "error": "handle_error"}
    )

    # 最终：结束
    workflow.add_edge("finalize", END)
    workflow.add_edge("handle_error", END)

    # 编译图
    graph = workflow.compile()

    return graph


NODE_PROGRESS = {
    "parse_question": ("解析问题", "正在提取指标、时间范围和分析维度"),
    "ask_clarification": ("生成追问", "正在整理还需补充的信息"),
    "build_request": ("构造分析请求", "正在校验数据范围"),
    "run_analysis": ("计算归因", "正在查询业务数据并计算漏斗"),
    "extract_findings": ("提取关键发现", "正在排序主要影响因素"),
    "query_attachments": ("查询附件", "正在从上传文件中提取补充证据"),
    "retrieve_documents": ("检索文档", "正在从文档库中检索相关业务资料"),
    "generate_report": ("生成报告", "正在基于证据生成结论"),
    "validate_report": ("校验证据", "正在检查结论与证据的一致性"),
    "finalize": ("整理最终结果", "正在输出可展示报告"),
    "handle_error": ("处理异常", "分析流程未能正常完成"),
}


def _next_node(node_name: str, state: dict[str, Any]) -> str | None:
    """根据本次节点输出推断下一条图边，用于展示进行中状态。"""
    if state.get("next_action") == "error":
        return "handle_error"
    if node_name == "parse_question":
        return "build_request" if state.get("is_info_complete") else "ask_clarification"
    if node_name == "build_request":
        return "run_analysis"
    if node_name == "run_analysis":
        return "extract_findings"
    if node_name == "extract_findings":
        return "retrieve_documents"
    if node_name == "retrieve_documents":
        return "generate_report"
    if node_name == "generate_report":
        return "validate_report"
    if node_name == "validate_report":
        return "finalize" if state.get("is_valid") else "handle_error"
    return None


def _emit_progress(
    callback: Callable[[dict[str, Any]], None] | None,
    event_type: str,
    **payload: Any,
) -> None:
    if callback:
        callback({"type": event_type, **payload})


def run_analysis_pipeline(
    user_question: str,
    conversation_id: str | None = None,
    conversation_history: list[dict[str, Any]] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict:
    """
    运行分析流程

    Args:
        user_question: 用户问题
        conversation_id: 会话ID（可选）
        conversation_history: 同一会话下历史任务的上下文摘要（可选）
        attachments: 当前会话已解析的结构化附件元数据（可选）

    Returns:
        dict: 分析状态
    """
    # 创建初始状态
    initial_state = AnalysisState(
        user_question=user_question,
        conversation_id=conversation_id,
        conversation_history=conversation_history or [],
        attachments=attachments or [],
    )

    # 创建图
    graph = create_analysis_graph()

    progress_token = set_progress_callback(on_progress)
    try:
        label, message = NODE_PROGRESS["parse_question"]
        _emit_progress(on_progress, "node_started", node="parse_question", label=label, message=message)
        final_state: dict | None = None

        # updates 会在每个真实 LangGraph 节点结束后产生一条事件。
        for update in graph.stream(initial_state, stream_mode="updates"):
            node_name, state = next(iter(update.items()))
            if not isinstance(state, dict):
                continue
            final_state = state
            label, message = NODE_PROGRESS.get(node_name, (node_name, "正在处理"))
            _emit_progress(on_progress, "node_completed", node=node_name, label=label, message=message)

            next_node = _next_node(node_name, state)
            if next_node:
                next_label, next_message = NODE_PROGRESS[next_node]
                _emit_progress(
                    on_progress,
                    "node_started",
                    node=next_node,
                    label=next_label,
                    message=next_message,
                )

        if final_state is None:
            raise RuntimeError("LangGraph 未返回最终状态")
        return final_state
    finally:
        reset_progress_callback(progress_token)


# ============================================================
# 测试代码
# ============================================================

if __name__ == "__main__":
    import os

    # 设置环境变量（测试用）
    # os.environ["OPENAI_API_KEY"] = "your-api-key"
    # os.environ["OPENAI_BASE_URL"] = "https://api.openai.com/v1"

    print("=" * 60)
    print("LangGraph 分析流程测试")
    print("=" * 60)

    # 测试问题
    test_questions = [
        "为什么本月整体转化率比上月下降了？",
        "抖音渠道的转化率为什么下降？",
    ]

    for question in test_questions:
        print(f"\n问题: {question}")
        print("-" * 40)

        try:
            result = run_analysis_pipeline(question)

            if result.errors:
                print(f"错误: {result.errors}")

            if result.clarification_question and result.next_action == "clarify":
                print(f"追问: {result.clarification_question}")

            if result.report_final:
                print(f"\n报告已生成（{len(result.report_final)}字）")
                print("\n报告预览:")
                print(result.report_final[:500] + "...")

            if result.key_findings:
                print(f"\n关键发现:")
                for f in result.key_findings[:3]:
                    print(f"  - {f['dimension']}-{f['group']}: {f['effect']*100:+.4f}%")

        except Exception as e:
            print(f"运行失败: {str(e)}")
