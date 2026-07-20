"""LangGraph 同步节点向实时任务层报告进度的轻量上下文。"""

from contextvars import ContextVar, Token
from typing import Any, Callable


ProgressCallback = Callable[[dict[str, Any]], None]
_progress_callback: ContextVar[ProgressCallback | None] = ContextVar("analysis_progress_callback", default=None)


def set_progress_callback(callback: ProgressCallback | None) -> Token:
    """绑定当前分析线程的进度回调。"""
    return _progress_callback.set(callback)


def reset_progress_callback(token: Token) -> None:
    """清理当前分析线程的进度回调。"""
    _progress_callback.reset(token)


def emit_progress(event_type: str, **payload: Any) -> None:
    """尽力发送进度；展示层故障不能中断真实分析。"""
    callback = _progress_callback.get()
    if callback is None:
        return
    try:
        callback({"type": event_type, **payload})
    except Exception:
        pass
