"""FastAPI 当前用户依赖。"""

from typing import Any

from fastapi import Cookie, Header, HTTPException, status

import app.config as app_config
from app.auth.security import verify_access_token
from app.persistence.service import get_persistence_service


def _read_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


def get_current_user(
    authorization: str | None = Header(default=None),
    analysis_access_token: str | None = Cookie(default=None),
) -> dict[str, Any]:
    """优先使用 Bearer/Cookie；开发模式无凭证时提供受限本地用户。"""
    token = _read_bearer(authorization) or analysis_access_token
    payload = verify_access_token(token)
    service = get_persistence_service()
    if payload:
        user = service.get_user(str(payload["sub"]))
        if user:
            return user

    if not app_config.AUTH_REQUIRED:
        return service.get_or_create_user(
            app_config.DEV_DEFAULT_USERNAME,
            display_name="本地分析用户",
            role=app_config.DEV_DEFAULT_ROLE,
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="请先登录后再访问工作台",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_admin(current_user: dict[str, Any]) -> dict[str, Any]:
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要系统管理员权限")
    return current_user
