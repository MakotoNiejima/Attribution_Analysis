"""错误处理节点"""

from app.agent.state import AnalysisState


def handle_error(state: AnalysisState) -> AnalysisState:
    """
    错误处理

    记录错误信息，准备错误报告
    """
    print("[节点] 处理错误...")

    # 构建错误报告
    error_parts = []
    
    error_parts.append("## 分析过程中出现错误\n")
    
    if state.errors:
        error_parts.append("### 错误信息\n")
        for i, error in enumerate(state.errors, 1):
            error_parts.append(f"{i}. {error}")
        error_parts.append("")
    
    # 如果有部分结果，仍然展示
    if state.key_findings:
        error_parts.append("### 已完成的部分分析\n")
        for finding in state.key_findings[:3]:
            dimension = finding.get("dimension", "")
            group = finding.get("group", "")
            effect = finding.get("effect", 0)
            error_parts.append(f"- {dimension} - {group}: 效应 {effect*100:+.2f}%")
        error_parts.append("")
    
    error_parts.append("---\n")
    error_parts.append("*分析未能完全完成，请检查输入参数或联系管理员。*")
    
    state.report_final = "\n".join(error_parts)

    return state
