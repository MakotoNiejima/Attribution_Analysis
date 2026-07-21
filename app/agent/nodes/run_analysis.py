"""运行分析节点"""

from datetime import datetime, timezone

from app.agent.state import AnalysisState
from app.agent.progress import emit_progress
from app.agent.nodes.constants import SUPPORTED_METRIC, MARKET_METRIC
from app.analysis_core.service import run_conversion_analysis, AnalysisRequest
from app.analysis_core.market import analyze_market_performance


def run_analysis(state: AnalysisState) -> AnalysisState:
    """
    运行分析

    根据 parsed_metric 路由到不同的分析函数：
    - order_conversion_rate: 转化率分析
    - market_performance: 市场表现分析（渠道ROI等）
    """
    print("[节点] 运行分析...")

    try:
        if not state.analysis_request:
            raise ValueError("缺少分析请求")

        def parse_datetime(value: str) -> datetime:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

        def parse_date(value: str):
            return parse_datetime(value).date()

        request_data = state.analysis_request
        metric = request_data.get("metric", SUPPORTED_METRIC)

        if metric == MARKET_METRIC:
            # 市场表现分析
            emit_progress("detail", node="run_analysis", stage="market", message="分析各渠道投放效率与ROI")
            result = analyze_market_performance(
                baseline_start=parse_date(request_data["baseline_start"]),
                baseline_end=parse_date(request_data["baseline_end"]),
                current_start=parse_date(request_data["current_start"]),
                current_end=parse_date(request_data["current_end"]),
            )
            state.analysis_result = result.to_dict()
            state.analysis_type = "market"

            # 为市场表现分析生成 evidence 结构
            result_dict = result.to_dict()
            evidence = {
                "metrics": [
                    {
                        "metric_name": "基准期整体ROI",
                        "metric_value": result_dict["baseline_summary"]["overall_roi"],
                        "metric_unit": "",
                        "metric_period": "baseline"
                    },
                    {
                        "metric_name": "当前期整体ROI",
                        "metric_value": result_dict["current_summary"]["overall_roi"],
                        "metric_unit": "",
                        "metric_period": "current"
                    }
                ],
                "dimension_evidences": [],
                "business_events": [],
                "attachment_evidence": []
            }

            # 添加各渠道效率变化作为维度证据
            for change in result_dict["channel_changes"]:
                evidence["dimension_evidences"].append({
                    "dimension_name": "渠道",
                    "group_name": change["channel"],
                    "metric_name": "ROI",
                    "baseline_value": change["baseline"]["roi"],
                    "current_value": change["current"]["roi"],
                    "change_value": change["roi_change"],
                    "effect_value": change["roi_change_rate"]
                })

            state.evidence = evidence
            state.matched_events = []
        else:
            # 转化率分析（默认）
            request = AnalysisRequest(
                problem=request_data["problem"],
                baseline_start=parse_datetime(request_data["baseline_start"]),
                baseline_end=parse_datetime(request_data["baseline_end"]),
                current_start=parse_datetime(request_data["current_start"]),
                current_end=parse_datetime(request_data["current_end"]),
            )
            result = run_conversion_analysis(
                request,
                progress_callback=lambda stage, message: emit_progress(
                    "detail",
                    node="run_analysis",
                    stage=stage,
                    message=message,
                ),
            )
            state.analysis_result = result.to_dict()
            state.evidence = result.evidence
            state.matched_events = result.business_events
            state.analysis_type = "conversion"

    except Exception as e:
        state.errors.append(f"分析失败: {str(e)}")
        state.next_action = "error"

    return state
