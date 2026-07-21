"""最终输出节点"""

from app.agent.state import AnalysisState


def finalize(state: AnalysisState) -> AnalysisState:
    """
    最终输出

    生成最终报告，整合所有分析结果
    """
    print("[节点] 生成最终输出...")

    if not state.report_draft:
        state.errors.append("无报告草稿可输出")
        state.next_action = "error"
        return state

    # 构建最终报告
    report_parts = []

    # 1. 问题定义
    if state.parsed_problem:
        report_parts.append(f"## 问题定义\n\n{state.parsed_problem}\n")

    # 2. 时间范围
    if state.analysis_request:
        baseline_start = state.analysis_request.get("baseline_start", "")[:10]
        baseline_end = state.analysis_request.get("baseline_end", "")[:10]
        current_start = state.analysis_request.get("current_start", "")[:10]
        current_end = state.analysis_request.get("current_end", "")[:10]
        report_parts.append(
            f"## 时间范围\n\n"
            f"- 基准期：{baseline_start} ~ {baseline_end}\n"
            f"- 当前期：{current_start} ~ {current_end}\n"
        )

    # 3. 关键发现
    if state.key_findings:
        report_parts.append("## 关键发现\n")
        for i, finding in enumerate(state.key_findings, 1):
            dimension = finding.get("dimension", "")
            group = finding.get("group", "")
            effect = finding.get("effect", 0)
            effect_type = finding.get("effect_type", "")
            
            if effect_type == "roi_change":
                # 市场表现分析
                baseline_roi = finding.get("baseline_roi", 0)
                current_roi = finding.get("current_roi", 0)
                roi_change = finding.get("roi_change", 0)
                report_parts.append(
                    f"{i}. **{dimension} - {group}**\n"
                    f"   - ROI 变化：{baseline_roi:.2f} → {current_roi:.2f} ({roi_change:+.2f})\n"
                )
            else:
                # 转化率分析
                report_parts.append(
                    f"{i}. **{dimension} - {group}**\n"
                    f"   - 效应：{effect*100:+.2f}%\n"
                )
        report_parts.append("")

    # 4. 报告正文
    report_parts.append("## 详细分析\n")
    report_parts.append(state.report_draft)

    # 5. 证据来源
    evidence_sources = []
    
    # 附件证据
    if state.attachment_evidence:
        for evidence in state.attachment_evidence:
            filename = evidence.get("filename", "")
            description = evidence.get("description", "")
            if filename:
                evidence_sources.append(f"- 附件：{filename} - {description}")
    
    # 文档证据
    if state.retrieved_docs:
        for doc in state.retrieved_docs:
            source = doc.get("source", "")
            if source:
                evidence_sources.append(f"- 文档：{source}")
    
    if evidence_sources:
        report_parts.append("\n## 证据来源\n")
        report_parts.extend(evidence_sources)

    # 6. 免责声明
    report_parts.append(
        "\n---\n"
        "*本报告基于数据分析生成，所有结论均有数据支持。业务事件仅作为关联因素，不构成因果关系证明。*"
    )

    state.report_final = "\n".join(report_parts)
    print(f"  最终报告已生成，长度：{len(state.report_final)} 字符")

    return state
