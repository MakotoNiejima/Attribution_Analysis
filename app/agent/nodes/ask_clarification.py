"""追问用户节点"""

from app.agent.state import AnalysisState


def ask_clarification(state: AnalysisState) -> AnalysisState:
    """
    向用户追问缺失的信息
    
    当信息不完整时，生成追问问题并设置状态为需要澄清。
    
    Args:
        state: 当前分析状态
        
    Returns:
        更新后的状态
    """
    print("[节点] 追问用户...")
    
    # 如果已经有追问问题，直接使用
    if state.clarification_question:
        state.next_action = "clarify"
        return state
    
    # 根据缺失的信息生成追问
    missing_info = []
    
    if not state.parsed_problem:
        missing_info.append("您想分析什么问题？")
    
    if not state.parsed_start or not state.parsed_end:
        missing_info.append("请提供分析的时间范围（例如：2026-07-01 到 2026-07-15）")
    
    if not state.parsed_metric:
        missing_info.append("您想分析哪个指标？（例如：转化率、ROI）")
    
    # 生成追问问题
    if missing_info:
        state.clarification_question = " ".join(missing_info)
    else:
        state.clarification_question = "请提供更多信息以便进行分析。"
    
    state.next_action = "clarify"
    
    return state
