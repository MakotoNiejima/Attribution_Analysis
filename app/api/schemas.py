"""
Pydantic 请求/响应模型
"""

from datetime import datetime
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field


# ============================================================
# 请求模型
# ============================================================

class AnalysisRequest(BaseModel):
    """分析请求"""
    question: str = Field(..., description="用户问题", min_length=1, max_length=1000)
    conversation_id: Optional[str] = Field(None, description="会话ID（可选）", min_length=1, max_length=64)


class AnalysisTaskAccepted(BaseModel):
    """后台任务已创建，客户端应通过 WebSocket 订阅后续进度。"""

    task_id: str
    conversation_id: str
    status: Literal["running"] = "running"


# ============================================================
# 响应模型
# ============================================================

class ClarifyResponse(BaseModel):
    """信息不完整，需要追问"""
    status: Literal["clarify"] = "clarify"
    conversation_id: str
    task_id: str
    clarification_question: str


class CompletedResponse(BaseModel):
    """分析成功"""
    status: Literal["success"] = "success"
    conversation_id: str
    task_id: str
    report: str
    key_findings: List[Dict[str, Any]] = Field(default_factory=list)
    analysis_result: Dict[str, Any] = Field(default_factory=dict)
    evidence: Dict[str, Any] = Field(default_factory=dict)
    matched_events: List[Dict[str, Any]] = Field(default_factory=list)


class FailedResponse(BaseModel):
    """分析失败"""
    status: Literal["failed"] = "failed"
    conversation_id: str
    task_id: Optional[str] = None
    errors: List[str] = Field(default_factory=list)


class CancelledResponse(BaseModel):
    """用户主动取消的任务。"""
    status: Literal["cancelled"] = "cancelled"
    conversation_id: str
    task_id: str
    message: str = "分析任务已取消"


# 统一响应类型
AnalysisResponse = ClarifyResponse | CompletedResponse | FailedResponse | CancelledResponse


# ============================================================
# 会话与任务历史
# ============================================================

TaskStatus = Literal["queued", "running", "clarify", "success", "failed", "cancelled"]


class ConversationSummary(BaseModel):
    """会话列表中的一项。"""

    conversation_id: str
    title: str
    task_count: int
    last_task_id: Optional[str] = None
    last_task_status: Optional[TaskStatus] = None
    created_at: datetime
    updated_at: datetime


class AnalysisTaskSummary(BaseModel):
    """会话内的一条任务记录。"""

    task_id: str
    conversation_id: str
    question: str
    status: TaskStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class AnalysisTaskDetail(AnalysisTaskSummary):
    """任务详情；成功任务带有可回放的结构化结果。"""

    clarification_question: Optional[str] = None
    errors: List[str] = Field(default_factory=list)
    report: Optional[str] = None
    key_findings: List[Dict[str, Any]] = Field(default_factory=list)
    analysis_result: Dict[str, Any] = Field(default_factory=dict)
    evidence: Dict[str, Any] = Field(default_factory=dict)
    matched_events: List[Dict[str, Any]] = Field(default_factory=list)
