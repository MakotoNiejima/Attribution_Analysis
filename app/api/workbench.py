"""课程工作台 API：授权会话、消息、任务控制、导出和运行期配置。"""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
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
    return await get_authorized_task(task_id, current_user)


@router.get("/results/{task_id}/export")
async def export_result(task_id: str, current_user: dict[str, Any] = Depends(get_current_user)):
    service = get_persistence_service()
    try:
        task = await run_in_threadpool(service.get_task_for_user, task_id, current_user["user_id"])
        if task["status"] != "success" or not task.get("report"):
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
        return {"task_id": request.task_id, "token": token, "expires_in": 300}
    except (TaskNotFoundError, ConversationAccessError) as exc:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问") from exc


def _chat_event(event: dict[str, Any]) -> list[dict[str, Any]]:
    """将原有节点进度兼容为课程约定的 WebSocket 事件类型。"""
    event_type = event.get("type")
    if event_type == "task_started":
        return [{**event, "type": "task_status", "status": "running"}]
    if event_type == "node_started":
        return [{**event, "type": "tool_start"}]
    if event_type == "node_completed":
        return [{**event, "type": "tool_finish"}]
    if event_type == "terminal":
        response = event.get("response") or {}
        return [
            {**event, "type": "result_ready", "response": response},
            {**event, "type": "done", "status": response.get("status", event.get("status"))},
        ]
    return [event]


@router.websocket("/chat/ws/chat")
async def stream_chat(websocket: WebSocket, task_id: str, token: str):
    """使用短期任务令牌订阅实时过程；过程事件与最终结果可断线后回放。"""
    service = get_persistence_service()
    if not await run_in_threadpool(service.verify_websocket_token_for_task, token, task_id):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    try:
        detail = await run_in_threadpool(service.get_task, task_id)
    except TaskNotFoundError:
        await websocket.send_json({"type": "error", "message": "任务不存在"})
        await websocket.close(code=4404)
        return

    await websocket.send_json({"type": "message_start", "task_id": task_id})
    manager = get_task_runtime_manager()
    subscription = await manager.subscribe(task_id)
    if subscription is None:
        if detail["status"] != "running":
            await websocket.send_json(jsonable_encoder({"type": "result_ready", "response": detail}))
            await websocket.send_json({"type": "done", "status": detail["status"]})
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
    return {"status": "ok", "config": config}


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
