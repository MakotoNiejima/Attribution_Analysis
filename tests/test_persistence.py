"""持久化服务测试：使用隔离 SQLite，不依赖真实 MySQL 或模型。"""

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.persistence.service import AnalysisPersistenceService


def build_service():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    service = AnalysisPersistenceService(engine)
    service.initialize_schema()
    return service


def test_completed_task_persists_result_and_history():
    service = build_service()
    task = service.create_task("conversation-1", "为什么转化率下降？")

    service.finish_task(
        task["task_id"],
        status="completed",
        report="# 分析报告",
        key_findings=[{"dimension": "渠道", "group": "organic", "effect": -0.006476}],
        analysis_result={"current_funnel": {"order_rate": 0.0166}},
        evidence={"metrics": [{"metric_name": "当前期整体转化率", "metric_value": 0.0166}]},
        matched_events=[{"title": "配送延迟"}],
    )

    conversations = service.list_conversations()
    assert conversations[0]["conversation_id"] == "conversation-1"
    assert conversations[0]["title"] == "为什么转化率下降？"
    assert conversations[0]["last_task_status"] == "completed"

    tasks = service.list_tasks("conversation-1")
    assert tasks[0]["status"] == "completed"

    detail = service.get_task(task["task_id"])
    assert detail["report"] == "# 分析报告"
    assert detail["key_findings"][0]["group"] == "organic"
    assert detail["analysis_result"]["current_funnel"]["order_rate"] == 0.0166
    assert detail["matched_events"][0]["title"] == "配送延迟"


def test_clarify_and_failed_tasks_do_not_create_final_results():
    service = build_service()
    clarify_task = service.create_task("conversation-2", "分析一下")
    failed_task = service.create_task("conversation-2", "为什么转化率下降？")

    service.finish_task(
        clarify_task["task_id"],
        status="clarify",
        clarification_question="请提供对比的时间范围。",
    )
    service.finish_task(
        failed_task["task_id"],
        status="failed",
        errors=["证据校验未通过"],
    )

    clarify_detail = service.get_task(clarify_task["task_id"])
    failed_detail = service.get_task(failed_task["task_id"])
    assert clarify_detail["clarification_question"] == "请提供对比的时间范围。"
    assert clarify_detail["report"] is None
    assert failed_detail["errors"] == ["证据校验未通过"]
    assert failed_detail["report"] is None


def test_conversation_context_uses_recent_tasks_and_excludes_current_task():
    service = build_service()
    first = service.create_task("conversation-3", "分析转化率")
    service.finish_task(
        first["task_id"],
        status="clarify",
        clarification_question="请提供对比时间范围。",
    )
    second = service.create_task("conversation-3", "比较 7 月和 6 月")
    service.finish_task(
        second["task_id"],
        status="completed",
        report="# 旧报告",
        key_findings=[{"dimension": "渠道", "group": "organic", "effect": -0.006476}],
    )
    current = service.create_task("conversation-3", "那设备维度呢？")

    context = service.get_conversation_context(
        "conversation-3",
        limit=2,
        exclude_task_id=current["task_id"],
    )

    assert [item["question"] for item in context] == ["分析转化率", "比较 7 月和 6 月"]
    assert context[0]["clarification_question"] == "请提供对比时间范围。"
    assert "organic" in context[1]["key_findings_summary"]
