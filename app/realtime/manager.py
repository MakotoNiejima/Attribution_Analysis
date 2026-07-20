"""单进程 WebSocket 任务事件代理。

任务结果仍以 MySQL 为事实来源；本模块只保留短期实时进度，供浏览器订阅。
"""

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Callable


Worker = Callable[[Callable[[dict[str, Any]], None]], dict[str, Any]]


@dataclass
class TaskChannel:
    """一个后台任务的事件缓存与订阅者集合。"""

    history: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=100))
    subscribers: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)
    worker: asyncio.Task | None = None


@dataclass
class TaskSubscription:
    """订阅建立时的补发事件和后续事件队列。"""

    queue: asyncio.Queue[dict[str, Any]]
    history: list[dict[str, Any]]


class TaskRuntimeManager:
    """将同步分析放入线程，并把进度安全转发至 FastAPI 事件循环。"""

    def __init__(self):
        self._channels: dict[str, TaskChannel] = {}

    async def start_task(self, task_id: str, worker: Worker) -> None:
        """启动后台分析。相同任务不会被重复启动。"""
        channel = self._channels.get(task_id)
        if channel and channel.worker and not channel.worker.done():
            raise ValueError("任务已在运行中")

        channel = TaskChannel()
        self._channels[task_id] = channel
        channel.worker = asyncio.create_task(self._run_task(task_id, worker), name=f"analysis-task-{task_id}")

    async def _run_task(self, task_id: str, worker: Worker) -> None:
        loop = asyncio.get_running_loop()
        self.publish(task_id, {"type": "task_started", "message": "任务已创建，正在进入分析流程"})

        def emit_from_worker(event: dict[str, Any]) -> None:
            try:
                loop.call_soon_threadsafe(self.publish, task_id, event)
            except RuntimeError:
                # 应用正在退出时事件循环可能已经关闭；不影响任务落库。
                pass

        try:
            response = await asyncio.to_thread(worker, emit_from_worker)
            self.publish(
                task_id,
                {
                    "type": "terminal",
                    "status": response["status"],
                    "response": response,
                    "message": "分析流程已结束",
                },
            )
        except Exception as exc:
            self.publish(
                task_id,
                {
                    "type": "terminal",
                    "status": "failed",
                    "message": f"后台任务异常: {str(exc)}",
                },
            )

    def publish(self, task_id: str, event: dict[str, Any]) -> None:
        """在 FastAPI 事件循环中广播一条事件。"""
        channel = self._channels.get(task_id)
        if channel is None:
            return

        payload = {
            "task_id": task_id,
            "timestamp": datetime.now(UTC).isoformat(),
            **event,
        }
        channel.history.append(payload)
        for queue in tuple(channel.subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(payload)

    async def subscribe(self, task_id: str) -> TaskSubscription | None:
        """订阅任务，并补发连接建立前的进度事件。"""
        channel = self._channels.get(task_id)
        if channel is None:
            return None
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        channel.subscribers.add(queue)
        return TaskSubscription(queue=queue, history=list(channel.history))

    async def unsubscribe(self, task_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        channel = self._channels.get(task_id)
        if channel:
            channel.subscribers.discard(queue)

    async def shutdown(self) -> None:
        """停止等待中的协程；运行中的线程会随进程退出而结束。"""
        workers = [channel.worker for channel in self._channels.values() if channel.worker and not channel.worker.done()]
        for worker in workers:
            worker.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)


@lru_cache(maxsize=1)
def get_task_runtime_manager() -> TaskRuntimeManager:
    return TaskRuntimeManager()
