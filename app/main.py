r"""
FastAPI 入口

启动命令：
    cd D:\dev\归因分析
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""

import os
import sys
from contextlib import asynccontextmanager

# 确保能找到 app 模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from dotenv import load_dotenv
load_dotenv()

from app.api.analysis import router as analysis_router
from app.api.attachments import router as attachments_router
from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.workbench import router as workbench_router
from app.persistence.service import get_persistence_service
from app.realtime.manager import get_task_runtime_manager


def get_cors_origins() -> list[str]:
    """读取允许访问 API 的前端地址，开发环境默认 Vite 地址。"""
    raw_origins = os.getenv(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:5174,http://127.0.0.1:5174,http://localhost:5175,http://127.0.0.1:5175",
    )
    return [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(_: FastAPI):
    """启动时补齐持久化表；不会改动已有的业务数据表。"""
    persistence = get_persistence_service()
    await run_in_threadpool(persistence.initialize_schema)
    await run_in_threadpool(persistence.fail_interrupted_tasks)
    try:
        yield
    finally:
        await get_task_runtime_manager().shutdown()

# 创建 FastAPI 应用
app = FastAPI(
    title="经营归因分析系统",
    description="基于 LangGraph 的经营归因分析 API",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    # 本地登录使用 HttpOnly Cookie，因此不能使用 '*' 作为允许来源。
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(analysis_router)
app.include_router(attachments_router)
app.include_router(documents_router)
app.include_router(auth_router)
app.include_router(workbench_router)


# 健康检查
@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok", "version": "0.2.0"}


# 根路径
@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "经营归因分析系统",
        "version": "0.2.0",
        "docs": "/docs",
        "endpoints": {
            "analysis": "/api/v1/analysis/run",
            "conversations": "/api/v1/conversations",
            "attachments": "/api/v1/attachments",
            "documents": "/api/v1/documents",
            "auth": "/auth/me",
            "workbench": "/api/chat/ls",
        }
    }
