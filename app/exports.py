"""将已验证的分析结果导出为可下载 Markdown。"""

from pathlib import Path
from typing import Any


def _percentage(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "--"


def build_markdown_export(task: dict[str, Any]) -> str:
    """统一输出问题、指标、证据、结论、缺口和行动六段。"""
    result = task.get("analysis_result") or {}
    baseline = result.get("baseline_funnel") or {}
    current = result.get("current_funnel") or {}
    findings = task.get("key_findings") or []
    evidence = task.get("evidence") or {}
    event_items = task.get("matched_events") or []

    metric_lines = [
        "| 指标 | 基准期 | 当前期 |",
        "| --- | ---: | ---: |",
        f"| 整体下单转化率 | {_percentage(baseline.get('order_rate'))} | {_percentage(current.get('order_rate'))} |",
        f"| 访问会话数 | {baseline.get('visit_sessions', '--')} | {current.get('visit_sessions', '--')} |",
        f"| 加购会话数 | {baseline.get('cart_sessions', '--')} | {current.get('cart_sessions', '--')} |",
        f"| 下单会话数 | {baseline.get('order_sessions', '--')} | {current.get('order_sessions', '--')} |",
    ]

    finding_lines = [
        f"- {item.get('dimension', '维度')} / {item.get('group', '分组')}："
        f"影响 {_percentage(item.get('effect'))}。"
        for item in findings
    ] or ["- 未生成可验证的关键归因项。"]

    evidence_lines = [f"- 结构化指标证据：{len(evidence.get('metrics') or [])} 条。"]
    evidence_lines += [
        f"- 经营事件：{item.get('title', '未命名事件')}。" for item in event_items
    ]
    if evidence.get("attachment_evidence"):
        evidence_lines.append(f"- 已使用 {len(evidence['attachment_evidence'])} 条附件查询证据。")
    if evidence.get("retrieved_docs"):
        evidence_lines.append(f"- 已引用 {len(evidence['retrieved_docs'])} 个文档片段。")

    next_actions = [
        "- 优先针对影响最大的维度复核投放、页面和商品策略，并在下一周期观察漏斗变化。",
        "- 补充与异常时间窗对应的活动、库存、价格或履约数据，避免把相关性当作因果。",
    ]
    return "\n".join(
        [
            "# 经营归因分析结果",
            "",
            "## 1. 分析问题",
            task.get("question") or "未记录问题",
            "",
            "## 2. 关键指标",
            *metric_lines,
            "",
            "## 3. 证据列表",
            *evidence_lines,
            "",
            "## 4. 归因结论",
            *(finding_lines + ["", task.get("report") or "未生成最终报告。"]),
            "",
            "## 5. 缺失数据与边界",
            "- 当前结论基于已接入的行为数据、附件和经营事件；未接入的数据不会被假定存在。",
            "- 经营事件仅作为时间相关线索，不能单独证明因果关系。",
            "",
            "## 6. 下一步行动",
            *next_actions,
            "",
        ]
    )


def write_markdown_export(path: Path, task: dict[str, Any]) -> Path:
    path.write_text(build_markdown_export(task), encoding="utf-8")
    return path
