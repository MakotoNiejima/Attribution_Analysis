"""不依赖第三方包的短期签名访问令牌。"""

import base64
import hashlib
import hmac
import json
import time
from typing import Any

import app.config as app_config


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_access_token(user: dict[str, Any], ttl_seconds: int = 12 * 60 * 60) -> str:
    """签发只包含身份和过期时间的 HMAC 令牌，不写入任何敏感信息。"""
    payload = {
        "sub": user["user_id"],
        "username": user["username"],
        "role": user["role"],
        "exp": int(time.time()) + max(300, min(ttl_seconds, 7 * 24 * 60 * 60)),
    }
    encoded = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(
        app_config.AUTH_SECRET.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{encoded}.{_b64encode(signature)}"


def verify_access_token(token: str | None) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None
    encoded, supplied_signature = token.rsplit(".", 1)
    expected_signature = hmac.new(
        app_config.AUTH_SECRET.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
    ).digest()
    try:
        if not hmac.compare_digest(expected_signature, _b64decode(supplied_signature)):
            return None
        payload = json.loads(_b64decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or int(payload.get("exp", 0)) < int(time.time()):
        return None
    if not payload.get("sub"):
        return None
    return payload
