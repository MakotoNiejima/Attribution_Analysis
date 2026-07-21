"""构造分析请求节点"""

from datetime import datetime, timezone

from app.agent.state import AnalysisState
from app.analysis_core.service import AnalysisRequest
import app.config as app_config


def build_request(state: AnalysisState) -> AnalysisState:
    """
    构造分析请求

    将解析结果转换为 AnalysisRequest
    """
    print("[节点] 构造分析请求...")

    try:
        if not state.parsed_start or not state.parsed_end:
            raise ValueError("缺少当前分析周期")

        # 计算对比周期（默认对比同等长度的上一个周期）
        delta = state.parsed_end - state.parsed_start
        compare_start = state.parsed_compare_start or (state.parsed_start - delta)
        compare_end = state.parsed_compare_end or state.parsed_start

        def config_datetime(value: str) -> datetime:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

        # 数据覆盖 2026-04-01 ~ 2026-08-01，任意两段均可对比
        data_start = datetime(2026, 4, 1, tzinfo=timezone.utc)
        data_end = datetime(2026, 8, 1, tzinfo=timezone.utc)

        is_supported_window = (
            data_start <= compare_start < compare_end <= data_end
            and data_start <= state.parsed_start < state.parsed_end <= data_end
        )
        if not is_supported_window:
            state.clarification_question = (
                "当前演示数据覆盖 2026-04-01 至 2026-07-31。"
                "请在该范围内指定分析周期，例如：对比 5 月和 7 月、对比 6 月第一周和 7 月第一周等。"
            )
            state.next_action = "clarify"
            return state

        request = AnalysisRequest(
            problem=state.parsed_problem,
            baseline_start=compare_start,
            baseline_end=compare_end,
            current_start=state.parsed_start,
            current_end=state.parsed_end
        )

        state.analysis_request = {
            "problem": request.problem,
            "metric": state.parsed_metric,
            "dimensions": state.parsed_dimensions,
            "baseline_start": request.baseline_start.isoformat(),
            "baseline_end": request.baseline_end.isoformat(),
            "current_start": request.current_start.isoformat(),
            "current_end": request.current_end.isoformat()
        }

    except Exception as e:
        state.errors.append(f"构造请求失败: {str(e)}")
        state.next_action = "error"

    return state
