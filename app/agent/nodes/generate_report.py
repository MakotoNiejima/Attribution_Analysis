"""生成报告节点"""

import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.state import AnalysisState
from app.agent.nodes.utils import get_llm
from app.agent.prompts import GENERATE_REPORT_PROMPT
from app.agent.progress import emit_progress


def generate_report(state: AnalysisState) -> AnalysisState:
    """
    生成报告

    根据 analysis_type 生成不同类型的报告
    """
    print("[节点] 生成报告...")

    if not state.analysis_result:
        state.errors.append("无分析结果可提取")
        return state

    try:
        llm = get_llm()
        result = state.analysis_result

        # 文档检索结果（RAG）
        retrieved_docs = state.retrieved_docs_text or "无相关业务文档"

        # 附件查询结果
        attachment_evidence = "无相关附件证据"
        if state.attachment_evidence:
            attachment_evidence = json.dumps(
                state.attachment_evidence[:5], ensure_ascii=False, default=str
            )[:4000]

        # 根据分析类型生成不同的报告
        # 优先检查市场表现分析的特征字段
        is_market_analysis = (
            state.analysis_type == "market" or 
            "baseline_summary" in result or 
            "channel_changes" in result
        )
        
        if is_market_analysis:
            # 市场表现分析报告
            baseline_summary = result.get("baseline_summary", {})
            current_summary = result.get("current_summary", {})
            channel_changes = result.get("channel_changes", [])
            abnormal_channels = result.get("abnormal_channels", [])

            # 整体指标
            baseline_roi = baseline_summary.get("overall_roi", 0.0)
            current_roi = current_summary.get("overall_roi", 0.0)
            roi_change = current_roi - baseline_roi

            # 渠道效率对比
            channel_lines = []
            for change in sorted(channel_changes, key=lambda x: abs(x.get("roi_change_rate", 0)), reverse=True):
                channel = change.get("channel", "未知")
                baseline_roi_val = change.get("baseline", {}).get("roi", 0.0)
                current_roi_val = change.get("current", {}).get("roi", 0.0)
                roi_change_val = change.get("roi_change", 0.0)
                roi_change_rate = change.get("roi_change_rate", 0.0)
                ad_spend = change.get("current", {}).get("ad_spend", 0.0)
                revenue = change.get("current", {}).get("revenue", 0.0)
                
                abnormal_mark = " [异常]" if any(ac.get("channel") == channel for ac in abnormal_channels) else ""
                channel_lines.append(
                    f"- {channel}{abnormal_mark}: ROI {baseline_roi_val:.2f} → {current_roi_val:.2f} "
                    f"(变化 {roi_change_val:+.2f}, 变化率 {roi_change_rate:+.2%}), "
                    f"广告花费 ¥{ad_spend:,.2f}, 收入 ¥{revenue:,.2f}"
                )
            channel_breakdown = "\n".join(channel_lines) if channel_lines else "无渠道数据"

            # 异常渠道
            if abnormal_channels:
                abnormal_lines = []
                for ac in abnormal_channels:
                    abnormal_lines.append(
                        f"- {ac.get('channel', '未知')}: ROI 下降 {ac.get('roi_change_rate', 0):.2%}, "
                        f"广告花费变化 ¥{ac.get('ad_spend_change', 0):+,.2f}, "
                        f"收入变化 ¥{ac.get('revenue_change', 0):+,.2f}"
                    )
                abnormal_breakdown = "\n".join(abnormal_lines)
            else:
                abnormal_breakdown = "无显著异常渠道"

            # 时间范围
            baseline_period_data = result.get("baseline_period", {})
            current_period_data = result.get("current_period", {})
            baseline_period = f"{baseline_period_data.get('start', 'N/A')} ~ {baseline_period_data.get('end', 'N/A')}"
            current_period = f"{current_period_data.get('start', 'N/A')} ~ {current_period_data.get('end', 'N/A')}"

            prompt = GENERATE_REPORT_PROMPT.format(
                problem=state.parsed_problem or "各渠道的 ROI 表现如何？",
                baseline_period=baseline_period,
                current_period=current_period,
                baseline_rate=f"{baseline_roi:.2f}",
                current_rate=f"{current_roi:.2f}",
                rate_change=f"{roi_change:+.2f}",
                stage_breakdown="市场表现分析不涉及漏斗环节",
                dimension_breakdown=f"#### 渠道效率对比\n{channel_breakdown}\n\n#### 异常渠道\n{abnormal_breakdown}",
                business_events="无匹配的业务事件",
                attachment_evidence=attachment_evidence,
                retrieved_docs=retrieved_docs
            )
        else:
            # 转化率分析报告（原有逻辑）
            # 整体漏斗
            baseline_rate = result["baseline_funnel"]["order_rate"] * 100
            current_rate = result["current_funnel"]["order_rate"] * 100
            rate_change = result["funnel_change"]["order_rate_change"] * 100

            # 漏斗环节
            stage_lines = []
            for stage in result["stage_decomposition"]["stages"]:
                stage_lines.append(
                    f"- {stage['stage_name']}: {stage['baseline_rate']*100:.2f}% → {stage['current_rate']*100:.2f}% "
                    f"(变化 {stage['rate_change']*100:+.2f}%, 对整体影响 {stage['effect_on_overall']*100:+.4f}%)"
                )
            stage_breakdown = "\n".join(stage_lines)

            dimension_configs = {
                "channel": ("channel_decomposition", "渠道"),
                "device": ("device_decomposition", "设备"),
                "region": ("region_decomposition", "地区"),
                "user_type": ("user_type_decomposition", "新老用户"),
            }
            requested_dimensions = state.parsed_dimensions or list(dimension_configs)
            dimension_blocks = []
            for dimension_key in requested_dimensions:
                config = dimension_configs.get(dimension_key)
                if not config:
                    continue
                result_key, display_name = config
                contributions = result.get(result_key, {}).get("contributions", [])
                if not contributions:
                    continue
                lines = []
                for contribution in sorted(contributions, key=lambda item: abs(item["total_effect"]), reverse=True):
                    lines.append(
                        f"- {contribution['group_name']}: 总效应 {contribution['total_effect']*100:+.4f}% "
                        f"(结构{contribution['share_effect']*100:+.4f}% + 表现{contribution['rate_effect']*100:+.4f}%)"
                    )
                dimension_blocks.append(f"#### {display_name}\n" + "\n".join(lines))
            dimension_breakdown = "\n\n".join(dimension_blocks) or "未指定可分析维度"

            # 业务事件
            event_lines = []
            for event in state.matched_events:
                event_lines.append(f"- {event['title']}: {event['description']}")
            business_events = "\n".join(event_lines) if event_lines else "无匹配的业务事件"

            # 时间范围
            baseline_period = f"{result['time_range']['baseline_start']} ~ {result['time_range']['baseline_end']}"
            current_period = f"{result['time_range']['current_start']} ~ {result['time_range']['current_end']}"

            prompt = GENERATE_REPORT_PROMPT.format(
                problem=state.parsed_problem,
                baseline_period=baseline_period,
                current_period=current_period,
                baseline_rate=f"{baseline_rate:.2f}",
                current_rate=f"{current_rate:.2f}",
                rate_change=f"{rate_change:+.2f}",
                stage_breakdown=stage_breakdown,
                dimension_breakdown=dimension_breakdown,
                business_events=business_events,
                attachment_evidence=attachment_evidence,
                retrieved_docs=retrieved_docs
            )

        # 使用流式输出，实现 message_delta 推送
        messages = [
            SystemMessage(content="你是一个经营分析报告撰写助手，必须基于提供的证据撰写报告，不能编造数据。"),
            HumanMessage(content=prompt)
        ]
        
        full_content = []
        for chunk in llm.stream(messages):
            if chunk.content:
                full_content.append(chunk.content)
                # 发送 message_delta 事件
                emit_progress("message_delta", delta_text=chunk.content)
        
        state.report_draft = "".join(full_content)

    except Exception as e:
        state.errors.append(f"生成报告失败: {str(e)}")
        state.next_action = "error"

    return state
