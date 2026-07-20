"""一次已持久化分析任务的同步执行与终态保存。"""

from typing import Any, Callable

from app.agent.graph import run_analysis_pipeline
from app.api.schemas import (
    AnalysisResponse,
    CancelledResponse,
    ClarifyResponse,
    CompletedResponse,
    FailedResponse,
)
from app.persistence.service import get_persistence_service


def build_analysis_response(
    result: dict[str, Any],
    *,
    conversation_id: str,
    task_id: str,
) -> AnalysisResponse:
    """将 LangGraph 最终状态映射为 API 的三种业务响应。"""
    next_action = result.get("next_action", "unknown")
    errors = result.get("errors", [])

    if next_action == "clarify" or (
        not result.get("report_final") and result.get("clarification_question")
    ):
        return ClarifyResponse(
            conversation_id=conversation_id,
            task_id=task_id,
            clarification_question=result.get(
                "clarification_question",
                "请提供更多信息：您想分析什么指标？时间范围是什么？",
            ),
        )
    if errors and not result.get("report_final"):
        return FailedResponse(conversation_id=conversation_id, task_id=task_id, errors=errors)
    if result.get("report_final"):
        return CompletedResponse(
            conversation_id=conversation_id,
            task_id=task_id,
            report=result["report_final"],
            key_findings=result.get("key_findings", []),
            analysis_result=result.get("analysis_result", {}),
            evidence=result.get("evidence", {}),
            matched_events=result.get("matched_events", []),
        )
    return FailedResponse(
        conversation_id=conversation_id,
        task_id=task_id,
        errors=errors or result.get("validation_errors") or ["分析流程异常结束"],
    )


class TaskCancelledError(RuntimeError):
    """任务在可安全中断的节点边界收到取消请求。"""


def persist_terminal_response(response: AnalysisResponse) -> None:
    """按终态写入任务；未经证据校验的草稿绝不写入结果表。"""
    service = get_persistence_service()
    if isinstance(response, CompletedResponse):
        service.finish_task(
            response.task_id,
            status="completed",
            report=response.report,
            key_findings=response.key_findings,
            analysis_result=response.analysis_result,
            evidence=response.evidence,
            matched_events=response.matched_events,
        )
    elif isinstance(response, ClarifyResponse):
        service.finish_task(
            response.task_id,
            status="clarify",
            clarification_question=response.clarification_question,
        )
    elif isinstance(response, CancelledResponse):
        service.finish_task(response.task_id, status="cancelled")
    else:
        service.finish_task(response.task_id, status="failed", errors=response.errors)


def execute_persisted_task(
    *,
    task_id: str,
    conversation_id: str,
    question: str,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> AnalysisResponse:
    """运行图、发送进度并持久化最终结果。"""
    service = get_persistence_service()
    try:
        cancellation_checker = getattr(service, "is_task_cancel_requested", None)
        if cancellation_checker and cancellation_checker(task_id):
            raise TaskCancelledError()
        conversation_history = service.get_conversation_context(
            conversation_id,
            exclude_task_id=task_id,
        )
        attachment_loader = getattr(service, "get_task_attachments", None)
        attachments = attachment_loader(conversation_id) if attachment_loader else []

        def report_progress(event: dict[str, Any]) -> None:
            if cancellation_checker and cancellation_checker(task_id):
                raise TaskCancelledError()
            logger = getattr(service, "log_task_event", None)
            if logger:
                logger(
                    task_id,
                    str(event.get("type", "progress")),
                    str(event.get("message") or event.get("label") or "任务进度更新"),
                    payload=event,
                )
            if on_progress:
                on_progress(event)

        logger = getattr(service, "log_task_event", None)
        if logger:
            logger(task_id, "task_started", "开始执行 LangGraph 分析流程")
        pipeline_kwargs: dict[str, Any] = dict(
            user_question=question,
            conversation_id=conversation_id,
            conversation_history=conversation_history,
            on_progress=report_progress,
        )
        # 空会话不传该可选参数，兼容已有的轻量测试替身和旧调用方。
        if attachments:
            pipeline_kwargs["attachments"] = attachments
        result = run_analysis_pipeline(**pipeline_kwargs)
        if cancellation_checker and cancellation_checker(task_id):
            raise TaskCancelledError()
        response = build_analysis_response(
            result,
            conversation_id=conversation_id,
            task_id=task_id,
        )
        persist_terminal_response(response)
        summary_writer = getattr(service, "save_context_summary", None)
        if summary_writer and response.status in {"completed", "clarify"}:
            if isinstance(response, CompletedResponse):
                summary = f"用户问题：{question}\n最终结论：{response.report[:600]}"
            else:
                summary = f"用户问题：{question}\n待补充：{response.clarification_question}"
            summary_writer(conversation_id, summary, len(conversation_history) + 2)
        return response
    except TaskCancelledError:
        response = CancelledResponse(conversation_id=conversation_id, task_id=task_id)
        try:
            persist_terminal_response(response)
        except Exception:
            pass
        return response
    except Exception as exc:
        response = FailedResponse(
            conversation_id=conversation_id,
            task_id=task_id,
            errors=[f"接口异常: {str(exc)}"],
        )
        try:
            service.finish_task(task_id, status="failed", errors=response.errors)
        except Exception:
            pass
        return response
