"""提取关键发现节点"""

from app.agent.state import AnalysisState


def extract_findings(state: AnalysisState) -> AnalysisState:
    """
    提取关键发现

    从分析结果中提取最重要的发现
    根据 analysis_type 选择不同的提取逻辑
    """
    print("[节点] 提取关键发现...")

    if not state.analysis_result:
        state.errors.append("无分析结果可提取")
        return state

    try:
        findings = []

        if state.analysis_type == "market":
            # 市场表现分析：提取渠道ROI变化
            channel_changes = state.analysis_result.get("channel_changes", [])
            for change in channel_changes:
                roi_change_rate = change.get("roi_change_rate", 0)
                if abs(roi_change_rate) > 0.05:  # ROI变化超过5%
                    findings.append({
                        "dimension": "渠道效率",
                        "group": change["channel"],
                        "effect": roi_change_rate,
                        "effect_type": "roi_change",
                        "baseline_roi": change["baseline"]["roi"],
                        "current_roi": change["current"]["roi"],
                        "roi_change": change["roi_change"],
                        "ad_spend_change": change["ad_spend_change"],
                        "revenue_change": change["revenue_change"],
                        "evidence_ref": f"channel_changes[{change['channel']}].roi_change_rate",
                    })
        else:
            # 转化率分析：原有提取逻辑
            dimension_configs = {
                "channel": ("channel_decomposition", "渠道"),
                "device": ("device_decomposition", "设备"),
                "region": ("region_decomposition", "地区"),
                "user_type": ("user_type_decomposition", "新老用户"),
            }
            requested_dimensions = set(state.parsed_dimensions or dimension_configs.keys())
            for dimension_key in requested_dimensions:
                config = dimension_configs.get(dimension_key)
                if not config:
                    continue
                result_key, display_name = config
                contributions = state.analysis_result.get(result_key, {}).get("contributions", [])
                for contrib in contributions:
                    if abs(contrib["total_effect"]) > 0.001:
                        findings.append({
                            "dimension": display_name,
                            "group": contrib["group_name"],
                            "effect": contrib["total_effect"],
                            "effect_type": "total",
                            "share_effect": contrib["share_effect"],
                            "rate_effect": contrib["rate_effect"],
                            "baseline_rate": contrib["baseline_rate"],
                            "current_rate": contrib["current_rate"],
                            "evidence_ref": f"{result_key}.contributions[{contrib['group_name']}].total_effect",
                        })

            # 从漏斗环节中提取
            stages = state.analysis_result.get("stage_decomposition", {}).get("stages", [])
            for stage in stages:
                if abs(stage["effect_on_overall"]) > 0.001:
                    findings.append({
                        "dimension": "漏斗环节",
                        "group": stage["stage_name"],
                        "effect": stage["effect_on_overall"],
                        "effect_type": "stage",
                        "baseline_rate": stage["baseline_rate"],
                        "current_rate": stage["current_rate"],
                        "evidence_ref": f"stage_decomposition.stages[{stage['stage_name']}].effect_on_overall"
                    })

        # 按效应绝对值排序，取前5个
        findings.sort(key=lambda x: abs(x["effect"]), reverse=True)
        state.key_findings = findings[:5]

    except Exception as e:
        state.errors.append(f"提取发现失败: {str(e)}")
        state.next_action = "error"

    return state
