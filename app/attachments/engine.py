"""附件解析与查询引擎。

职责：
- 解析上传的 CSV/XLSX 文件，提取列信息和前5行预览
- 按条件筛选查询（简化版 SQL WHERE）
- 分组聚合（简化版 SQL GROUP BY + SUM/COUNT/AVG）

不使用 pandas，用纯 Python + openpyxl/csv 处理，避免大文件内存问题。
"""

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.attachments.store import AttachmentRecord, get_attachment_store

# 最大预览行数
PREVIEW_ROWS = 5
# 最大查询返回行数
MAX_QUERY_ROWS = 200
# 文件大小阈值：超过此值用 openpyxl 逐行读取
LARGE_FILE_THRESHOLD = 10 * 1024 * 1024  # 10MB


# ================================================================
# 文件解析
# ================================================================

def parse_and_store(
    file_path: str | Path,
    conversation_id: str,
    filename: str | None = None,
) -> dict:
    """解析文件 → 提取列信息和预览 → 存入 SQLite → 返回摘要。"""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")

    suffix = path.suffix.lower()
    if suffix not in (".csv", ".xlsx", ".xls", ".txt"):
        raise ValueError(f"不支持的附件格式: {suffix}（支持 CSV/XLSX/TXT）")

    filename = filename or path.name
    file_size = path.stat().st_size

    if suffix == ".csv":
        columns, preview, row_count = _parse_csv(path)
    elif suffix in (".xlsx", ".xls"):
        columns, preview, row_count = _parse_excel(path)
    else:  # .txt
        columns, preview, row_count = _parse_txt(path)

    record = AttachmentRecord(
        id=str(uuid4()),
        conversation_id=conversation_id,
        filename=filename,
        stored_path=str(path),
        file_size=file_size,
        file_type=suffix,
        row_count=row_count,
        columns_json=columns,
        preview_json=preview,
        uploaded_at=datetime.now(UTC).isoformat(),
        status="parsed",
    )

    get_attachment_store().save(record)

    return {
        "id": record.id,
        "filename": filename,
        "file_type": suffix,
        "file_size": file_size,
        "row_count": row_count,
        "columns": columns,
        "preview": preview,
    }


def _parse_csv(path: Path) -> tuple[list[dict], list[dict], int]:
    """解析 CSV 文件。"""
    encodings = ["utf-8-sig", "utf-8", "gbk", "latin-1"]
    for enc in encodings:
        try:
            with open(path, encoding=enc, newline="") as f:
                return _read_csv_file(f)
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"无法识别 CSV 编码: {path.name}")


def _read_csv_file(f) -> tuple[list[dict], list[dict], int]:
    reader = csv.reader(f)
    header = next(reader, None)
    if not header:
        return [], [], 0

    columns = [{"name": h.strip(), "index": i} for i, h in enumerate(header)]
    preview = []
    row_count = 0

    for row in reader:
        row_count += 1
        if len(preview) < PREVIEW_ROWS:
            row_dict = {}
            for col in columns:
                idx = col["index"]
                row_dict[col["name"]] = row[idx] if idx < len(row) else ""
            preview.append(row_dict)

    # 继续计数剩余行
    # （reader 已经遍历完了，row_count 就是总行数）
    return columns, preview, row_count


def _parse_excel(path: Path) -> tuple[list[dict], list[dict], int]:
    """解析 Excel 文件（只读第一个 sheet）。"""
    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]

    columns = []
    preview = []
    row_count = 0
    header_found = False

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if not header_found:
            # 第一非空行作为表头
            cells = [str(c).strip() if c is not None else "" for c in row]
            if not any(cells):
                continue
            columns = [{"name": h, "index": j} for j, h in enumerate(cells)]
            header_found = True
            continue

        row_count += 1
        if len(preview) < PREVIEW_ROWS:
            row_dict = {}
            for col in columns:
                idx = col["index"]
                val = row[idx] if idx < len(row) else None
                row_dict[col["name"]] = str(val) if val is not None else ""
            preview.append(row_dict)

    wb.close()

    if not header_found:
        return [], [], 0

    return columns, preview, row_count


