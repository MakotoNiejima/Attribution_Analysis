"""本地开发登录与认证回调接口。生产环境可替换 callback 的身份提供方校验。"""

import re
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

import app.config as app_config
from app.auth.dependencies import get_current_user
from app.auth.security import issue_access_token
from app.persistence.service import get_persistence_service


router = APIRouter(prefix="/auth", tags=["auth"])
_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{2,80}$")


class LocalLoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=80)
    display_name: str | None = Field(default=None, max_length=120)
    # 该字段只用于课程演示的本地身份模式；生产环境应由身份提供方声明角色。
    role: Literal["analyst", "admin"] = "analyst"


def _normalize_username(value: str) -> str:
    username = value.strip().lower()
    if not _USERNAME_PATTERN.fullmatch(username):
        raise HTTPException(status_code=422, detail="用户名只能使用字母、数字、下划线、点或连字符")
    return username


def _login_payload(username: str, display_name: str | None, role: str) -> tuple[dict, str]:
    user = get_persistence_service().get_or_create_user(username, display_name, role)
    return user, issue_access_token(user)


@router.post("/login")
def login(request: LocalLoginRequest, response: Response):
    """课程开发环境的本地账号登录；返回令牌并设置 HttpOnly Cookie。"""
    user, token = _login_payload(
        _normalize_username(request.username), request.display_name, request.role
    )
    response.set_cookie(
        key="analysis_access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=12 * 60 * 60,
    )
    return {"access_token": token, "token_type": "bearer", "user": user}


@router.get("/login")
def begin_login(username: str = Query(default="local-analyst")):
    """保留 OAuth 风格入口，供登录页/课程演示跳转到 callback。"""
    normalized = _normalize_username(username)
    return RedirectResponse(url=f"/auth/callback?code={quote(normalized)}", status_code=302)


@router.get("/callback")
def auth_callback(code: str = Query(min_length=2, max_length=80)):
    """本地 callback：code 代表已在开发身份页确认的用户名。"""
    user, token = _login_payload(_normalize_username(code), None, "analyst")
    response = RedirectResponse(url=app_config.FRONTEND_URL, status_code=302)
    response.set_cookie(
        key="analysis_access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=12 * 60 * 60,
    )
    response.headers["X-Authenticated-User"] = user["username"]
    return response


@router.get("/me")
def current_user(user: dict = Depends(get_current_user)):
    return user


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("analysis_access_token")
    return {"status": "ok"}
