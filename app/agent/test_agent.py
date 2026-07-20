"""不调用真实模型的 LangGraph 回归测试。"""

import json

from app.agent import nodes
from app.agent.graph import create_analysis_graph, run_analysis_pipeline


class FakeReply:
    def __init__(self, content: str):
        self.content = content


class QueueLLM:
    """按节点调用顺序返回固定回复，保证图测试不消耗模型额度。"""

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.messages = []

    def invoke(self, _messages):
        self.messages.append(_messages)
        if not self.replies:
            raise AssertionError("假模型回复不足")
        return FakeReply(self.replies.pop(0))


def complete_parse_reply() -> str:
    return json.dumps({
        "problem": "为什么本月整体转化率比上月下降？",
        "start_date": "2026-07-01",
        "end_date": "2026-07-15",
        "compare_start": "2026-06-01",
        "compare_end": "2026-06-15",
        "dimensions": ["channel", "device", "region", "user_type"],
        "is_complete": True,
        "clarification": None,
    })


def test_graph_contains_success_and_error_routes():
    graph = create_analysis_graph()
    expected_nodes = {
        "__start__", "parse_question", "ask_clarification", "build_request",
        "run_analysis", "extract_findings", "generate_report", "validate_report",
        "finalize", "handle_error",
    }
    assert expected_nodes.issubset(set(graph.nodes))


def test_complete_path_runs_to_verified_report(monkeypatch):
    fake_llm = QueueLLM([
        complete_parse_reply(),
        "# 分析报告\n\n结论均基于给定证据。",
        json.dumps({"is_valid": True, "errors": [], "warnings": []}),
    ])
    monkeypatch.setattr(nodes, "get_llm", lambda: fake_llm)

    result = run_analysis_pipeline("为什么本月整体转化率比上月下降？")

    assert result["next_action"] == "end"
    assert result["errors"] == []
    assert result["report_final"]
    assert result["analysis_request"]["baseline_start"].startswith("2026-06-01")
    assert result["analysis_request"]["current_start"].startswith("2026-07-01")
    assert result["analysis_result"]["current_funnel"]["order_rate"] == 0.0166


def test_complete_path_emits_graph_and_analysis_progress(monkeypatch):
    fake_llm = QueueLLM([
        complete_parse_reply(),
        "# 分析报告\n\n结论均基于给定证据。",
        json.dumps({"is_valid": True, "errors": [], "warnings": []}),
    ])
    monkeypatch.setattr(nodes, "get_llm", lambda: fake_llm)
    events = []

    result = run_analysis_pipeline(
        "为什么本月整体转化率比上月下降？",
        on_progress=events.append,
    )

    assert result["report_final"]
    assert any(event["type"] == "node_started" and event["node"] == "parse_question" for event in events)
    assert any(event["type"] == "detail" and event["stage"] == "channel" for event in events)
    assert any(event["type"] == "node_completed" and event["node"] == "finalize" for event in events)


def test_incomplete_question_keeps_model_clarification(monkeypatch):
    fake_llm = QueueLLM([
        json.dumps({
            "problem": "转化率变化分析",
            "start_date": None,
            "end_date": None,
            "compare_start": None,
            "compare_end": None,
            "dimensions": [],
            "is_complete": False,
            "clarification": "请提供要比较的两个时间范围。",
        })
    ])
    monkeypatch.setattr(nodes, "get_llm", lambda: fake_llm)

    result = run_analysis_pipeline("帮我看看转化率")

    assert result["next_action"] == "clarify"
    assert result["clarification_question"] == "请提供要比较的两个时间范围。"
    assert result["errors"] == []
    assert result["analysis_result"] is None


def test_follow_up_uses_clarification_history_to_complete_request(monkeypatch):
    fake_llm = QueueLLM([
        complete_parse_reply(),
        "# 多轮分析报告\n\n结论均基于给定证据。",
        json.dumps({"is_valid": True, "errors": [], "warnings": []}),
    ])
    monkeypatch.setattr(nodes, "get_llm", lambda: fake_llm)
    history = [{
        "question": "分析转化率",
        "status": "clarify",
        "clarification_question": "请提供要比较的两个时间范围。",
        "key_findings_summary": None,
    }]

    result = run_analysis_pipeline(
        "比较 2026 年 7 月和 6 月。",
        conversation_history=history,
    )

    parse_prompt = fake_llm.messages[0][1].content
    assert "分析转化率" in parse_prompt
    assert "请提供要比较的两个时间范围" in parse_prompt
    assert "比较 2026 年 7 月和 6 月" in parse_prompt
    assert result["next_action"] == "end"
    assert result["report_final"]


def test_invalid_report_never_becomes_final(monkeypatch):
    fake_llm = QueueLLM([
        complete_parse_reply(),
        "# 未验证报告\n\n这里可能包含无证据结论。",
        json.dumps({"is_valid": False, "errors": ["存在缺少证据支持的结论"], "warnings": []}),
    ])
    monkeypatch.setattr(nodes, "get_llm", lambda: fake_llm)

    result = run_analysis_pipeline("为什么本月整体转化率比上月下降？")

    assert result["next_action"] == "error"
    assert result["report_final"] is None
    assert "存在缺少证据支持的结论" in result["errors"]


def test_out_of_data_window_requests_clarification(monkeypatch):
    fake_llm = QueueLLM([
        json.dumps({
            "problem": "本月转化率变化分析",
            "start_date": "2026-07-01",
            "end_date": "2026-07-20",
            "compare_start": "2026-06-01",
            "compare_end": "2026-06-30",
            "dimensions": ["channel"],
            "is_complete": True,
            "clarification": None,
        })
    ])
    monkeypatch.setattr(nodes, "get_llm", lambda: fake_llm)

    result = run_analysis_pipeline("为什么本月整体转化率下降？")

    assert result["next_action"] == "clarify"
    assert "当前演示数据仅覆盖" in result["clarification_question"]
    assert result["analysis_result"] is None
