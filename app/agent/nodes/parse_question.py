"""解析用户问题节点"""

import json
from datetime import datetime, timezone
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.state import AnalysisState
from app.agent.nodes.constants import SUPPORTED_METRIC, MARKET_METRIC, _METRIC_ALIASES
from app.agent.nodes.utils import get_llm, _unsupported_metric_label, _format_conversation_history
from app.agent.nodes.time_utils import TimeGranularity, parse_relative_time
from app.agent.prompts import PARSE_QUESTION_PROMPT, PARSE_QUESTION_WITH_HISTORY_PROMPT
import app.config as app_config


def parse_question(state: AnalysisState) -> AnalysisState:
    """
    解析用户问题

    从自然语言问题中提取：
    - 问题描述
    - 时间范围（支持多段对比）
    - 时间粒度
    - 分析维度

    当 conversation_history 非空时，使用多轮合并提示词。
    """
    print("[节点] 解析问题...")

    llm = get_llm()
    current_date = datetime.now().strftime("%Y-%m-%d")

    common_kwargs = dict(
        user_question=state.user_question,
        current_date=current_date,
        available_baseline_start=app_config.BASELINE_START[:10],
        available_baseline_end=app_config.BASELINE_END[:10],
        available_current_start=app_config.CURRENT_START[:10],
        available_current_end=app_config.CURRENT_END[:10],
    )

    if state.conversation_history:
        history_text = _format_conversation_history(state.conversation_history)
        prompt = PARSE_QUESTION_WITH_HISTORY_PROMPT.format(
            history_text=history_text,
            **common_kwargs,
        )
    else:
        prompt = PARSE_QUESTION_PROMPT.format(**common_kwargs)

    response = llm.invoke([
        SystemMessage(content="你是一个经营分析参数提取助手。"),
        HumanMessage(content=prompt)
    ])

    try:
        # 解析JSON响应
        content = response.content
        print(f"[DEBUG] LLM 原始响应: {content}")
        # 提取JSON部分
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        parsed = json.loads(content.strip())
        print(f"[DEBUG] 解析后的 JSON: {parsed}")

        def parse_date(value: Optional[str]) -> Optional[datetime]:
            if not value:
                return None
            return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)

        state.parsed_problem = parsed.get("problem", state.user_question)
        parsed_metric = str(parsed.get("metric") or SUPPORTED_METRIC).strip().lower()
        state.parsed_metric = _METRIC_ALIASES.get(parsed_metric, parsed_metric)
        state.is_info_complete = bool(parsed.get("is_complete", True))
        state.clarification_question = parsed.get("clarification")
        
        # 解析时间周期列表（新格式）
        time_periods = parsed.get("time_periods", [])
        if time_periods:
            # 使用第一个周期作为当前分析期
            current_period = time_periods[-1] if len(time_periods) > 0 else None
            if current_period:
                state.parsed_start = parse_date(current_period.get("start"))
                state.parsed_end = parse_date(current_period.get("end"))
            
            # 使用倒数第二个周期作为对比期（如果存在）
            if len(time_periods) >= 2:
                compare_period = time_periods[-2]
                state.parsed_compare_start = parse_date(compare_period.get("start"))
                state.parsed_compare_end = parse_date(compare_period.get("end"))
            
            # 存储所有时间周期供后续使用
            state.parsed_time_periods = [
                {
                    "start": parse_date(p.get("start")),
                    "end": parse_date(p.get("end")),
                    "label": p.get("label", f"周期{i+1}")
                }
                for i, p in enumerate(time_periods)
            ]
        else:
            # 兼容旧格式：start_date/end_date/compare_start/compare_end
            state.parsed_start = parse_date(parsed.get("start_date"))
            state.parsed_end = parse_date(parsed.get("end_date"))
            state.parsed_compare_start = parse_date(parsed.get("compare_start"))
            state.parsed_compare_end = parse_date(parsed.get("compare_end"))
        
        # 解析时间粒度
        granularity_str = parsed.get("granularity", "day").lower()
        try:
            state.parsed_granularity = TimeGranularity(granularity_str)
        except ValueError:
            state.parsed_granularity = TimeGranularity.DAY
        
        state.parsed_dimensions = parsed.get("dimensions", ["channel", "device", "region", "user_type"])

        unsupported_label = _unsupported_metric_label(state.user_question)
        # 支持两种指标：转化率和市场表现
        supported_metrics = {SUPPORTED_METRIC, MARKET_METRIC}
        if state.parsed_metric not in supported_metrics or unsupported_label:
            state.is_info_complete = False
            state.clarification_question = (
                f"当前演示仅支持有效下单转化率和市场表现（渠道ROI）的归因分析，暂不支持{unsupported_label or '该指标'}。"
                "你可以改问：为什么本期下单转化率下降，或按渠道、设备、地区、新老用户拆解转化率；"
                "也可以问：各渠道的ROI表现如何，哪个渠道投放效率下降最大。"
            )

        if state.is_info_complete and (not state.parsed_start or not state.parsed_end):
            raise ValueError("完整分析请求必须提供时间范围")

        if not state.is_info_complete and not state.clarification_question:
            state.clarification_question = "请明确要分析的时间范围，例如 2026-07-01 到 2026-07-15。"

    except Exception as e:
        state.errors.append(f"问题解析失败: {str(e)}")
        state.is_info_complete = False
        state.clarification_question = "抱歉，我无法理解您的问题。请明确说明您想分析什么指标，以及时间范围。"

    return state
