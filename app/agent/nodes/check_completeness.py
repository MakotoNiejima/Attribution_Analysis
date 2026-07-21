"""检查信息完整性节点"""

from app.agent.state import AnalysisState


def check_completeness(state: AnalysisState) -> str:
    """
    检查信息完整性
    
    判断解析后的信息是否足够开始分析。
    
    Args:
        state: 当前分析状态
        
    Returns:
        "complete" 或 "clarify"
    """
    print("[节点] 检查信息完整性...")
    
    # 检查是否有明确的问题
    if not state.parsed_problem:
        return "clarify"
    
    # 检查是否有时间范围
    if not state.parsed_start or not state.parsed_end:
        return "clarify"
    
    # 检查是否有对比时间范围（可选）
    # 对比时间范围可以由系统自动推断，所以不是必须的
    
    # 检查是否有分析指标
    if not state.parsed_metric:
        return "clarify"
    
    # 检查是否有分析维度（可选）
    # 维度可以为空，系统会使用默认维度
    
    return "complete"
