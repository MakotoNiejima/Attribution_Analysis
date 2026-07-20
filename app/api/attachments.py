"""附件管理 API：上传、列表、查询、删除。"""

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.attachments.engine import (
    aggregate_attachment,
    parse_and_store,
    preview_attachment,
    query_attachment,
)
from app.attachments.store import get_attachment_store
from app.auth.dependencies import get_current_user
from app.persistence.service import (
    ConversationAccessError,
    ConversationNotFoundError,
    TaskNotFoundError,
    get_persistence_service,
)
from app.storage import StoragePathError, save_upload, unlink_file

router = APIRouter(prefix="/api/v1/attachments", tags=["attachments"])

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".txt"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


# ================================================================
# 请求模型
# ================================================================

class QueryRequest(BaseModel):
    filters: Optional[dict[str, Any]] = None
    columns: Optional[list[str]] = None
    limit: int = 200


class AggregateRequest(BaseModel):
    group_by: str
    metrics: dict[str, str]  # {"col": "sum/avg/count/min/max"}
    filters: Optional[dict[str, Any]] = None


# ================================================================
# 端点
# ================================================================

@router.post("/upload")
async def upload_attachment(
    file: UploadFile = File(...),
    conversation_id: str = Form(...),
    current_user: dict = Depends(get_current_user),
):
    """上传附件，自动解析列信息和数据预览。"""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的格式: {suffix}（支持 {', '.join(sorted(ALLOWED_EXTENSIONS))}）",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"文件过大（最大 {MAX_FILE_SIZE // 1024 // 1024}MB）")
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="文件为空")

    try:
        persistence = get_persistence_service()
        await run_in_threadpool(
            persistence.ensure_conversation,
            conversation_id,
            current_user["user_id"],
        )
        dest = await run_in_threadpool(
            save_upload,
            content,
            user_id=current_user["user_id"],
            conversation_id=conversation_id,
            filename=file.filename or "attachment",
            category="structured",
        )
    except (ConversationAccessError, StoragePathError, ValueError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    try:
        result = await run_in_threadpool(
            parse_and_store, dest, conversation_id, file.filename
        )
        await run_in_threadpool(
            persistence.create_attachment,
            attachment_id=result["id"],
            conversation_id=conversation_id,
            owner_id=current_user["user_id"],
            filename=result["filename"],
            stored_path=str(dest),
            file_type=result["file_type"],
            file_size=result["file_size"],
            parse_status="parsed",
            parse_summary={
                "row_count": result["row_count"],
                "columns": result["columns"],
                "preview": result["preview"],
            },
        )
    except Exception as exc:
        if dest.exists():
            unlink_file(dest)
        raise HTTPException(status_code=422, detail=f"解析失败: {str(exc)}")

    return {
        "status": "ok",
        "message": f"附件已解析（{result['row_count']} 行 × {len(result['columns'])} 列）",
        "attachment": result,
    }


@router.get("")
async def list_attachments(conversation_id: str, current_user: dict = Depends(get_current_user)):
    """列出指定会话的附件。"""
    try:
        docs = await run_in_threadpool(
            get_persistence_service().list_attachments, conversation_id, current_user["user_id"]
        )
        return {"attachments": docs, "total": len(docs)}
    except (ConversationNotFoundError, ConversationAccessError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"查询失败: {str(exc)}")


@router.get("/{attachment_id}")
async def get_attachment_detail(attachment_id: str, current_user: dict = Depends(get_current_user)):
    """获取附件详情（含表头和预览）。"""
    try:
        await run_in_threadpool(
            get_persistence_service().get_attachment, attachment_id, current_user["user_id"]
        )
        detail = await run_in_threadpool(preview_attachment, attachment_id)
        return detail
    except (ValueError, TaskNotFoundError, ConversationAccessError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{attachment_id}/query")
async def query_attachment_data(
    attachment_id: str, request: QueryRequest, current_user: dict = Depends(get_current_user)
):
    """按条件筛选附件数据。"""
    try:
        await run_in_threadpool(
            get_persistence_service().get_attachment, attachment_id, current_user["user_id"]
        )
        result = await run_in_threadpool(
            query_attachment,
            attachment_id,
            filters=request.filters,
            columns=request.columns,
            limit=request.limit,
        )
        return result
    except (ValueError, TaskNotFoundError, ConversationAccessError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=410, detail=str(exc))


@router.post("/{attachment_id}/aggregate")
async def aggregate_attachment_data(
    attachment_id: str, request: AggregateRequest, current_user: dict = Depends(get_current_user)
):
    """分组聚合查询。"""
    try:
        await run_in_threadpool(
            get_persistence_service().get_attachment, attachment_id, current_user["user_id"]
        )
        result = await run_in_threadpool(
            aggregate_attachment,
            attachment_id,
            group_by=request.group_by,
            metrics=request.metrics,
            filters=request.filters,
        )
        return result
    except (ValueError, TaskNotFoundError, ConversationAccessError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=410, detail=str(exc))


@router.get("/{attachment_id}/download")
async def download_attachment(attachment_id: str, current_user: dict = Depends(get_current_user)):
    """下载原始附件；路径只从数据库受控字段读取。"""
    try:
        path, filename = await run_in_threadpool(
            get_persistence_service().get_attachment_path, attachment_id, current_user["user_id"]
        )
        if not Path(path).is_file():
            raise FileNotFoundError("原始附件缓存不存在")
        return FileResponse(path, filename=filename)
    except (TaskNotFoundError, ConversationAccessError, FileNotFoundError, StoragePathError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{attachment_id}")
async def delete_attachment(attachment_id: str, current_user: dict = Depends(get_current_user)):
    """删除附件。"""
    try:
        path = await run_in_threadpool(
            get_persistence_service().delete_attachment, attachment_id, current_user["user_id"]
        )
        deleted = await run_in_threadpool(get_attachment_store().delete, attachment_id)
        if not deleted:
            await run_in_threadpool(unlink_file, path)
            deleted = True
    except (TaskNotFoundError, ConversationAccessError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StoragePathError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"删除失败: {str(exc)}")

    if not deleted:
        raise HTTPException(status_code=404, detail="附件不存在")
    return {"status": "ok", "message": "附件已删除"}