def _parse_txt(path: Path) -> tuple[list[dict], list[dict], int]:
    """解析 TXT 文件（按 Tab/逗号分隔尝试）。"""
    for enc in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
        try:
            text = path.read_text(encoding=enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    else:
        raise ValueError(f"无法识别文件编码: {path.name}")

    lines = text.strip().splitlines()
    if not lines:
        return [], [], 0

    # 尝试逗号分隔，再尝试 Tab
    for sep in (",", "\t"):
        first = lines[0].split(sep)
        if len(first) > 1:
            with open(path, encoding=enc, newline="") as f:
                return _read_csv_file(f)

    # 无法识别为表格，按纯文本处理
    columns = [{"name": "行号", "index": 0}, {"name": "内容", "index": 1}]
    preview = [{"行号": str(i + 1), "内容": line} for i, line in enumerate(lines[:PREVIEW_ROWS])]
    return columns, preview, len(lines)


# ================================================================
# 预览
# ================================================================

def preview_attachment(attachment_id: str) -> dict:
    """返回附件的表头和前5行预览。"""
    store = get_attachment_store()
    record = store.get(attachment_id)
    if record is None:
        raise ValueError(f"附件不存在: {attachment_id}")
    return {
        "id": record.id,
        "filename": record.filename,
        "file_type": record.file_type,
        "row_count": record.row_count,
        "columns": record.columns_json,
        "preview": record.preview_json,
    }


# ================================================================
# 筛选查询
# ================================================================

def query_attachment(
    attachment_id: str,
    filters: dict[str, Any] | None = None,
    columns: list[str] | None = None,
    limit: int = MAX_QUERY_ROWS,
) -> dict:
    """按条件筛选附件数据。

    filters 支持的语法：
      {"col": "exact_value"}          — 精确匹配
      {"col__eq": "value"}            — 精确匹配
      {"col__contains": "substring"}  — 包含
      {"col__gte": "2026-06-01"}      — 大于等于（字符串比较）
      {"col__lte": "2026-06-30"}      — 小于等于
      {"col__gt": "100"}              — 大于
      {"col__lt": "50"}               — 小于
    """
    store = get_attachment_store()
    record = store.get(attachment_id)
    if record is None:
        raise ValueError(f"附件不存在: {attachment_id}")

    # 重新读取文件执行查询
    path = Path(record.stored_path)
    if not path.exists():
        raise FileNotFoundError(f"源文件已删除: {path}")

    if record.file_type == ".csv":
        rows = _query_csv(path, filters, columns, limit)
    elif record.file_type in (".xlsx", ".xls"):
        rows = _query_excel(path, filters, columns, limit)
    else:
        rows = _query_txt(path, filters, columns, limit)

    return {
        "id": record.id,
        "filename": record.filename,
        "total_rows": record.row_count,
        "returned_rows": len(rows),
        "columns": columns or [c["name"] for c in record.columns_json],
        "rows": rows,
    }


def _apply_filters(row: dict, filters: dict[str, Any] | None) -> bool:
    """判断一行是否满足筛选条件。"""
    if not filters:
        return True

    for key, expected in filters.items():
        if "__" in key:
            col, op = key.rsplit("__", 1)
        else:
            col, op = key, "eq"

        val = row.get(col, "")
        val_str = str(val).lower()
        exp_str = str(expected).lower()

        if op == "eq" and val_str != exp_str:
            return False
        elif op == "contains" and exp_str not in val_str:
            return False
        elif op == "gte" and val_str < exp_str:
            return False
        elif op == "lte" and val_str > exp_str:
            return False
        elif op == "gt" and val_str <= exp_str:
            return False
        elif op == "lt" and val_str >= exp_str:
            return False

    return True


def _select_columns(row: dict, columns: list[str] | None) -> dict:
    """只保留指定列。"""
    if columns is None:
        return row
    return {k: v for k, v in row.items() if k in columns}


def _query_csv(
    path: Path,
    filters: dict | None,
    columns: list[str] | None,
    limit: int,
) -> list[dict]:
    for enc in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
        try:
            with open(path, encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                results = []
                for row in reader:
                    if _apply_filters(row, filters):
                        results.append(_select_columns(row, columns))
                        if len(results) >= limit:
                            break
                return results
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"无法读取文件: {path.name}")


def _query_excel(
    path: Path,
    filters: dict | None,
    columns: list[str] | None,
    limit: int,
) -> list[dict]:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]

    header = []
    results = []

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if not header:
            header = [str(c).strip() if c is not None else "" for c in row]
            continue

        row_dict = {}
        for j, h in enumerate(header):
            val = row[j] if j < len(row) else None
            row_dict[h] = str(val) if val is not None else ""

        if _apply_filters(row_dict, filters):
            results.append(_select_columns(row_dict, columns))
            if len(results) >= limit:
                break

    wb.close()
    return results


