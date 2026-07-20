"""运行期文件的受限存储路径与安全清理。"""

import re
import shutil
from pathlib import Path
from uuid import uuid4

from app.config import get_storage_root


class StoragePathError(ValueError):
    """文件路径试图越出项目运行目录。"""


def safe_filename(filename: str, fallback: str = "attachment") -> str:
    """保留可读文件名，去除路径段、控制字符和 Windows 非法字符。"""
    name = Path(filename or "").name.strip()
    name = re.sub(r"[<>:\\/*?\"|\x00-\x1f]", "_", name)
    name = name.strip(". ")
    return name[:180] or fallback


def _child_of(root: Path, *parts: str) -> Path:
    candidate = root.joinpath(*parts).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise StoragePathError("文件路径不在允许的运行目录内") from exc
    return candidate


def save_upload(content: bytes, *, user_id: str, conversation_id: str, filename: str, category: str) -> Path:
    """保存上传内容到 uploads/{user}/{conversation}/，以 UUID 消除同名覆盖。"""
    root = get_storage_root()
    directory = _child_of(root, "uploads", category, safe_filename(user_id), safe_filename(conversation_id))
    directory.mkdir(parents=True, exist_ok=True)
    destination = _child_of(directory, f"{uuid4().hex}_{safe_filename(filename)}")
    destination.write_bytes(content)
    return destination


def export_path(*, user_id: str, conversation_id: str, task_id: str, suffix: str = ".md") -> Path:
    root = get_storage_root()
    directory = _child_of(root, "exports", safe_filename(user_id), safe_filename(conversation_id))
    directory.mkdir(parents=True, exist_ok=True)
    return _child_of(directory, f"{safe_filename(task_id)}{suffix}")


def unlink_file(path_value: str | Path) -> bool:
    """只删除 runtime_data 内的单个文件，防止元数据被篡改时越界删除。"""
    root = get_storage_root()
    path = Path(path_value).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise StoragePathError("拒绝删除运行目录以外的文件") from exc
    if path.is_file():
        path.unlink()
        return True
    return False


def remove_conversation_files(user_id: str, conversation_id: str) -> None:
    """删除一个会话的上传和导出目录；目标经过根目录校验。"""
    root = get_storage_root()
    for category in ("uploads", "exports", "workspace"):
        if category == "uploads":
            targets = [
                _child_of(root, category, kind, safe_filename(user_id), safe_filename(conversation_id))
                for kind in ("structured", "document")
            ]
        else:
            targets = [_child_of(root, category, safe_filename(user_id), safe_filename(conversation_id))]
        for target in targets:
            if target.exists() and target.is_dir():
                shutil.rmtree(target)
