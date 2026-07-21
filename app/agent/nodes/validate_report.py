"""验证报告节点"""

import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.state import AnalysisState
from app.agent.nodes.utils import get_llm
from app.agent.prompts import VALIDATE_REPORT_PROMPT


def validate_report(state: AnalysisState) -> AnalysisState:
    """
    验证报告

    检查报告中的每条结论是否有证据支持
    """
    print("[节点] 验证报告...")

    if not state.report_draft or not state.evidence:
        state.errors.append("无报告或证据可验证")
        state.next_action = "error"
        return state

    try:
        llm = get_llm()

        # 准备证据摘要
        evidence = state.evidence
        evidence_lines = []

        # 漏斗指标
        for m in evidence.get("metrics", []):
            value = m["metric_value"]
            if m["metric_unit"] == "%":
                value_text = f"{value * 100:.4f}%"
            else:
                value_text = str(value)
            evidence_lines.append(
                f"- 指标 | {m['metric_name']} | {value_text} | 周期={m['metric_period']}"
            )

        # 维度证据
        for d in evidence.get("dimension_evidences", []):
            evidence_lines.append(
                f"- 维度 | {d['dimension_name']}-{d['group_name']} | {d['metric_name']} | "
                f"基准{d['baseline_value']*100:.4f}% → 当前{d['current_value']*100:.4f}% | "
                f"变化{d['change_value']*100:+.4f}% | 效应{d['effect_value']*100:+.4f}%"
            )

        # 业务事件
        for event in evidence.get("business_events", []):
            evidence_lines.append(
                f"- 业务事件（仅关联） | {event['title']} | {event['description']}"
            )

        # 附件证据
        for attachment in evidence.get("attachment_evidence", []):
            evidence_lines.append(
                f"- 附件证据 | {attachment.get('filename', '未命名附件')} | "
                f"{attachment.get('description', '受控查询结果')}"
            )

        evidence_summary = "\n".join(evidence_lines)

        prompt = VALIDATE_REPORT_PROMPT.format(
            report=state.report_draft,
            evidence_summary=evidence_summary
        )

        response = llm.invoke([
            SystemMessage(content="你是一个证据校验助手。"),
            HumanMessage(content=prompt)
        ])

        # 解析验证结果
        content = response.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]

        validation = json.loads(content.strip())

        state.is_valid = validation.get("is_valid", True)
        state.validation_errors = validation.get("errors", [])

        if not state.is_valid:
            print(f"  [警告] 发现 {len(state.validation_errors)} 个证据问题")
            for err in state.validation_errors:
                state.errors.append(f"证据校验: {err}")

    except Exception as e:
        state.errors.append(f"验证报告失败: {str(e)}")
        state.validation_errors.append("证据校验无法完成，报告不能作为已验证结果输出。")
        state.is_valid = False
        state.next_action = "error"

    return state
