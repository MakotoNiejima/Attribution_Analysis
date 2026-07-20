"""
多轮对话上下文衔接测试

场景：
1. 首轮模糊问题 → 返回追问
2. 二轮补充信息 → 同一 conversation_id → 自动合并上下文 → 完成分析
3. 验证 conversation 下有 2 条 task 记录
4. 验证上下文格式化函数正确工作
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.persistence.models import utc_now
from app.persistence.service import TaskNotFoundError
from app.agent.nodes import _format_conversation_history


# ============================================================
# FakePersistenceService（与 test_api_analysis 共享逻辑）
# ============================================================

class FakePersistenceService:
    def __init__(self):
        self.conversations = {}
        self.tasks = {}

    def initialize_schema(self):
        return None

    def fail_interrupted_tasks(self):
        return 0

    def create_task(self, conversation_id, question):
        conversation_id = conversation_id or f"conversation-{len(self.conversations) + 1}"
        now = utc_now()
        self.conversations.setdefault(conversation_id, {
            "conversation_id": conversation_id,
            "title": question[:100],
            "task_count": 0,
            "created_at": now,
            "updated_at": now,
        })
        task_id = f"task-{len(self.tasks) + 1}"
        task = {
            "task_id": task_id,
            "conversation_id": conversation_id,
            "question": question,
            "status": "running",
            "created_at": now,
            "started_at": now,
            "finished_at": None,
            "clarification_question": None,
            "errors": [],
            "report": None,
            "key_findings": [],
            "analysis_result": {},
            "evidence": {},
            "matched_events": [],
        }
        self.tasks[task_id] = task
        self.conversations[conversation_id]["task_count"] += 1
        self.conversations[conversation_id]["last_task_id"] = task_id
        self.conversations[conversation_id]["last_task_status"] = "running"
        return task.copy()

    def finish_task(self, task_id, *, status, **payload):
        task = self.tasks[task_id]
        task["status"] = status
        task["finished_at"] = utc_now()
        task["clarification_question"] = payload.get("clarification_question")
        task["errors"] = payload.get("errors", [])
        for key in ("report", "key_findings", "analysis_result", "evidence", "matched_events"):
            if key in payload:
                task[key] = payload[key]
        conversation = self.conversations[task["conversation_id"]]
        conversation["last_task_status"] = status
        conversation["updated_at"] = task["finished_at"]
        return task.copy()

    def list_conversations(self, limit=30):
        return sorted(
            (item.copy() for item in self.conversations.values()),
            key=lambda item: item["updated_at"],
            reverse=True,
        )[:limit]

    def list_tasks(self, conversation_id, limit=50):
        if conversation_id not in self.conversations:
            raise TaskNotFoundError(conversation_id)
        return [
            {key: task[key] for key in ("task_id", "conversation_id", "question", "status", "created_at", "started_at", "finished_at")}
            for task in reversed(list(self.tasks.values()))
            if task["conversation_id"] == conversation_id
        ][:limit]

    def get_task(self, task_id):
        if task_id not in self.tasks:
            raise TaskNotFoundError(task_id)
        return self.tasks[task_id].copy()

    def get_conversation_context(self, conversation_id, limit=5, exclude_task_id=None):
        tasks = [
            t for t in self.tasks.values()
            if t["conversation_id"] == conversation_id
            and t["task_id"] != exclude_task_id
        ]
        context = []
        for task in tasks[:limit]:
            summary = None
            if task["status"] == "completed" and task.get("key_findings"):
                parts = []
                for f in task["key_findings"][:3]:
                    dim = f.get("dimension", "")
                    group = f.get("group", "")
                    effect = f.get("effect", 0)
                    parts.append(f"{dim}-{group} 效应{effect*100:+.2f}%")
                summary = "；".join(parts)
            context.append({
                "question": task["question"],
                "status": task["status"],
                "clarification_question": task.get("clarification_question"),
                "key_findings_summary": summary,
            })
        return context


@pytest.fixture
def persistence(monkeypatch):
    store = FakePersistenceService()
    monkeypatch.setattr("app.api.analysis.get_persistence_service", lambda: store)
    monkeypatch.setattr("app.services.analysis_execution.get_persistence_service", lambda: store)
    monkeypatch.setattr("app.main.get_persistence_service", lambda: store)
    return store


@pytest.fixture
def client(persistence):
    return TestClient(app)


# ============================================================
# 多轮对话 API 测试
# ============================================================

class TestMultiTurnConversation:
    """多轮对话上下文衔接"""

    @patch("app.services.analysis_execution.run_analysis_pipeline")
    def test_clarify_then_complete(self, mock_pipeline, client):
        """首轮追问 → 二轮补充 → 自动完成分析"""

        # 第一轮：模糊问题，返回追问
        mock_pipeline.return_value = {
            "next_action": "clarify",
            "errors": [],
            "parsed_problem": None,
            "key_findings": [],
            "matched_events": [],
            "report_final": None,
            "report_draft": None,
            "evidence": {},
            "analysis_result": {},
            "clarification_question": "请提供要分析的时间范围，例如：2026年7月1日到15日。",
            "validation_errors": [],
        }

        conv_id = "multi-turn-test-001"
        r1 = client.post("/api/v1/analysis/run", json={
            "question": "分析转化率",
            "conversation_id": conv_id,
        })
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1["status"] == "clarify"
        assert d1["conversation_id"] == conv_id
        assert "时间范围" in d1["clarification_question"]

        # 第二轮：补充时间范围，返回完整报告
        mock_pipeline.return_value = {
            "next_action": "end",
            "errors": [],
            "parsed_problem": "分析2026年7月1日至15日与6月1日至15日的转化率变化",
            "key_findings": [
                {"dimension": "渠道", "group": "douyin", "effect": -0.3762},
            ],
            "matched_events": [],
            "report_final": "# 经营分析报告\n\n转化率下降主要来自抖音渠道...",
            "report_draft": None,
            "evidence": {"metrics": [], "dimension_evidences": []},
            "analysis_result": {"baseline_funnel": {}, "current_funnel": {}},
            "clarification_question": None,
            "validation_errors": [],
        }

        r2 = client.post("/api/v1/analysis/run", json={
            "question": "2026年7月1日到15日，对比6月1日到15日",
            "conversation_id": conv_id,
        })
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["status"] == "completed"
        assert d2["conversation_id"] == conv_id
        assert "报告" in d2["report"]

        # 验证会话下有 2 条任务
        tasks = client.get(f"/api/v1/conversations/{conv_id}/tasks").json()
        assert len(tasks) == 2
        assert tasks[0]["question"] == "2026年7月1日到15日，对比6月1日到15日"
        assert tasks[1]["question"] == "分析转化率"

    @patch("app.services.analysis_execution.run_analysis_pipeline")
    def test_context_passes_to_pipeline(self, mock_pipeline, client, persistence):
        """验证第二轮调用 pipeline 时 conversation_history 包含首轮信息"""

        # 第一轮：追问
        mock_pipeline.return_value = {
            "next_action": "clarify",
            "errors": [],
            "clarification_question": "请提供时间范围",
        }
        conv_id = "ctx-check-001"
        client.post("/api/v1/analysis/run", json={
            "question": "看看转化率",
            "conversation_id": conv_id,
        })

        # 第二轮：捕获 pipeline 调用参数
        mock_pipeline.return_value = {
            "next_action": "end",
            "errors": [],
            "report_final": "# 报告",
            "key_findings": [],
            "analysis_result": {},
            "evidence": {},
            "matched_events": [],
        }
        client.post("/api/v1/analysis/run", json={
            "question": "7月和6月前两周",
            "conversation_id": conv_id,
        })

        # 检查第二轮调用时传入了 conversation_history
        second_call = mock_pipeline.call_args_list[-1]
        history = second_call.kwargs.get("conversation_history", [])
        assert len(history) >= 1
        assert history[0]["question"] == "看看转化率"
        assert history[0]["status"] == "clarify"
        assert history[0]["clarification_question"] == "请提供时间范围"


# ============================================================
# 上下文格式化单元测试
# ============================================================

class TestFormatConversationHistory:
    """_format_conversation_history 单元测试"""

    def test_clarify_entry_includes_question(self):
        history = [{
            "question": "分析转化率",
            "status": "clarify",
            "clarification_question": "请提供时间范围",
            "key_findings_summary": None,
        }]
        text = _format_conversation_history(history)
        assert "分析转化率" in text
        assert "请提供时间范围" in text

    def test_completed_entry_includes_findings(self):
        history = [{
            "question": "为什么转化率下降",
            "status": "completed",
            "clarification_question": None,
            "key_findings_summary": "渠道-douyin 效应-0.38%",
        }]
        text = _format_conversation_history(history)
        assert "为什么转化率下降" in text
        assert "渠道-douyin 效应-0.38%" in text

    def test_multiple_entries_ordered(self):
        history = [
            {"question": "Q1", "status": "clarify", "clarification_question": "追问1", "key_findings_summary": None},
            {"question": "Q2", "status": "completed", "clarification_question": None, "key_findings_summary": "结论"},
        ]
        text = _format_conversation_history(history)
        lines = text.strip().split("\n")
        assert "第1轮" in lines[0]
        assert "第2轮" in lines[-1] or "第2轮" in lines[-2]

    def test_empty_history(self):
        text = _format_conversation_history([])
        assert text == ""


# ============================================================
# 独立运行
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
