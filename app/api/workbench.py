"""课程工作台 API：授权会话、消息、任务控制、导出和运行期配置。"""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import app.config as app_config
from app.auth.dependencies import get_current_user, require_admin
from app.exports import write_markdown_export
from app.persistence.service import (
    ConversationAccessError,
    ConversationNotFoundError,
    TaskNotFoundError,
    get_persistence_service,
)
from app.realtime.manager import get_task_runtime_manager
from app.services.analysis_execution import execute_persisted_task
from app.storage import StoragePathError, export_path, remove_conversation_files


router = APIRouter(prefix="/api", tags=["workbench"])


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ConversationRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ConversationDeleteRequest(BaseModel):
    conversation_ids: list[str] = Field(min_length=1)


class ConversationUpdateRequest(BaseModel):
    conversation_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=200)


class AttachmentDeleteRequest(BaseModel):
    attachment_id: str = Field(min_length=1)


class MessageCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=1000)


class WsTokenRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=64)


class ConfigUpdateRequest(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    value: str = Field(max_length=4000)


async def _start_task(*, task_id: str, conversation_id: str, question: str) -> None:
    def worker(on_progress: Any):
        response = execute_persisted_task(
            task_id=task_id,
            conversation_id=conversation_id,
            question=question,
            on_progress=on_progress,
        )
        return response.model_dump(mode="json")

    try:
        await get_task_runtime_manager().start_task(task_id, worker)
    except Exception as exc:
        await run_in_threadpool(
            get_persistence_service().finish_task,
            task_id,
            status="failed",
            errors=[f"后台任务启动失败: {exc}"],
        )
        raise HTTPException(status_code=503, detail="后台任务启动失败") from exc


@router.post("/chat/create")
async def create_chat(
    request: ConversationCreateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
):
    return await run_in_threadpool(
        get_persistence_service().create_conversation,
        current_user["user_id"],
        request.title,
    )


@router.get("/chat/ls")
async def list_chats(
    limit: int = Query(default=30, ge=1, le=100),
    current_user: dict[str, Any] = Depends(get_current_user),
):
    return await run_in_threadpool(
        get_persistence_service().list_conversations,
        limit,
        current_user["user_id"],
    )


@router.get("/chat/ls/{conversation_id}")
async def get_chat(conversation_id: str, current_user: dict[str, Any] = Depends(get_current_user)):
    service = get_persistence_service()
    try:
        messages = await run_in_threadpool(service.list_messages, conversation_id, current_user["user_id"])
        tasks = await run_in_threadpool(service.list_tasks, conversation_id, 100, current_user["user_id"])
        attachments = await run_in_threadpool(service.list_attachments, conversation_id, current_user["user_id"])
        return {"conversation_id": conversation_id, "messages": messages, "tasks": tasks, "attachments": attachments}
    except (ConversationNotFoundError, ConversationAccessError) as exc:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问") from exc


@router.patch("/chat/{conversation_id}")
async def rename_chat(
    conversation_id: str,
    request: ConversationRenameRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
):
    try:
        return await run_in_threadpool(
            get_persistence_service().rename_conversation,
            conversation_id,
            current_user["user_id"],
            request.title,
        )
    except (ConversationNotFoundError, ConversationAccessError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/chat/{conversation_id}")
async def delete_chat(conversation_id: str, current_user: dict[str, Any] = Depends(get_current_user)):
    try:
        paths = await run_in_threadpool(
            get_persistence_service().delete_conversation, conversation_id, current_user["user_id"]
        )
        # 逐文件清理用于兼容旧记录；目录清理覆盖导出和工作区。
        for path in paths:
            try:
                from app.storage import unlink_file
                await run_in_threadpool(unlink_file, path)
            except StoragePathError:
                # 旧版本附件在项目 uploads/ 下，数据库记录删掉即可，绝不越界删除。
                pass
        await run_in_threadpool(remove_conversation_files, current_user["user_id"], conversation_id)
        return {"status": "ok"}
    except (ConversationNotFoundError, ConversationAccessError) as exc:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问") from exc


@router.post("/chat/{conversation_id}/messages", status_code=202)
async def send_message(
    conversation_id: str,
    request: MessageCreateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
):
    try:
        task = await run_in_threadpool(
            get_persistence_service().create_task,
            conversation_id,
            request.content.strip(),
            owner_id=current_user["user_id"],
        )
        await _start_task(
            task_id=task["task_id"], conversation_id=conversation_id, question=request.content.strip()
        )
        return {"task_id": task["task_id"], "conversation_id": conversation_id, "status": "running"}
    except (ConversationNotFoundError, ConversationAccessError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/tasks/{task_id}")
async def get_authorized_task(task_id: str, current_user: dict[str, Any] = Depends(get_current_user)):
    try:
        return await run_in_threadpool(
            get_persistence_service().get_task_for_user, task_id, current_user["user_id"]
        )
    except (TaskNotFoundError, ConversationAccessError) as exc:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问") from exc


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, current_user: dict[str, Any] = Depends(get_current_user)):
    try:
        task = await run_in_threadpool(
            get_persistence_service().request_task_cancel, task_id, current_user["user_id"]
        )
        return {"status": "cancellation_requested", "task": task}
    except (TaskNotFoundError, ConversationAccessError) as exc:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问") from exc


@router.get("/tasks/{task_id}/logs")
async def get_task_logs(task_id: str, current_user: dict[str, Any] = Depends(get_current_user)):
    try:
        await run_in_threadpool(get_persistence_service().get_task_for_user, task_id, current_user["user_id"])
        return await run_in_threadpool(get_persistence_service().list_task_logs, task_id)
    except (TaskNotFoundError, ConversationAccessError) as exc:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问") from exc


@router.get("/results/{task_id}")
async def get_result(task_id: str, current_user: dict[str, Any] = Depends(get_current_user)):
    """返回分析结果，按规范六段结构格式"""
    service = get_persistence_service()
    try:
        task = await run_in_threadpool(service.get_task_for_user, task_id, current_user["user_id"])
        # 按需求文档 1.1.9 返回六段结构
        return {
            "problem_definition": task.get("problem_definition"),
            "key_metrics": task.get("key_metrics", []),
            "evidence_list": task.get("evidence_list", []),
            "conclusion_text": task.get("conclusion_text"),
            "missing_data_text": task.get("missing_data_text"),
            "next_action_text": task.get("next_action_text"),
        }
    except (TaskNotFoundError, ConversationAccessError) as exc:
        raise HTTPException(status_code=404, detail="结果不存在或无权访问") from exc


@router.get("/results/{task_id}/export")
async def export_result(task_id: str, current_user: dict[str, Any] = Depends(get_current_user)):
    service = get_persistence_service()
    try:
        task = await run_in_threadpool(service.get_task_for_user, task_id, current_user["user_id"])
        if task["task_status"] != "success" or not task.get("report"):
            raise HTTPException(status_code=409, detail="只有已完成且验证通过的分析结果可以导出")
        destination = export_path(
            user_id=current_user["user_id"],
            conversation_id=task["conversation_id"],
            task_id=task_id,
        )
        await run_in_threadpool(write_markdown_export, destination, task)
        await run_in_threadpool(service.save_export_path, task_id, str(destination))
        return FileResponse(destination, media_type="text/markdown", filename=f"analysis-{task_id}.md")
    except (TaskNotFoundError, ConversationAccessError) as exc:
        raise HTTPException(status_code=404, detail="结果不存在或无权访问") from exc


@router.post("/chat/ws-token")
async def create_ws_token(
    request: WsTokenRequest, current_user: dict[str, Any] = Depends(get_current_user)
):
    try:
        token = await run_in_threadpool(
            get_persistence_service().create_websocket_token,
            current_user["user_id"],
            request.task_id,
        )
        # 同时返回 websocket_token 和 token 以兼容不同前端实现
        return {
            "task_id": request.task_id,
            "websocket_token": token,
            "token": token,
            "expires_in": 300
        }
    except (TaskNotFoundError, ConversationAccessError) as exc:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问") from exc


def _chat_event(event: dict[str, Any]) -> list[dict[str, Any]]:
    """将原有节点进度兼容为课程约定的 WebSocket 事件类型。"""
    event_type = event.get("type")
    task_id = event.get("task_id", "")
    
    if event_type == "task_started":
        return [{
            "type": "task_status",
            "task_id": task_id,
            "task_status": "running",
            "current_step": event.get("node", "start"),
            "timestamp": event.get("timestamp")
        }]
    if event_type == "node_started":
        return [{
            "type": "tool_start",
            "task_id": task_id,
            "tool_name": event.get("node", ""),
            "timestamp": event.get("timestamp")
        }]
    if event_type == "node_completed":
        return [{
            "type": "tool_finish",
            "task_id": task_id,
            "tool_name": event.get("node", ""),
            "tool_result_summary": event.get("result_summary", "执行完成"),
            "timestamp": event.get("timestamp")
        }]
    if event_type == "message_delta":
        return [{
            "type": "message_delta",
            "task_id": task_id,
            "delta_text": event.get("delta_text", ""),
            "timestamp": event.get("timestamp")
        }]
    if event_type == "terminal":
        response = event.get("response") or {}
        task_status = response.get("task_status", event.get("status", "completed"))
        finished_at = response.get("finished_at", event.get("timestamp"))
        result_id = response.get("result_id", task_id)
        
        return [
            {
                "type": "result_ready",
                "task_id": task_id,
                "result_id": result_id,
                "timestamp": event.get("timestamp")
            },
            {
                "type": "done",
                "task_id": task_id,
                "task_status": task_status,
                "finished_at": finished_at,
                "timestamp": event.get("timestamp")
            },
        ]
    if event_type == "error":
        return [{
            "type": "error",
            "task_id": task_id,
            "error_message": event.get("message", "未知错误"),
            "timestamp": event.get("timestamp")
        }]
    return [event]


@router.websocket("/chat/ws/chat")
async def stream_chat(
    websocket: WebSocket,
    task_id: str,
    websocket_token: str | None = None,
    token: str | None = None,
    conversation_id: str | None = None,
):
    """使用短期任务令牌订阅实时过程；过程事件与最终结果可断线后回放。
    
    支持两种参数名：websocket_token（规范）或 token（兼容旧版）。
    """
    # 兼容 websocket_token 和 token 两种参数名
    auth_token = websocket_token or token
    if not auth_token:
        await websocket.close(code=4401)
        return
    
    service = get_persistence_service()
    if not await run_in_threadpool(service.verify_websocket_token_for_task, auth_token, task_id):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    try:
        detail = await run_in_threadpool(service.get_task, task_id)
    except TaskNotFoundError:
        await websocket.send_json({"type": "error", "message": "任务不存在"})
        await websocket.close(code=4404)
        return

    await websocket.send_json({
        "type": "message_start",
        "task_id": task_id,
        "conversation_id": detail.get("conversation_id", "")
    })
    manager = get_task_runtime_manager()
    subscription = await manager.subscribe(task_id)
    if subscription is None:
        task_status = detail.get("task_status", detail.get("status", "unknown"))
        if task_status != "running":
            await websocket.send_json(jsonable_encoder({"type": "result_ready", "response": detail}))
            await websocket.send_json({
                "type": "done",
                "task_id": task_id,
                "finished_at": detail.get("finished_at")
            })
            await websocket.close(code=1000)
            return
        await websocket.send_json({"type": "error", "message": "实时进程已重启，请刷新任务状态"})
        await websocket.close(code=1011)
        return

    try:
        for event in subscription.history:
            for outgoing in _chat_event(event):
                await websocket.send_json(jsonable_encoder(outgoing))
            if event.get("type") == "terminal":
                await websocket.close(code=1000)
                return
        while True:
            event = await subscription.queue.get()
            for outgoing in _chat_event(event):
                await websocket.send_json(jsonable_encoder(outgoing))
            if event.get("type") == "terminal":
                await websocket.close(code=1000)
                return
    except WebSocketDisconnect:
        pass
    finally:
        await manager.unsubscribe(task_id, subscription.queue)


@router.post("/admin/reload")
async def reload_config(current_user: dict[str, Any] = Depends(get_current_user)):
    require_admin(current_user)
    app_config.reload_runtime_config()
    config = app_config.apply_runtime_overrides(get_persistence_service().get_system_configs())
    return {"status": "ok", "message": "配置已重载", "config": config}


@router.get("/admin/config")
async def list_config(current_user: dict[str, Any] = Depends(get_current_user)):
    require_admin(current_user)
    overrides = get_persistence_service().get_system_configs()
    app_config.reload_runtime_config()
    return {"runtime": app_config.apply_runtime_overrides(overrides), "overrides": overrides}


@router.put("/admin/config")
async def set_config(
    request: ConfigUpdateRequest, current_user: dict[str, Any] = Depends(get_current_user)
):
    require_admin(current_user)
    await run_in_threadpool(
        get_persistence_service().set_system_config,
        request.key,
        request.value,
        current_user["user_id"],
    )
    runtime = app_config.apply_runtime_overrides({request.key: request.value})
    return {"status": "ok", "key": request.key, "runtime": runtime}


# ============================================================
# 规范接口兼容层（1.1.9 接口要求）
# ============================================================

@router.post("/chat/delete")
async def delete_chats_batch(
    request: ConversationDeleteRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
):
    """批量删除会话（兼容规范接口）"""
    deleted_count = 0
    for conversation_id in request.conversation_ids:
        try:
            paths = await run_in_threadpool(
                get_persistence_service().delete_conversation, conversation_id, current_user["user_id"]
            )
            for path in paths:
                try:
                    from app.storage import unlink_file
                    await run_in_threadpool(unlink_file, path)
                except StoragePathError:
                    pass
            await run_in_threadpool(remove_conversation_files, current_user["user_id"], conversation_id)
            deleted_count += 1
        except (ConversationNotFoundError, ConversationAccessError):
            continue
    return {"status": "ok", "deleted_count": deleted_count}


@router.post("/chat/update")
async def update_chat(
    request: ConversationUpdateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
):
    """更新会话标题（兼容规范接口）"""
    try:
        return await run_in_threadpool(
            get_persistence_service().rename_conversation,
            request.conversation_id,
            current_user["user_id"],
            request.title,
        )
    except (ConversationNotFoundError, ConversationAccessError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/attachment/delete")
async def delete_attachment_compat(
    request: AttachmentDeleteRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
):
    """删除附件（兼容规范接口）"""
    from app.api.attachments import delete_attachment as _delete
    return await _delete(request.attachment_id, current_user)


@router.get("/attachment/get")
async def get_attachment_compat(
    attachment_id: str = Query(...),
    current_user: dict[str, Any] = Depends(get_current_user),
):
    """获取附件信息（兼容规范接口）"""
    from app.api.attachments import get_attachment_detail
    return await get_attachment_detail(attachment_id, current_user)


@router.post("/attachment/upload")
async def upload_attachment_compat(
    file: UploadFile = File(...),
    conversation_id: str = Form(...),
    current_user: dict[str, Any] = Depends(get_current_user),
):
    """上传附件（兼容规范接口）"""
    from app.api.attachments import upload_attachment as _upload
    result = await _upload(file, conversation_id, current_user)
    # 返回符合规范格式的响应
    attachment = result.get("attachment", {})
    return {
        "attachment_id": attachment.get("id"),
        "file_name": attachment.get("filename"),
        "file_path": attachment.get("stored_path"),
        "status": "ok",
        "message": result.get("message", ""),
    }
