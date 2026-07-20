"""会话、任务与最终分析结果的数据库读写服务。"""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from typing import Any
from uuid import uuid4

from sqlalchemy import create_engine, func, inspect, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import build_sync_url
from app.persistence.models import (
    AnalysisConversation,
    AnalysisResult,
    AnalysisTask,
    AppUser,
    Attachment,
    Base,
    ChatMessage,
    ContextSummary,
    SystemConfig,
    TaskLog,
    WebsocketToken,
    utc_now,
)


class TaskNotFoundError(LookupError):
    """请求的任务不存在。"""


class ConversationNotFoundError(LookupError):
    """请求的会话不存在。"""


class ConversationAccessError(PermissionError):
    """当前用户不能访问该会话。"""


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def to_jsonable(value: Any) -> Any:
    """将 LangGraph 的结果转换为可稳定写入 MySQL JSON 字段的值。"""
    return json.loads(json.dumps(value, ensure_ascii=False, default=_json_default))


def question_title(question: str) -> str:
    """生成列表中展示的会话标题。"""
    compact = " ".join(question.split())
    return compact[:100] or "未命名分析会话"


@lru_cache(maxsize=1)
def get_persistence_engine() -> Engine:
    """创建并缓存持久化专用连接池。"""
    return create_engine(build_sync_url(), pool_pre_ping=True, future=True)


