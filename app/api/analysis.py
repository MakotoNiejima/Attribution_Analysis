"""经营归因分析、会话历史、任务回放与 WebSocket 进度接口。"""

from typing import Union

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool

from app.api.schemas import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisTaskAccepted,
    AnalysisTaskDetail,
    AnalysisTaskSummary,
    CancelledResponse,
    ClarifyResponse,
    CompletedResponse,
    ConversationSummary,
    FailedResponse,
)
from app.persistence.service import TaskNotFoundError, get_persistence_service
from app.realtime.manager import get_task_runtime_manager
from app.services.analysis_execution import execute_persisted_task


router = APIRouter(prefix="/api/v1", tags=["analysis"])


async def create_persisted_task(request: AnalysisRequest) -> dict:
    """在线程中创建数据库任务，避免阻塞事件循环。"""
    return await run_in_threadpool(
        get_persistence_service().create_task,
        request.conversation_id,
        request.question,
    )


@router.post(
    "/analysis/run",
    response_model=Union[ClarifyResponse, CompletedResponse, FailedResponse, CancelledResponse],
)
async def run_analysis(request: AnalysisRequest):
    """同步兼容接口：等待任务完成后一次性返回最终结果。"""
    task_id: str | None = None
    conversation_id = request.conversation_id
    try:
        task = await create_persisted_task(request)
        task_id = task["task_id"]
        conversation_id = task["conversation_id"]
        return await run_in_threadpool(
            execute_persisted_task,
            task_id=task_id,
            conversation_id=conversation_id,
            question=request.question,
        )
    except Exception as exc:
        return FailedResponse(
            conversation_id=conversation_id or request.conversation_id or "unpersisted",
            task_id=task_id,
            errors=[f"接口异常: {str(exc)}"],
        )


@router.post("/analysis/tasks", response_model=AnalysisTaskAccepted, status_code=202)
async def create_analysis_task(request: AnalysisRequest):
    """创建后台分析任务；前端随后连接 task_id 对应的 WebSocket。"""
    task = await create_persisted_task(request)
    task_id = task["task_id"]
    conversation_id = task["conversation_id"]

    def worker(on_progress):
        response = execute_persisted_task(
            task_id=task_id,
            conversation_id=conversation_id,
            question=request.question,
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
            errors=[f"后台任务启动失败: {str(exc)}"],
        )
        raise HTTPException(status_code=503, detail="后台任务启动失败") from exc

    return AnalysisTaskAccepted(task_id=task_id, conversation_id=conversation_id)


@router.websocket("/analysis/tasks/{task_id}/stream")
async def stream_analysis_task(websocket: WebSocket, task_id: str):
    """补发已有进度，并持续推送实时节点事件，直到收到终态。"""
    await websocket.accept()
    try:
        detail = await run_in_threadpool(get_persistence_service().get_task, task_id)
    except TaskNotFoundError:
        await websocket.send_json({"type": "stream_error", "message": "任务不存在"})
        await websocket.close(code=4404)
        return
    except Exception:
        await websocket.send_json({"type": "stream_error", "message": "无法读取任务状态"})
        await websocket.close(code=1011)
        return

    manager = get_task_runtime_manager()
    subscription = await manager.subscribe(task_id)
    # 任务刚完成但仍在本进程缓存中时，优先补发完整过程事件。
    if subscription is not None:
        try:
            await websocket.send_json({"type": "connected", "task_id": task_id})
            for event in subscription.history:
                await websocket.send_json(event)
                if event.get("type") == "terminal":
                    await websocket.close(code=1000)
                    return

            while True:
                event = await subscription.queue.get()
                await websocket.send_json(event)
                if event.get("type") == "terminal":
                    await websocket.close(code=1000)
                    return
        except WebSocketDisconnect:
            # 用户关闭页面时，后台线程继续运行并写入 MySQL。
            pass
        finally:
            await manager.unsubscribe(task_id, subscription.queue)
        return

    # 服务重启后实时缓存不在，但已结束任务仍可通过持久化快照回放。
    if detail["status"] != "running":
        await websocket.send_json(jsonable_encoder({"type": "snapshot", "task": detail}))
        await websocket.close(code=1000)
        return

    if subscription is None:
        await websocket.send_json({
            "type": "stream_error",
            "message": "实时通道不存在；请刷新任务详情确认最终状态。",
        })
        await websocket.close(code=1011)
        return


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(limit: int = Query(default=30, ge=1, le=100)):
    """返回最近活跃会话，用于前端侧栏。"""
    try:
        return await run_in_threadpool(get_persistence_service().list_conversations, limit)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"会话历史暂不可用: {str(exc)}") from exc


@router.get(
    "/conversations/{conversation_id}/tasks",
    response_model=list[AnalysisTaskSummary],
)
async def list_conversation_tasks(
    conversation_id: str,
    limit: int = Query(default=50, ge=1, le=100),
):
    """返回一个会话中的任务列表。"""
    try:
        return await run_in_threadpool(get_persistence_service().list_tasks, conversation_id, limit)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="会话不存在") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"任务历史暂不可用: {str(exc)}") from exc


@router.get("/tasks/{task_id}", response_model=AnalysisTaskDetail)
async def get_task(task_id: str):
    """读取一次任务的状态，以及已保存的最终分析结果。"""
    try:
        return await run_in_threadpool(get_persistence_service().get_task, task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"任务详情暂不可用: {str(exc)}") from exc
