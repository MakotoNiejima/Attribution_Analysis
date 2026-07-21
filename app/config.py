"""
统一配置模块

数据库凭据从环境变量读取，不写死在代码中。
"""

import os
from pathlib import Path
from urllib.parse import quote_plus

# 项目与运行期文件目录
PROJECT_ROOT = Path(__file__).parent.parent

# 尝试加载 .env 文件
try:
    from dotenv import load_dotenv
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass


# ============================================================
# 数据库配置
# ============================================================

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "attribution_db")


def build_sync_url() -> str:
    """构建同步数据库 URL"""
    password = quote_plus(DB_PASSWORD)
    return f"mysql+pymysql://{DB_USER}:{password}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"


def get_engine():
    """获取数据库引擎"""
    from sqlalchemy import create_engine
    url = build_sync_url()
    return create_engine(url, echo=False)


# ============================================================
# 时间范围配置（演示数据覆盖 2026-04-01 ~ 2026-08-01）
# ============================================================

BASELINE_START = os.getenv("BASELINE_START", "2026-06-01 00:00:00")
BASELINE_END = os.getenv("BASELINE_END", "2026-07-01 00:00:00")
CURRENT_START = os.getenv("CURRENT_START", "2026-07-01 00:00:00")
CURRENT_END = os.getenv("CURRENT_END", "2026-08-01 00:00:00")


# ============================================================
# LLM 配置
# ============================================================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")


# ============================================================
# 工作台、鉴权与文件存储配置
# ============================================================

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5174")
AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "false").strip().lower() in {"1", "true", "yes"}
AUTH_SECRET = os.getenv("AUTH_SECRET", "change-this-before-production")
DEV_DEFAULT_USERNAME = os.getenv("DEV_DEFAULT_USERNAME", "local-analyst")
DEV_DEFAULT_ROLE = os.getenv("DEV_DEFAULT_ROLE", "analyst")
APP_STORAGE_ROOT = Path(os.getenv("APP_STORAGE_ROOT", str(PROJECT_ROOT / "runtime_data"))).resolve()


def get_storage_root() -> Path:
    """返回并创建受项目控制的运行期文件根目录。"""
    APP_STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    return APP_STORAGE_ROOT


def reload_runtime_config() -> dict[str, str | bool]:
    """重新读取 .env；不返回数据库密码或模型密钥。"""
    global BASELINE_START, BASELINE_END, CURRENT_START, CURRENT_END
    global OPENAI_BASE_URL, LLM_MODEL, FRONTEND_URL, AUTH_REQUIRED, AUTH_SECRET
    global DEV_DEFAULT_USERNAME, DEV_DEFAULT_ROLE, APP_STORAGE_ROOT

    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env", override=True)
    except ImportError:
        pass

    BASELINE_START = os.getenv("BASELINE_START", "2026-06-01 00:00:00")
    BASELINE_END = os.getenv("BASELINE_END", "2026-06-15 00:00:00")
    CURRENT_START = os.getenv("CURRENT_START", "2026-07-01 00:00:00")
    CURRENT_END = os.getenv("CURRENT_END", "2026-07-15 00:00:00")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5174")
    AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "false").strip().lower() in {"1", "true", "yes"}
    AUTH_SECRET = os.getenv("AUTH_SECRET", "change-this-before-production")
    DEV_DEFAULT_USERNAME = os.getenv("DEV_DEFAULT_USERNAME", "local-analyst")
    DEV_DEFAULT_ROLE = os.getenv("DEV_DEFAULT_ROLE", "analyst")
    APP_STORAGE_ROOT = Path(os.getenv("APP_STORAGE_ROOT", str(PROJECT_ROOT / "runtime_data"))).resolve()

    return {
        "baseline_start": BASELINE_START,
        "baseline_end": BASELINE_END,
        "current_start": CURRENT_START,
        "current_end": CURRENT_END,
        "llm_model": LLM_MODEL,
        "llm_base_url": OPENAI_BASE_URL,
        "auth_required": AUTH_REQUIRED,
    }


def apply_runtime_overrides(overrides: dict[str, str]) -> dict[str, str | bool]:
    """应用数据库中允许热更新的非敏感配置，并返回当前公开快照。"""
    global BASELINE_START, BASELINE_END, CURRENT_START, CURRENT_END
    global OPENAI_BASE_URL, LLM_MODEL, FRONTEND_URL, AUTH_REQUIRED

    allowed = {
        "BASELINE_START", "BASELINE_END", "CURRENT_START", "CURRENT_END",
        "OPENAI_BASE_URL", "LLM_MODEL", "FRONTEND_URL", "AUTH_REQUIRED",
    }
    for key, value in overrides.items():
        if key not in allowed:
            continue
        if key == "AUTH_REQUIRED":
            AUTH_REQUIRED = value.strip().lower() in {"1", "true", "yes"}
            os.environ[key] = "true" if AUTH_REQUIRED else "false"
        else:
            os.environ[key] = value
            if key == "BASELINE_START": BASELINE_START = value
            elif key == "BASELINE_END": BASELINE_END = value
            elif key == "CURRENT_START": CURRENT_START = value
            elif key == "CURRENT_END": CURRENT_END = value
            elif key == "OPENAI_BASE_URL": OPENAI_BASE_URL = value
            elif key == "LLM_MODEL": LLM_MODEL = value
            elif key == "FRONTEND_URL": FRONTEND_URL = value
    return {
        "baseline_start": BASELINE_START,
        "baseline_end": BASELINE_END,
        "current_start": CURRENT_START,
        "current_end": CURRENT_END,
        "llm_model": LLM_MODEL,
        "llm_base_url": OPENAI_BASE_URL,
        "auth_required": AUTH_REQUIRED,
    }