class AnalysisPersistenceService:
    """封装会话、任务与结果的生命周期。"""

    def __init__(self, engine: Engine | None = None):
        self.engine = engine or get_persistence_engine()
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)

    def initialize_schema(self) -> None:
        """创建缺失表，并为早期版本的三张持久化表补齐非破坏性列。"""
        self._migrate_legacy_columns()
        # 先补列，再让 SQLAlchemy 创建新增索引和关联表；否则旧 MySQL 表在
        # 建 owner_id 等新索引时会因列尚不存在而失败。
        Base.metadata.create_all(self.engine)

    def _migrate_legacy_columns(self) -> None:
        """只追加可空列或带默认值的列，兼容已经创建好的 MySQL 数据库。"""
        dialect = self.engine.dialect.name
        type_boolean = "BOOLEAN NOT NULL DEFAULT FALSE" if dialect == "mysql" else "BOOLEAN NOT NULL DEFAULT 0"
        additions = {
            "analysis_conversations": {
                "owner_id": "VARCHAR(64)",
                "status": "VARCHAR(16) NOT NULL DEFAULT 'active'",
                "last_message_at": "DATETIME",
            },
            "analysis_tasks": {
                "cancel_requested": type_boolean,
                "current_node": "VARCHAR(64)",
            },
            "analysis_results": {
                "export_path": "VARCHAR(500)",
                "exported_at": "DATETIME",
            },
        }
        inspector = inspect(self.engine)
        table_names = set(inspector.get_table_names())
        with self.engine.begin() as connection:
            for table_name, columns in additions.items():
                if table_name not in table_names:
                    continue
                existing = {column["name"] for column in inspector.get_columns(table_name)}
                for column_name, definition in columns.items():
                    if column_name not in existing:
                        connection.execute(
                            text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
                        )

    def fail_interrupted_tasks(self) -> int:
        """服务启动后收束上次进程异常退出时遗留的 running 任务。"""
        now = utc_now()
        reason = ["服务在任务执行期间重启，请重新发起分析。"]
        with self.session_factory.begin() as session:
            result = session.execute(
                update(AnalysisTask)
                .where(AnalysisTask.status == "running")
                .values(
                    status="failed",
                    errors_json=reason,
                    finished_at=now,
                    updated_at=now,
                )
            )
        return result.rowcount or 0

    def create_task(
        self,
        conversation_id: str | None,
        question: str,
        *,
        owner_id: str | None = None,
    ) -> dict[str, Any]:
        """创建会话（如有必要）和一条正在运行的任务。"""
        resolved_conversation_id = conversation_id or str(uuid4())
        now = utc_now()
        task = AnalysisTask(
            id=str(uuid4()),
            conversation_id=resolved_conversation_id,
            question=question,
            status="running",
            errors_json=[],
            started_at=now,
            created_at=now,
            updated_at=now,
        )

        with self.session_factory.begin() as session:
            conversation = session.get(AnalysisConversation, resolved_conversation_id)
            if conversation is None:
                conversation = AnalysisConversation(
                    id=resolved_conversation_id,
                    owner_id=owner_id,
                    title=question_title(question),
                    status="active",
                    last_message_at=now,
                    created_at=now,
                    updated_at=now,
                )
                session.add(conversation)
            else:
                self._assert_conversation_access(conversation, owner_id)
                if conversation.status != "active":
                    raise ValueError("该会话已归档或删除，不能继续发起分析")
                conversation.updated_at = now
                conversation.last_message_at = now
            session.add(task)
            session.add(
                ChatMessage(
                    id=str(uuid4()),
                    conversation_id=resolved_conversation_id,
                    task_id=task.id,
                    user_id=owner_id,
                    role="user",
                    content=question,
                    metadata_json={},
                    created_at=now,
                )
            )

        return self._task_summary(task)

    def finish_task(
        self,
        task_id: str,
        *,
        status: str,
        clarification_question: str | None = None,
        errors: list[str] | None = None,
        report: str | None = None,
        key_findings: list[dict[str, Any]] | None = None,
        analysis_result: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
        matched_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """将运行中任务收束为澄清、成功或失败状态。"""
        if status not in {"clarify", "completed", "failed", "cancelled"}:
            raise ValueError(f"不支持的任务终态: {status}")

        now = utc_now()
        with self.session_factory.begin() as session:
            task = session.get(AnalysisTask, task_id)
            if task is None:
                raise TaskNotFoundError(task_id)

            task.status = status
            task.clarification_question = clarification_question if status == "clarify" else None
            task.errors_json = to_jsonable(errors or [])
            task.finished_at = now
            task.updated_at = now
            task.conversation.updated_at = now
            task.conversation.last_message_at = now

            if status == "completed":
                if not report:
                    raise ValueError("已完成任务必须保存最终报告")
                if task.result is not None:
                    session.delete(task.result)
                    session.flush()
                session.add(
                    AnalysisResult(
                        task_id=task.id,
                        report=report,
                        key_findings_json=to_jsonable(key_findings or []),
                        analysis_result_json=to_jsonable(analysis_result or {}),
                        evidence_json=to_jsonable(evidence or {}),
                        matched_events_json=to_jsonable(matched_events or []),
                        created_at=now,
                    )
                )

            assistant_content = self._assistant_message_content(
                status=status,
                report=report,
                clarification_question=clarification_question,
                errors=errors or [],
            )
            already_written = session.scalar(
                select(func.count())
                .select_from(ChatMessage)
                .where(ChatMessage.task_id == task.id, ChatMessage.role == "assistant")
            ) or 0
            if not already_written:
                session.add(
                    ChatMessage(
                        id=str(uuid4()),
                        conversation_id=task.conversation_id,
                        task_id=task.id,
                        user_id=None,
                        role="assistant",
                        content=assistant_content,
                        metadata_json={"status": status},
                        created_at=now,
                    )
                )
            session.add(
                TaskLog(
                    task_id=task.id,
                    level="error" if status == "failed" else "info",
                    event_type="task_finished",
                    message=f"任务状态变更为 {status}",
                    payload_json={"status": status},
                    created_at=now,
                )
            )

        return self.get_task(task_id)

    def list_conversations(self, limit: int = 30, owner_id: str | None = None) -> list[dict[str, Any]]:
        """按最近活跃时间返回会话列表。"""
        normalized_limit = max(1, min(limit, 100))
        with self.session_factory() as session:
            statement = select(AnalysisConversation).where(AnalysisConversation.status != "deleted")
            if owner_id:
                statement = statement.where(AnalysisConversation.owner_id == owner_id)
            conversations = session.scalars(statement.order_by(AnalysisConversation.updated_at.desc()).limit(normalized_limit)).all()

            items = []
            for conversation in conversations:
                last_task = session.scalars(
                    select(AnalysisTask)
                    .where(AnalysisTask.conversation_id == conversation.id)
                    .order_by(AnalysisTask.created_at.desc())
                    .limit(1)
                ).first()
                task_count = session.scalar(
                    select(func.count()).select_from(AnalysisTask).where(
                        AnalysisTask.conversation_id == conversation.id
                    )
                ) or 0
                items.append({
                    "conversation_id": conversation.id,
                    "title": conversation.title,
                    "task_count": task_count,
                    "last_task_id": last_task.id if last_task else None,
                    "last_task_status": last_task.status if last_task else None,
                    "status": conversation.status,
                    "owner_id": conversation.owner_id,
                    "updated_at": conversation.updated_at,
                    "created_at": conversation.created_at,
                })
            return items

    def list_tasks(
        self, conversation_id: str, limit: int = 50, owner_id: str | None = None
    ) -> list[dict[str, Any]]:
        """返回一个会话内的任务历史，最新任务排在前面。"""
        normalized_limit = max(1, min(limit, 100))
        with self.session_factory() as session:
            exists = session.get(AnalysisConversation, conversation_id)
            if exists is None:
                raise ConversationNotFoundError(conversation_id)
            self._assert_conversation_access(exists, owner_id)
            tasks = session.scalars(
                select(AnalysisTask)
                .where(AnalysisTask.conversation_id == conversation_id)
                .order_by(AnalysisTask.created_at.desc())
                .limit(normalized_limit)
            ).all()
            return [self._task_summary(task) for task in tasks]

    def get_conversation_context(
        self,
        conversation_id: str,
        limit: int = 5,
        exclude_task_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """返回最近任务的上下文摘要，供多轮对话合并使用。

        每条记录包含 question、status、clarification_question 和
        已完成任务的关键结论截断（200 字以内），按时间正序排列。
        当前正在执行的任务可通过 exclude_task_id 排除，避免重复注入最新消息。
        """
        normalized_limit = max(1, min(limit, 20))
        with self.session_factory() as session:
            statement = select(AnalysisTask).where(AnalysisTask.conversation_id == conversation_id)
            if exclude_task_id:
                statement = statement.where(AnalysisTask.id != exclude_task_id)
            # 先取最近 N 条，再恢复为正序，避免长会话一直注入最早的旧上下文。
            tasks = list(session.scalars(
                statement
                .order_by(AnalysisTask.created_at.desc())
                .limit(normalized_limit)
            ).all())
            tasks.reverse()

            context: list[dict[str, Any]] = []
            for task in tasks:
                summary: str | None = None
                if task.status == "completed" and task.result:
                    findings = task.result.key_findings_json or []
                    parts = []
                    for f in findings[:3]:
                        dim = f.get("dimension", "")
                        group = f.get("group", "")
                        effect = f.get("effect", 0)
                        parts.append(f"{dim}-{group} 效应{effect*100:+.2f}%")
                    report_snippet = (task.result.report or "")[:200]
                    summary = "；".join(parts) if parts else report_snippet

                context.append({
                    "question": task.question,
                    "status": task.status,
                    "clarification_question": task.clarification_question,
                    "key_findings_summary": summary,
                })
            return context

    def get_task(self, task_id: str) -> dict[str, Any]:
        """读取任务详情；成功任务会一并读取结构化结果。"""
        with self.session_factory() as session:
            task = session.get(AnalysisTask, task_id)
            if task is None:
                raise TaskNotFoundError(task_id)

            result = task.result
            detail = self._task_summary(task)
            detail.update({
                "clarification_question": task.clarification_question,
                "errors": task.errors_json or [],
                "report": result.report if result else None,
                "key_findings": result.key_findings_json if result else [],
                "analysis_result": result.analysis_result_json if result else {},
                "evidence": result.evidence_json if result else {},
                "matched_events": result.matched_events_json if result else [],
                "export_available": bool(result and result.export_path),
            })
            return detail

    def get_task_for_user(self, task_id: str, owner_id: str | None) -> dict[str, Any]:
        with self.session_factory() as session:
            task = session.get(AnalysisTask, task_id)
            if task is None:
                raise TaskNotFoundError(task_id)
            self._assert_conversation_access(task.conversation, owner_id)
        return self.get_task(task_id)

    def request_task_cancel(self, task_id: str, owner_id: str | None = None) -> dict[str, Any]:
        with self.session_factory.begin() as session:
            task = session.get(AnalysisTask, task_id)
            if task is None:
                raise TaskNotFoundError(task_id)
            self._assert_conversation_access(task.conversation, owner_id)
            if task.status != "running":
                return self._task_summary(task)
            task.cancel_requested = True
            task.updated_at = utc_now()
            session.add(
                TaskLog(
                    task_id=task.id,
                    level="info",
                    event_type="cancel_requested",
                    message="用户请求取消任务",
                    payload_json={},
                    created_at=utc_now(),
                )
            )
            return self._task_summary(task)

    def is_task_cancel_requested(self, task_id: str) -> bool:
        with self.session_factory() as session:
            task = session.get(AnalysisTask, task_id)
            return bool(task and task.cancel_requested)

    def save_export_path(self, task_id: str, path: str) -> None:
        with self.session_factory.begin() as session:
            task = session.get(AnalysisTask, task_id)
            if task is None or task.result is None:
                raise TaskNotFoundError(task_id)
            task.result.export_path = path
            task.result.exported_at = utc_now()

    def get_or_create_user(
        self,
        username: str,
        display_name: str | None = None,
        role: str = "analyst",
    ) -> dict[str, Any]:
        normalized = username.strip().lower()
        if not normalized:
            raise ValueError("用户名不能为空")
        now = utc_now()
        with self.session_factory.begin() as session:
            user = session.scalar(select(AppUser).where(AppUser.username == normalized))
            if user is None:
                user = AppUser(
                    id=str(uuid4()),
                    username=normalized,
                    display_name=(display_name or normalized)[:120],
                    role=role if role in {"analyst", "admin"} else "analyst",
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                session.add(user)
            elif display_name and user.display_name != display_name[:120]:
                user.display_name = display_name[:120]
                user.updated_at = now
            return self._user_summary(user)

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            user = session.get(AppUser, user_id)
            return self._user_summary(user) if user and user.is_active else None

    def create_conversation(self, owner_id: str, title: str | None = None) -> dict[str, Any]:
        now = utc_now()
        with self.session_factory.begin() as session:
            self._require_active_user(session, owner_id)
            conversation = AnalysisConversation(
                id=str(uuid4()),
                owner_id=owner_id,
                title=(title or "新建分析会话").strip()[:200] or "新建分析会话",
                status="active",
                created_at=now,
                updated_at=now,
            )
            session.add(conversation)
            return self._conversation_summary(conversation, task_count=0, last_task=None)

    def ensure_conversation(
        self, conversation_id: str, owner_id: str | None, title: str | None = None
    ) -> dict[str, Any]:
        """为“先上传附件、后提问”的工作流创建空会话。"""
        now = utc_now()
        with self.session_factory.begin() as session:
            conversation = session.get(AnalysisConversation, conversation_id)
            if conversation is None:
                if owner_id:
                    self._require_active_user(session, owner_id)
                conversation = AnalysisConversation(
                    id=conversation_id,
                    owner_id=owner_id,
                    title=(title or "新建分析会话")[:200],
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
                session.add(conversation)
            else:
                self._assert_conversation_access(conversation, owner_id)
            return self._conversation_summary(conversation, task_count=0, last_task=None)

    def rename_conversation(self, conversation_id: str, owner_id: str, title: str) -> dict[str, Any]:
        cleaned_title = title.strip()[:200]
        if not cleaned_title:
            raise ValueError("会话标题不能为空")
        with self.session_factory.begin() as session:
            conversation = self._get_conversation_for_update(session, conversation_id, owner_id)
            conversation.title = cleaned_title
            conversation.updated_at = utc_now()
            return self._conversation_summary(conversation, task_count=None, last_task=None)

    def archive_conversation(self, conversation_id: str, owner_id: str) -> None:
        with self.session_factory.begin() as session:
            conversation = self._get_conversation_for_update(session, conversation_id, owner_id)
            conversation.status = "archived"
            conversation.updated_at = utc_now()

    def delete_conversation(self, conversation_id: str, owner_id: str) -> list[str]:
        """删除会话记录并返回需由文件层清理的附件绝对路径。"""
        with self.session_factory.begin() as session:
            conversation = self._get_conversation_for_update(session, conversation_id, owner_id)
            paths = [attachment.stored_path for attachment in conversation.attachments]
            session.delete(conversation)
            return paths

    def list_messages(
        self, conversation_id: str, owner_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        normalized_limit = max(1, min(limit, 300))
        with self.session_factory() as session:
            conversation = session.get(AnalysisConversation, conversation_id)
            if conversation is None:
                raise ConversationNotFoundError(conversation_id)
            self._assert_conversation_access(conversation, owner_id)
            messages = session.scalars(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .order_by(ChatMessage.created_at.asc())
                .limit(normalized_limit)
            ).all()
            return [
                {
                    "message_id": message.id,
                    "task_id": message.task_id,
                    "role": message.role,
                    "content": message.content,
                    "metadata": message.metadata_json or {},
                    "created_at": message.created_at,
                }
                for message in messages
            ]

    def create_attachment(
        self,
        *,
        attachment_id: str,
        conversation_id: str,
        owner_id: str | None,
        filename: str,
        stored_path: str,
        file_type: str,
        file_size: int,
        parse_status: str,
        parse_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.session_factory.begin() as session:
            conversation = self._get_conversation_for_update(session, conversation_id, owner_id)
            attachment = Attachment(
                id=attachment_id,
                conversation_id=conversation_id,
                owner_id=owner_id,
                filename=filename[:255],
                stored_path=stored_path,
                file_type=file_type[:32],
                file_size=file_size,
                parse_status=parse_status[:20],
                parse_summary_json=to_jsonable(parse_summary or {}),
                created_at=now,
                updated_at=now,
            )
            session.add(attachment)
            conversation.updated_at = now
            return self._attachment_summary(attachment)

    def list_attachments(self, conversation_id: str, owner_id: str | None = None) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            conversation = session.get(AnalysisConversation, conversation_id)
            if conversation is None:
                raise ConversationNotFoundError(conversation_id)
            self._assert_conversation_access(conversation, owner_id)
            attachments = session.scalars(
                select(Attachment)
                .where(Attachment.conversation_id == conversation_id)
                .order_by(Attachment.created_at.desc())
            ).all()
            return [self._attachment_summary(attachment) for attachment in attachments]

    def get_attachment(self, attachment_id: str, owner_id: str | None = None) -> dict[str, Any]:
        with self.session_factory() as session:
            attachment = session.get(Attachment, attachment_id)
            if attachment is None:
                raise TaskNotFoundError(attachment_id)
            self._assert_conversation_access(attachment.conversation, owner_id)
            return self._attachment_summary(attachment)

    def delete_attachment(self, attachment_id: str, owner_id: str | None = None) -> str:
        with self.session_factory.begin() as session:
            attachment = session.get(Attachment, attachment_id)
            if attachment is None:
                raise TaskNotFoundError(attachment_id)
            self._assert_conversation_access(attachment.conversation, owner_id)
            path = attachment.stored_path
            session.delete(attachment)
            return path

    def get_attachment_path(self, attachment_id: str, owner_id: str | None = None) -> tuple[str, str]:
        """返回已授权附件的内部文件路径和下载文件名，不用于列表响应。"""
        with self.session_factory() as session:
            attachment = session.get(Attachment, attachment_id)
            if attachment is None:
                raise TaskNotFoundError(attachment_id)
            self._assert_conversation_access(attachment.conversation, owner_id)
            return attachment.stored_path, attachment.filename

    def get_task_attachments(self, conversation_id: str) -> list[dict[str, Any]]:
        """供图节点读取；附件元数据仍由主数据库作为事实来源。"""
        with self.session_factory() as session:
            attachments = session.scalars(
                select(Attachment).where(Attachment.conversation_id == conversation_id)
            ).all()
            return [self._attachment_summary(attachment) for attachment in attachments]

    def log_task_event(
        self,
        task_id: str,
        event_type: str,
        message: str,
        *,
        payload: dict[str, Any] | None = None,
        level: str = "info",
    ) -> None:
        with self.session_factory.begin() as session:
            task = session.get(AnalysisTask, task_id)
            if task is None:
                return
            if event_type == "node_started" and payload:
                task.current_node = str(payload.get("node") or "")[:64] or None
                task.updated_at = utc_now()
            session.add(
                TaskLog(
                    task_id=task_id,
                    level=level[:16],
                    event_type=event_type[:40],
                    message=message,
                    payload_json=to_jsonable(payload or {}),
                    created_at=utc_now(),
                )
            )

    def list_task_logs(self, task_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            if session.get(AnalysisTask, task_id) is None:
                raise TaskNotFoundError(task_id)
            logs = session.scalars(
                select(TaskLog)
                .where(TaskLog.task_id == task_id)
                .order_by(TaskLog.created_at.asc())
                .limit(max(1, min(limit, 500)))
            ).all()
            return [
                {
                    "level": log.level,
                    "event_type": log.event_type,
                    "message": log.message,
                    "payload": log.payload_json or {},
                    "created_at": log.created_at,
                }
                for log in logs
            ]

    def save_context_summary(self, conversation_id: str, summary: str, message_count: int) -> None:
        if not summary.strip():
            return
        with self.session_factory.begin() as session:
            if session.get(AnalysisConversation, conversation_id) is None:
                raise ConversationNotFoundError(conversation_id)
            session.add(
                ContextSummary(
                    conversation_id=conversation_id,
                    summary=summary.strip(),
                    message_count=message_count,
                    created_at=utc_now(),
                )
            )

    def set_system_config(self, key: str, value: str, updated_by: str | None = None) -> None:
        with self.session_factory.begin() as session:
            config = session.get(SystemConfig, key)
            if config is None:
                config = SystemConfig(key=key, value=value, updated_by=updated_by, updated_at=utc_now())
                session.add(config)
            else:
                config.value = value
                config.updated_by = updated_by
                config.updated_at = utc_now()

    def get_system_configs(self) -> dict[str, str]:
        with self.session_factory() as session:
            return {item.key: item.value for item in session.scalars(select(SystemConfig)).all()}

    def create_websocket_token(self, user_id: str, task_id: str, ttl_seconds: int = 300) -> str:
        token = str(uuid4())
        expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=max(30, min(ttl_seconds, 900)))
        with self.session_factory.begin() as session:
            task = session.get(AnalysisTask, task_id)
            if task is None:
                raise TaskNotFoundError(task_id)
            self._assert_conversation_access(task.conversation, user_id)
            session.add(WebsocketToken(id=token, user_id=user_id, task_id=task_id, expires_at=expires_at))
        return token

    def verify_websocket_token(self, token: str, user_id: str, task_id: str) -> bool:
        with self.session_factory() as session:
            record = session.get(WebsocketToken, token)
            return bool(
                record
                and record.user_id == user_id
                and record.task_id == task_id
                and record.expires_at >= utc_now()
            )

    def verify_websocket_token_for_task(self, token: str, task_id: str) -> bool:
        """WebSocket 使用短期能力令牌；令牌已在签发时绑定用户和任务。"""
        with self.session_factory() as session:
            record = session.get(WebsocketToken, token)
            return bool(record and record.task_id == task_id and record.expires_at >= utc_now())

    @staticmethod
    def _assistant_message_content(
        *, status: str, report: str | None, clarification_question: str | None, errors: list[str]
    ) -> str:
        if status == "completed":
            return report or "分析已完成。"
        if status == "clarify":
            return clarification_question or "请补充分析范围后重试。"
        if status == "cancelled":
            return "分析任务已取消。"
        return "分析未完成：" + ("；".join(errors) if errors else "未知错误")

    @staticmethod
    def _user_summary(user: AppUser) -> dict[str, Any]:
        return {
            "user_id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role,
            "is_active": user.is_active,
        }

    @staticmethod
    def _attachment_summary(attachment: Attachment) -> dict[str, Any]:
        return {
            "id": attachment.id,
            "conversation_id": attachment.conversation_id,
            "filename": attachment.filename,
            "file_type": attachment.file_type,
            "file_size": attachment.file_size,
            "parse_status": attachment.parse_status,
            "parse_summary": attachment.parse_summary_json or {},
            "created_at": attachment.created_at,
        }

    def _conversation_summary(
        self,
        conversation: AnalysisConversation,
        task_count: int | None,
        last_task: AnalysisTask | None,
    ) -> dict[str, Any]:
        return {
            "conversation_id": conversation.id,
            "title": conversation.title,
            "status": conversation.status,
            "owner_id": conversation.owner_id,
            "task_count": task_count if task_count is not None else 0,
            "last_task_id": last_task.id if last_task else None,
            "last_task_status": last_task.status if last_task else None,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
        }

    @staticmethod
    def _assert_conversation_access(conversation: AnalysisConversation, owner_id: str | None) -> None:
        if owner_id and conversation.owner_id and conversation.owner_id != owner_id:
            raise ConversationAccessError("该会话不属于当前用户")

    def _get_conversation_for_update(self, session: Session, conversation_id: str, owner_id: str | None) -> AnalysisConversation:
        conversation = session.get(AnalysisConversation, conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)
        self._assert_conversation_access(conversation, owner_id)
        return conversation

    @staticmethod
    def _require_active_user(session: Session, owner_id: str) -> AppUser:
        user = session.get(AppUser, owner_id)
        if user is None or not user.is_active:
            raise ConversationAccessError("当前用户不可用")
        return user

    @staticmethod
    def _task_summary(task: AnalysisTask) -> dict[str, Any]:
        return {
            "task_id": task.id,
            "conversation_id": task.conversation_id,
            "question": task.question,
            "status": task.status,
            "cancel_requested": task.cancel_requested,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "finished_at": task.finished_at,
        }


@lru_cache(maxsize=1)
def get_persistence_service() -> AnalysisPersistenceService:
    """提供给 FastAPI 路由调用的服务实例。"""
    return AnalysisPersistenceService()
