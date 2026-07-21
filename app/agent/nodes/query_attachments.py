"""查询附件节点"""

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.state import AnalysisState
from app.agent.nodes.utils import get_llm
from app.agent.prompts import ATTACHMENT_QUERY_PROMPT
from app.attachments.engine import preview_attachment, query_attachment, aggregate_attachment


def query_attachments(state: AnalysisState) -> AnalysisState:
    """
    查询附件

    根据分析结果查询相关附件，提取补充证据
    """
    print("[节点] 查询附件...")

    if not state.attachments:
        return state

    try:
        llm = get_llm()

        # 准备关键发现
        findings_text = ""
        if state.key_findings:
            findings_text = "\n".join([
                f"- {f['dimension']}-{f['group']}: 效应{f['effect']*100:+.2f}%"
                for f in state.key_findings[:5]
            ])

        evidence_list = []

        for attachment in state.attachments:
            att_id = attachment.get("attachment_id")
            if not att_id:
                continue

            try:
                # 预览附件内容
                detail = preview_attachment(att_id)
            except Exception as e:
                print(f"  [警告] 无法预览附件 {attachment.get('filename')}: {e}")
                continue

            columns_str = ", ".join(c["name"] for c in detail.get("columns", []))
            preview_lines = []
            for row in detail.get("preview", [])[:5]:
                preview_lines.append(" | ".join(f"{k}={v}" for k, v in row.items()))
            preview_str = "\n".join(preview_lines) if preview_lines else "（无预览数据）"

            prompt = ATTACHMENT_QUERY_PROMPT.format(
                filename=detail["filename"],
                row_count=detail["row_count"],
                columns=columns_str,
                preview=preview_str,
                key_findings=findings_text,
            )

            response = llm.invoke([
                SystemMessage(content="你是数据分析助手，判断文件与分析的相关性并生成查询计划。"),
                HumanMessage(content=prompt),
            ])

            try:
                content = response.content
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                plan = json.loads(content.strip())
            except Exception:
                print(f"  [警告] 无法解析附件相关性判断: {detail['filename']}")
                continue

            if not plan.get("is_relevant", False):
                print(f"  附件 {detail['filename']} 与分析不相关: {plan.get('reason', '')}")
                continue

            print(f"  附件 {detail['filename']} 相关: {plan.get('reason', '')}")

            for q in plan.get("queries", []):
                try:
                    action = q.get("action", "query")
                    if action == "aggregate":
                        result = aggregate_attachment(
                            att_id,
                            group_by=q.get("group_by", ""),
                            metrics=q.get("metrics", {}),
                            filters=q.get("filters"),
                        )
                    else:
                        result = query_attachment(
                            att_id,
                            filters=q.get("filters"),
                            columns=q.get("columns"),
                            limit=q.get("limit", 50),
                        )

                    evidence_list.append({
                        "filename": detail["filename"],
                        "description": q.get("description", ""),
                        "action": action,
                        "result": result,
                    })
                except Exception as e:
                    print(f"  [警告] 查询附件失败: {e}")

        state.attachment_evidence = evidence_list
        if evidence_list:
            print(f"  提取到 {len(evidence_list)} 条附件证据")

    except Exception as e:
        print(f"  [警告] 附件查询异常: {e}")
        state.attachment_evidence = []

    return state
