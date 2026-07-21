"""将已验证的分析结果导出为可下载 Markdown。"""

from pathlib import Path
from typing import Any


def _percentage(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "--"


def build_markdown_export(task: dict[str, Any]) -> str:
    """统一输出问题、指标、证据、结论、缺口和行动六段。

    优先使用规范六段结构字段（problem_definition、key_metrics、evidence_list、
    conclusion_text、missing_data_text、next_action_text），如不存在则回退到
    兼容字段。
    """
    result = task.get("analysis_result") or {}
    baseline = result.get("baseline_funnel") or {}
    current = result.get("current_funnel") or {}
    findings = task.get("key_findings") or []
    evidence = task.get("evidence") or {}
    event_items = task.get("matched_events") or []

    # 规范六段结构字段（优先）
    problem_definition = task.get("problem_definition") or task.get("input_text") or "未记录问题"
    key_metrics = task.get("key_metrics") or []
    evidence_list = task.get("evidence_list") or []
    conclusion_text = task.get("conclusion_text") or ""
    missing_data_text = task.get("missing_data_text") or ""
    next_action_text = task.get("next_action_text") or ""

    # 关键指标：优先使用规范字段
    if key_metrics:
        metric_lines = [
            "| 指标名称 | 数值 | 单位 | 周期 |",
            "| --- | ---: | --- | --- |",
        ]
        for m in key_metrics:
            metric_lines.append(
                f"| {m.get('metric_name', '')} | {m.get('metric_value', '--')} "
                f"| {m.get('metric_unit', '')} | {m.get('metric_period', '')} |"
            )
    else:
        metric_lines = [
            "| 指标 | 基准期 | 当前期 |",
            "| --- | ---: | ---: |",
            f"| 整体下单转化率 | {_percentage(baseline.get('order_rate'))} | {_percentage(current.get('order_rate'))} |",
            f"| 访问会话数 | {baseline.get('visit_sessions', '--')} | {current.get('visit_sessions', '--')} |",
            f"| 加购会话数 | {baseline.get('cart_sessions', '--')} | {current.get('cart_sessions', '--')} |",
            f"| 下单会话数 | {baseline.get('order_sessions', '--')} | {current.get('order_sessions', '--')} |",
        ]

    # 证据列表：优先使用规范字段
    if evidence_list:
        evidence_lines = [
            "| 来源类型 | 来源名称 | 证据内容 | 关联指标 | 置信度 |",
            "| --- | --- | --- | --- | ---: |",
        ]
        for e in evidence_list:
            evidence_lines.append(
                f"| {e.get('source_type', '')} | {e.get('source_name', '')} "
                f"| {e.get('evidence_text', '')} | {e.get('related_metric', '')} "
                f"| {e.get('confidence', '')} |"
            )
    else:
        evidence_lines = [f"- 结构化指标证据：{len(evidence.get('metrics') or [])} 条。"]
        evidence_lines += [
            f"- 经营事件：{item.get('title', '未命名事件')}。" for item in event_items
        ]
        if evidence.get("attachment_evidence"):
            evidence_lines.append(f"- 已使用 {len(evidence['attachment_evidence'])} 条附件查询证据。")
        if evidence.get("retrieved_docs"):
            evidence_lines.append(f"- 已引用 {len(evidence['retrieved_docs'])} 个文档片段。")

    # 归因结论
    if conclusion_text:
        conclusion_content = [conclusion_text]
    else:
        finding_lines = [
            f"- {item.get('dimension', '维度')} / {item.get('group', '分组')}："
            f"影响 {_percentage(item.get('effect'))}。"
            for item in findings
        ] or ["- 未生成可验证的关键归因项。"]
        conclusion_content = finding_lines + ["", task.get("report") or "未生成最终报告。"]

    # 缺失数据
    if missing_data_text:
        missing_content = [missing_data_text]
    else:
        missing_content = [
            "- 当前结论基于已接入的行为数据、附件和经营事件；未接入的数据不会被假定存在。",
            "- 经营事件仅作为时间相关线索，不能单独证明因果关系。",
        ]

    # 下一步建议
    if next_action_text:
        # 按换行拆分为列表项
        action_items = [f"- {line.strip()}" for line in next_action_text.split("\n") if line.strip()]
    else:
        action_items = [
            "- 优先针对影响最大的维度复核投放、页面和商品策略，并在下一周期观察漏斗变化。",
            "- 补充与异常时间窗对应的活动、库存、价格或履约数据，避免把相关性当作因果。",
        ]

    return "\n".join(
        [
            "# 经营归因分析结果",
            "",
            "## 1. 问题定义",
            problem_definition,
            "",
            "## 2. 关键指标",
            *metric_lines,
            "",
            "## 3. 证据列表",
            *evidence_lines,
            "",
            "## 4. 归因结论",
            *conclusion_content,
            "",
            "## 5. 待补充数据",
            *missing_content,
            "",
            "## 6. 下一步建议",
            *action_items,
            "",
        ]
    )


def write_markdown_export(path: Path, task: dict[str, Any]) -> Path:
    path.write_text(build_markdown_export(task), encoding="utf-8")
    return path
