"""工作台新增能力：本地认证、消息持久化、附件、实时任务与导出。"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

import app.config as app_config
from app.main import app
from app.persistence.service import AnalysisPersistenceService
from app.realtime.manager import TaskRuntimeManager


@pytest.fixture
def workbench_client(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'workbench.sqlite'}")
    service = AnalysisPersistenceService(engine)
    manager = TaskRuntimeManager()

    monkeypatch.setattr(app_config, "AUTH_REQUIRED", False)
    monkeypatch.setattr(app_config, "APP_STORAGE_ROOT", tmp_path / "runtime")
    monkeypatch.setattr("app.persistence.service.get_persistence_service", lambda: service)
    monkeypatch.setattr("app.auth.dependencies.get_persistence_service", lambda: service)
    monkeypatch.setattr("app.api.auth.get_persistence_service", lambda: service)
    monkeypatch.setattr("app.api.workbench.get_persistence_service", lambda: service)
    monkeypatch.setattr("app.api.analysis.get_persistence_service", lambda: service)
    monkeypatch.setattr("app.api.attachments.get_persistence_service", lambda: service)
    monkeypatch.setattr("app.services.analysis_execution.get_persistence_service", lambda: service)
    monkeypatch.setattr("app.main.get_persistence_service", lambda: service)
    monkeypatch.setattr("app.api.workbench.get_task_runtime_manager", lambda: manager)

    import app.attachments.store as attachment_store
    monkeypatch.setattr(attachment_store, "_DB_PATH", tmp_path / "attachment-cache.sqlite")
    monkeypatch.setattr(attachment_store, "_UPLOAD_DIR", tmp_path / "legacy-upload-cache")
    monkeypatch.setattr(attachment_store, "_store", None)

    with TestClient(app) as client:
        yield client, service


def completed_graph_result(*, user_question, **_kwargs):
    return {
        "next_action": "end",
        "errors": [],
        "report_final": "# 经营归因报告\n\n## 归因结论\n渠道 organic 是主要影响项。",
        "key_findings": [{"dimension": "渠道", "group": "organic", "effect": -0.006}],
        "analysis_result": {
            "baseline_funnel": {"order_rate": 0.02, "visit_sessions": 100, "cart_sessions": 20, "order_sessions": 2},
            "current_funnel": {"order_rate": 0.014, "visit_sessions": 100, "cart_sessions": 15, "order_sessions": 1},
        },
        "evidence": {"metrics": [{"metric_name": "整体转化率", "metric_value": 0.014, "metric_unit": "%", "metric_period": "current"}]},
        "matched_events": [],
    }


def test_authenticated_chat_persists_messages_streams_and_exports(workbench_client):
    client, _ = workbench_client
    assert client.get("/auth/me").json()["username"] == app_config.DEV_DEFAULT_USERNAME

    conversation = client.post("/api/chat/create", json={"title": "测试归因会话"}).json()
    conversation_id = conversation["conversation_id"]

    with patch("app.services.analysis_execution.run_analysis_pipeline", side_effect=completed_graph_result):
        accepted = client.post(
            f"/api/chat/{conversation_id}/messages",
            json={"content": "请分析整体转化率下降"},
        )
        assert accepted.status_code == 202
        task_id = accepted.json()["task_id"]

        token = client.post("/api/chat/ws-token", json={"task_id": task_id}).json()["token"]
        event_types = []
        with client.websocket_connect(f"/api/chat/ws/chat?task_id={task_id}&token={token}") as websocket:
            while True:
                event = websocket.receive_json()
                event_types.append(event["type"])
                if event["type"] == "done":
                    break

    assert "message_start" in event_types
    assert "result_ready" in event_types
    replay = client.get(f"/api/chat/ls/{conversation_id}").json()
    assert [message["role"] for message in replay["messages"]] == ["user", "assistant"]
    assert replay["tasks"][0]["status"] == "completed"

    exported = client.get(f"/api/results/{task_id}/export")
    assert exported.status_code == 200, exported.text
    assert "关键指标" in exported.text
    assert "下一步行动" in exported.text


def test_attachment_is_scoped_to_conversation_and_can_be_downloaded(workbench_client):
    client, _ = workbench_client
    conversation = client.post("/api/chat/create", json={"title": "附件会话"}).json()
    conversation_id = conversation["conversation_id"]
    response = client.post(
        "/api/v1/attachments/upload",
        data={"conversation_id": conversation_id},
        files={"file": ("channel.csv", b"channel,value\norganic,12\npaid,8\n", "text/csv")},
    )
    assert response.status_code == 200
    attachment_id = response.json()["attachment"]["id"]

    listing = client.get("/api/v1/attachments", params={"conversation_id": conversation_id}).json()
    assert listing["attachments"][0]["filename"] == "channel.csv"
    assert listing["attachments"][0]["parse_summary"]["row_count"] == 2

    downloaded = client.get(f"/api/v1/attachments/{attachment_id}/download")
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"channel,value")
    assert client.delete(f"/api/v1/attachments/{attachment_id}").status_code == 200


def test_admin_can_apply_non_sensitive_runtime_override_immediately(workbench_client):
    client, _ = workbench_client
    login = client.post("/auth/login", json={"username": "course-admin", "role": "admin"})
    assert login.status_code == 200

    updated = client.put("/api/admin/config", json={"key": "LLM_MODEL", "value": "demo-model"})
    assert updated.status_code == 200
    assert updated.json()["runtime"]["llm_model"] == "demo-model"
    assert app_config.LLM_MODEL == "demo-model"
