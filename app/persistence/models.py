"""经营归因分析的持久化表模型。"""

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    """生成不带时区的 UTC 时间，和现有 MySQL 业务表保持一致。"""
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    """持久化模块的 SQLAlchemy 基类。"""


class AppUser(Base):
    """分析工作台用户；与业务明细表 biz_users 明确隔离。"""

    __tablename__ = "app_users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    external_user_id: Mapped[str | None] = mapped_column(String(120), nullable=True, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="analyst")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class AnalysisConversation(Base):
    """用户连续提问的会话容器。"""

    __tablename__ = "analysis_conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)

    tasks: Mapped[list["AnalysisTask"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
    )
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    context_summaries: Mapped[list["ContextSummary"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class AnalysisTask(Base):
    """一次分析请求从运行到结束的状态记录。"""

    __tablename__ = "analysis_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("analysis_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    current_node: Mapped[str | None] = mapped_column(String(64), nullable=True)
    clarification_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    errors_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)

    conversation: Mapped[AnalysisConversation] = relationship(back_populates="tasks")
    result: Mapped["AnalysisResult | None"] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        uselist=False,
    )
    logs: Mapped[list["TaskLog"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class AnalysisResult(Base):
    """仅保存已通过证据校验的最终分析结果。"""

    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("analysis_tasks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # 规范六段结构字段
    problem_definition: Mapped[str] = mapped_column(Text, nullable=False)
    key_metrics_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence_list_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    conclusion_text: Mapped[str] = mapped_column(Text, nullable=False)
    missing_data_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    next_action_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 兼容字段（保留原有数据）
    report: Mapped[str] = mapped_column(Text, nullable=False)
    key_findings_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    analysis_result_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evidence_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    matched_events_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    export_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)

    task: Mapped[AnalysisTask] = relationship(back_populates="result")


class ChatMessage(Base):
    """会话中的用户消息、追问和最终报告消息。"""

    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("analysis_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("analysis_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    message_type: Mapped[str] = mapped_column(String(32), nullable=False, default="text", index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)

    conversation: Mapped[AnalysisConversation] = relationship(back_populates="messages")


class Attachment(Base):
    """会话附件元数据；原文件按用户/会话目录保存在本地磁盘。"""

    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("analysis_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded")
    parse_summary_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)

    conversation: Mapped[AnalysisConversation] = relationship(back_populates="attachments")


class ContextSummary(Base):
    """长会话的压缩上下文，避免每轮传入全部历史。"""

    __tablename__ = "context_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("analysis_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)

    conversation: Mapped[AnalysisConversation] = relationship(back_populates="context_summaries")


class WebsocketToken(Base):
    """短期 WebSocket 鉴权令牌，绑定用户和单个任务。"""

    __tablename__ = "websocket_tokens"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("analysis_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class SystemConfig(Base):
    """可在运行期刷新读取的非敏感系统配置。"""

    __tablename__ = "system_configs"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class TaskLog(Base):
    """任务节点、工具和异常日志，用于排查和管理员查看。"""

    __tablename__ = "task_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("analysis_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)

    task: Mapped[AnalysisTask] = relationship(back_populates="logs")


Index("idx_analysis_tasks_conversation_created", AnalysisTask.conversation_id, AnalysisTask.created_at)
Index("idx_analysis_conversations_updated", AnalysisConversation.updated_at)
Index("idx_chat_messages_conversation_created", ChatMessage.conversation_id, ChatMessage.created_at)
Index("idx_attachments_conversation_created", Attachment.conversation_id, Attachment.created_at)