def _query_txt(
    path: Path,
    filters: dict | None,
    columns: list[str] | None,
    limit: int,
) -> list[dict]:
    # TXT 按 CSV 方式处理
    return _query_csv(path, filters, columns, limit)


# ================================================================
# 分组聚合
# ================================================================

def aggregate_attachment(
    attachment_id: str,
    group_by: str,
    metrics: dict[str, str],
    filters: dict[str, Any] | None = None,
) -> dict:
    """分组聚合查询。

    Args:
        group_by: 分组列名
        metrics: {"列名": "聚合函数"}，支持 sum/avg/count/min/max
        filters: 可选的前置筛选条件

    Returns:
        {"columns": [...], "rows": [...]}
    """
    # 先做筛选查询（不限行数）
    store = get_attachment_store()
    record = store.get(attachment_id)
    if record is None:
        raise ValueError(f"附件不存在: {attachment_id}")

    path = Path(record.stored_path)
    if not path.exists():
        raise FileNotFoundError(f"源文件已删除: {path}")

    # 读取所有满足条件的行
    if record.file_type == ".csv":
        all_rows = _query_csv(path, filters, None, limit=MAX_QUERY_ROWS * 10)
    elif record.file_type in (".xlsx", ".xls"):
        all_rows = _query_excel(path, filters, None, limit=MAX_QUERY_ROWS * 10)
    else:
        all_rows = _query_txt(path, filters, None, limit=MAX_QUERY_ROWS * 10)

    # 分组
    groups: dict[str, list[dict]] = {}
    for row in all_rows:
        key = str(row.get(group_by, "未知"))
        groups.setdefault(key, []).append(row)

    # 聚合
    result_rows = []
    for group_key, group_rows in sorted(groups.items()):
        agg_row = {group_by: group_key}
        for col, func in metrics.items():
            values = []
            for r in group_rows:
                try:
                    values.append(float(r.get(col, 0)))
                except (ValueError, TypeError):
                    continue

            if func == "sum":
                agg_row[f"{col}_sum"] = round(sum(values), 4)
            elif func == "avg":
                agg_row[f"{col}_avg"] = round(sum(values) / len(values), 4) if values else 0
            elif func == "count":
                agg_row[f"{col}_count"] = len(values)
            elif func == "min":
                agg_row[f"{col}_min"] = round(min(values), 4) if values else 0
            elif func == "max":
                agg_row[f"{col}_max"] = round(max(values), 4) if values else 0

        result_rows.append(agg_row)

    return {
        "id": record.id,
        "filename": record.filename,
        "group_by": group_by,
        "metrics": metrics,
        "groups_count": len(result_rows),
        "rows": result_rows,
    }
