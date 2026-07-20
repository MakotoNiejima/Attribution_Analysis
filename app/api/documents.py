"""文档管理 API：上传、列表、删除。"""

import shutil
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app.rag.store import get_rag_store

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

# 上传目录
UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads"

# 允许的文件类型
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xls", ".txt", ".md", ".csv"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """上传文档，自动解析、分块、编码并入库。"""
    # 检查文件类型
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {suffix}（支持 {', '.join(sorted(ALLOWED_EXTENSIONS))}）",
        )

    # 检查文件大小
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"文件过大（最大 {MAX_FILE_SIZE // 1024 // 1024}MB）")
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="文件为空")

    # 保存到本地
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPLOAD_DIR / file.filename
    dest.write_bytes(content)

    # 解析 + 入库
    try:
        result = await run_in_threadpool(get_rag_store().add_document, dest)
    except Exception as exc:
        # 入库失败时清理文件
        if dest.exists():
            dest.unlink()
        raise HTTPException(status_code=422, detail=f"文档处理失败: {str(exc)}")

    return {
        "status": "ok",
        "message": f"文档已上传并完成索引（{result['chunk_count']} 个片段）",
        "document": result,
    }


@router.get("")
async def list_documents():
    """列出所有已上传文档。"""
    try:
        docs = await run_in_threadpool(get_rag_store().list_documents)
        return {"documents": docs, "total": len(docs)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"查询失败: {str(exc)}")


@router.delete("/{doc_id}")
async def delete_document(doc_id: int):
    """删除指定文档及其向量索引。"""
    try:
        deleted = await run_in_threadpool(get_rag_store().delete_document, doc_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"删除失败: {str(exc)}")

    if not deleted:
        raise HTTPException(status_code=404, detail="文档不存在")

    return {"status": "ok", "message": "文档已删除"}
