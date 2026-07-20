"""
API 测试

使用假 LLM 验证三条路径：
1. completed - 完整问题返回分析报告
2. clarify - 模糊问题返回追问
3. failed - 证据校验失败返回错误
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
from app.realtime.manager import TaskRuntimeManager


# ============================================================
# 测试客户端
# ============================================================

class FakePersistenceService:
    """避免 API 测试连接真实 MySQL，同时验证持久化调用契约。"""

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
            if t["conversation_id"] == conversation_id and t["task_id"] != exclude_task_id
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
    """测试客户端"""
    return TestClient(app)


@pytest.fixture
def realtime_manager(monkeypatch, persistence):
    manager = TaskRuntimeManager()
    monkeypatch.setattr("app.api.analysis.get_task_runtime_manager", lambda: manager)
    return manager


# ============================================================
# 测试用例
# ============================================================

class TestAnalysisAPI:
    """分析接口测试"""

    def test_health_check(self, client):
        """健康检查"""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_cors_allows_local_vite_frontend(self, client):
        """本地 Vite 前端可以在浏览器中访问 API。"""
        response = client.options(
            "/api/v1/analysis/run",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"

    def test_root(self, client):
        """根路径"""
        response = client.get("/")
        assert response.status_code == 200
        assert "docs" in response.json()

    @patch("app.services.analysis_execution.run_analysis_pipeline")
    def test_completed_path(self, mock_pipeline, client):
        """测试 completed 路径：完整问题返回报告"""

        # 模拟分析成功的结果
        mock_pipeline.return_value = {
            "next_action": "end",
            "errors": [],
            "parsed_problem": "为什么本月整体转化率比上月下降了？",
            "key_findings": [
                {"dimension": "渠道", "group": "douyin", "effect": -0.3762},
                {"dimension": "设备", "group": "mobile_web", "effect": -0.9810}
            ],
            "matched_events": [
                {"title": "抖音渠道大规模投放活动", "description": "7月投放"}
            ],
            "report_final": "# 经营分析报告\n\n转化率下降...",
            "report_draft": None,
            "evidence": {"metrics": [], "dimension_evidences": []},
            "analysis_result": {"baseline_funnel": {}, "current_funnel": {}},
            "clarification_question": None,
            "validation_errors": []
        }

        # 发送请求
        response = client.post("/api/v1/analysis/run", json={
            "question": "为什么本月整体转化率比上月下降了？",
            "conversation_id": "test-001"
        })

        # 验证响应
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["conversation_id"] == "test-001"
        assert data["task_id"] == "task-1"
        assert "report" in data
        assert len(data["report"]) > 0
        assert len(data["key_findings"]) > 0

    @patch("app.services.analysis_execution.run_analysis_pipeline")
    def test_clarify_path(self, mock_pipeline, client):
        """测试 clarify 路径：模糊问题返回追问"""

        # 模拟信息不完整的结果
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
            "clarification_question": "请提供要分析的时间范围，例如：本月、上季度、2026年7月。",
            "validation_errors": []
        }

        # 发送模糊问题
        response = client.post("/api/v1/analysis/run", json={
            "question": "分析转化率",
            "conversation_id": "test-002"
        })

        # 验证响应
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "clarify"
        assert data["conversation_id"] == "test-002"
        assert data["task_id"] == "task-1"
        assert "clarification_question" in data
        assert len(data["clarification_question"]) > 0

    @patch("app.services.analysis_execution.run_analysis_pipeline")
    def test_failed_path(self, mock_pipeline, client):
        """测试 failed 路径：分析失败返回错误"""

        # 模拟分析失败的结果
        mock_pipeline.return_value = {
            "next_action": "error",
            "errors": ["模型调用失败", "证据校验未通过"],
            "parsed_problem": None,
            "key_findings": [],
            "matched_events": [],
            "report_final": None,
            "report_draft": None,
            "evidence": {},
            "analysis_result": {},
            "clarification_question": None,
            "validation_errors": []
        }

        # 发送请求
        response = client.post("/api/v1/analysis/run", json={
            "question": "为什么转化率下降？",
            "conversation_id": "test-003"
        })

        # 验证响应
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert data["conversation_id"] == "test-003"
        assert data["task_id"] == "task-1"
        assert len(data["errors"]) > 0

    def test_empty_question(self, client):
        """测试空问题"""
        response = client.post("/api/v1/analysis/run", json={
            "question": "",
            "conversation_id": "test-004"
        })
        # 空问题应该返回422验证错误
        assert response.status_code == 422

    @patch("app.services.analysis_execution.run_analysis_pipeline")
    def test_report_with_validation_errors(self, mock_pipeline, client):
        """证据校验失败时，草稿不能作为完成报告返回。"""

        # 模拟有报告但校验有问题的结果
        mock_pipeline.return_value = {
            "next_action": "end",
            "errors": [],
            "parsed_problem": "为什么转化率下降？",
            "key_findings": [{"dimension": "渠道", "group": "douyin", "effect": -0.38}],
            "matched_events": [],
            "report_final": None,  # 没有最终报告
            "report_draft": "# 报告草稿\n\n转化率下降...",
            "evidence": {},
            "analysis_result": {},
            "clarification_question": None,
            "validation_errors": ["报告中的'配送延迟'没有对应证据"]
        }

        response = client.post("/api/v1/analysis/run", json={
            "question": "为什么转化率下降？",
            "conversation_id": "test-005"
        })

        # 应返回 failed，避免前端展示未经校验的报告草稿。
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert data["errors"] == ["报告中的'配送延迟'没有对应证据"]

    @patch("app.services.analysis_execution.run_analysis_pipeline")
    def test_history_endpoints_return_persisted_task(self, mock_pipeline, client):
        """任务完成后，可通过会话与任务接口取回历史结果。"""
        mock_pipeline.return_value = {
            "next_action": "end",
            "errors": [],
            "report_final": "# 已持久化报告",
            "key_findings": [],
            "analysis_result": {"current_funnel": {"order_rate": 0.0166}},
            "evidence": {"metrics": []},
            "matched_events": [],
        }

        run_response = client.post("/api/v1/analysis/run", json={"question": "历史回放测试"})
        data = run_response.json()

        conversations = client.get("/api/v1/conversations").json()
        assert conversations[0]["conversation_id"] == data["conversation_id"]
        assert conversations[0]["task_count"] == 1

        tasks = client.get(f"/api/v1/conversations/{data['conversation_id']}/tasks").json()
        assert tasks[0]["task_id"] == data["task_id"]

        detail = client.get(f"/api/v1/tasks/{data['task_id']}").json()
        assert detail["status"] == "completed"
        assert detail["report"] == "# 已持久化报告"

    def test_websocket_streams_progress_and_terminal_result(self, persistence, realtime_manager):
        """后台任务即使先完成，WebSocket 也能补发节点进度和最终结果。"""
        def fake_pipeline(*, user_question, conversation_id, conversation_history=None, on_progress=None):
            if on_progress:
                on_progress({"type": "node_started", "node": "parse_question", "label": "解析问题", "message": "开始解析"})
                on_progress({"type": "node_completed", "node": "parse_question", "label": "解析问题", "message": "解析完成"})
            return {
                "next_action": "end",
                "errors": [],
                "report_final": "# WebSocket 报告",
                "key_findings": [],
                "analysis_result": {"current_funnel": {"order_rate": 0.0166}},
                "evidence": {},
                "matched_events": [],
            }

        with patch("app.services.analysis_execution.run_analysis_pipeline", side_effect=fake_pipeline):
            with TestClient(app) as live_client:
                accepted = live_client.post("/api/v1/analysis/tasks", json={
                    "question": "请实时分析转化率",
                    "conversation_id": "websocket-test",
                })
                assert accepted.status_code == 202
                task_id = accepted.json()["task_id"]

                events = []
                with live_client.websocket_connect(f"/api/v1/analysis/tasks/{task_id}/stream") as websocket:
                    while True:
                        event = websocket.receive_json()
                        events.append(event)
                        if event["type"] == "terminal":
                            break

        assert any(event["type"] == "node_started" for event in events)
        terminal = events[-1]
        assert terminal["status"] == "completed"
        assert terminal["response"]["report"] == "# WebSocket 报告"


# ============================================================
# 独立运行
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
