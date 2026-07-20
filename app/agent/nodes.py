"""
LangGraph 节点函数

每个节点负责一个具体任务：
- parse_question：解析用户问题
- check_completeness：检查信息完整性
- build_request：构造分析请求
- run_analysis：运行分析
- extract_findings：提取关键发现
- generate_report：生成报告
- validate_report：校验证据
- finalize：最终输出
"""

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.state import AnalysisState
from app.agent.progress import emit_progress
from app.agent.prompts import (
    PARSE_QUESTION_PROMPT,
    PARSE_QUESTION_WITH_HISTORY_PROMPT,
    GENERATE_REPORT_PROMPT,
    VALIDATE_REPORT_PROMPT,
    EXTRACT_FINDINGS_PROMPT,
    ATTACHMENT_QUERY_PROMPT,
)
from app.analysis_core.service import (
    run_conversion_analysis, AnalysisRequest, AnalysisResult
)
import app.config as app_config


SUPPORTED_METRIC = "order_conversion_rate"
_METRIC_ALIASES = {
    "order_conversion_rate": SUPPORTED_METRIC,
    "conversion_rate": SUPPORTED_METRIC,
    "下单转化率": SUPPORTED_METRIC,
    "有效下单转化率": SUPPORTED_METRIC,
}
_UNSUPPORTED_METRIC_KEYWORDS = {
    "销售额": "销售额",
    "营收": "营收",
    "收入": "收入",
    "gmv": "GMV",
    "roi": "ROI",
    "客单价": "客单价",
    "复购": "复购率",
    "库存": "库存",
    "周转率": "周转率",
    "周转": "周转率",
}


def _unsupported_metric_label(question: str) -> str | None:
    normalized = question.lower()
    return next((label for keyword, label in _UNSUPPORTED_METRIC_KEYWORDS.items() if keyword in normalized), None)


# ============================================================
# LLM 配置
# ============================================================

def get_llm():
    """获取LLM实例"""
    return ChatOpenAI(
        model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        temperature=0,
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL")
    )


# ============================================================
# 节点函数
# ============================================================

def _format_conversation_history(history: list[dict]) -> str:
    """将历史任务上下文格式化为可读文本，注入 LLM 提示词。"""
    lines = []
    for i, entry in enumerate(history, 1):
        status = entry.get("status", "unknown")
        question = entry.get("question", "")
        clarification = entry.get("clarification_question")
        findings = entry.get("key_findings_summary")

        lines.append(f"第{i}轮 | 用户: {question}")
        if status == "clarify" and clarification:
            lines.append(f"第{i}轮 | 系统追问: {clarification}")
        elif status == "completed" and findings:
            lines.append(f"第{i}轮 | 分析结论: {findings}")
        elif status == "failed":
            lines.append(f"第{i}轮 | 分析未成功")
    return "\n".join(lines)


def parse_question(state: AnalysisState) -> AnalysisState:
    """
    解析用户问题

    从自然语言问题中提取：
    - 问题描述
    - 时间范围
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
        # 提取JSON部分
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        parsed = json.loads(content.strip())

        def parse_date(value: Optional[str]) -> Optional[datetime]:
            if not value:
                return None
            return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)

        state.parsed_problem = parsed.get("problem", state.user_question)
        parsed_metric = str(parsed.get("metric") or SUPPORTED_METRIC).strip().lower()
        state.parsed_metric = _METRIC_ALIASES.get(parsed_metric, parsed_metric)
        state.is_info_complete = bool(parsed.get("is_complete", True))
        state.clarification_question = parsed.get("clarification")
        state.parsed_start = parse_date(parsed.get("start_date"))
        state.parsed_end = parse_date(parsed.get("end_date"))
        state.parsed_compare_start = parse_date(parsed.get("compare_start"))
        state.parsed_compare_end = parse_date(parsed.get("compare_end"))
        state.parsed_dimensions = parsed.get("dimensions", ["channel", "device", "region", "user_type"])

        unsupported_label = _unsupported_metric_label(state.user_question)
        if state.parsed_metric != SUPPORTED_METRIC or unsupported_label:
            state.is_info_complete = False
            state.clarification_question = (
                f"当前演示仅支持有效下单转化率的归因分析，暂不支持{unsupported_label or '该指标'}。"
                "你可以改问：为什么本期下单转化率下降，或按渠道、设备、地区、新老用户拆解转化率。"
            )

        if state.is_info_complete and (not state.parsed_start or not state.parsed_end):
            raise ValueError("完整分析请求必须提供 start_date 和 end_date")

        if not state.is_info_complete and not state.clarification_question:
            state.clarification_question = "请明确要分析的时间范围，例如 2026-07-01 到 2026-07-15。"

    except Exception as e:
        state.errors.append(f"问题解析失败: {str(e)}")
        state.is_info_complete = False
        state.clarification_question = "抱歉，我无法理解您的问题。请明确说明您想分析什么指标，以及时间范围。"

    return state


def check_completeness(state: AnalysisState) -> str:
    """
    检查信息完整性

    Returns:
        "complete" 如果信息完整
        "clarify" 如果需要追问
    """
    print("[节点] 检查信息完整性...")

    if state.is_info_complete and state.parsed_start and state.parsed_end:
        return "complete"
    else:
        return "clarify"


def ask_clarification(state: AnalysisState) -> AnalysisState:
    """
    追问用户

    当信息不完整时，向用户提出澄清问题
    """
    print("[节点] 追问用户...")

    if not state.clarification_question:
        state.clarification_question = "请提供更多信息：您想分析什么指标？时间范围是什么？"

    state.next_action = "clarify"
    return state


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

        available_baseline_start = config_datetime(app_config.BASELINE_START)
        available_baseline_end = config_datetime(app_config.BASELINE_END)
        available_current_start = config_datetime(app_config.CURRENT_START)
        available_current_end = config_datetime(app_config.CURRENT_END)

        is_supported_window = (
            available_baseline_start <= compare_start < compare_end <= available_baseline_end
            and available_current_start <= state.parsed_start < state.parsed_end <= available_current_end
        )
        if not is_supported_window:
            state.clarification_question = (
                "当前演示数据仅覆盖基准期 "
                f"{app_config.BASELINE_START[:10]} 至 {app_config.BASELINE_END[:10]}，以及当前期 "
                f"{app_config.CURRENT_START[:10]} 至 {app_config.CURRENT_END[:10]}。"
                "请在该范围内指定分析周期。"
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


def run_analysis(state: AnalysisState) -> AnalysisState:
    """
    运行分析

    调用 run_conversion_analysis 获取分析结果
    """
    print("[节点] 运行分析...")

    try:
        if not state.analysis_request:
            raise ValueError("缺少分析请求")

        def parse_datetime(value: str) -> datetime:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

        request_data = state.analysis_request
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

    except Exception as e:
        state.errors.append(f"分析失败: {str(e)}")
        state.next_action = "error"

    return state


def extract_findings(state: AnalysisState) -> AnalysisState:
    """
    提取关键发现

    从分析结果中提取最重要的发现
    """
    print("[节点] 提取关键发现...")

    if not state.analysis_result:
        state.errors.append("无分析结果可提取")
        return state

    try:
        findings = []

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


def query_attachments(state: AnalysisState) -> AnalysisState:
    """查询关联附件，提取补充证据。"""
    print("[节点] 查询附件证据...")

    if not state.attachments:
        print("  无关联附件，跳过")
        return state

    try:
        llm = get_llm()
        from app.attachments.engine import preview_attachment, query_attachment, aggregate_attachment

        findings_text = "\n".join(
            f"- {f['dimension']}-{f['group']}: 效应{f['effect']*100:+.2f}%"
            for f in state.key_findings[:5]
        ) if state.key_findings else "暂无关键发现"

        evidence_list = []

        for att in state.attachments:
            att_id = att.get("id")
            if not att_id:
                continue

            try:
                detail = preview_attachment(att_id)
            except Exception as e:
                print(f"  [警告] 无法预览附件 {att.get('filename')}: {e}")
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


def retrieve_documents(state: AnalysisState) -> AnalysisState:
    """从文档库中检索与当前分析相关的片段（RAG）。"""
    print("[节点] 检索相关文档...")

    try:
        from app.rag.retriever import retrieve_context

        query = state.parsed_problem or state.user_question
        chunks, formatted = retrieve_context(query, key_findings=state.key_findings)

        state.retrieved_docs = [c.to_dict() for c in chunks]
        state.retrieved_docs_text = formatted if formatted else None

        if chunks:
            print(f"  找到 {len(chunks)} 个相关文档片段")
        else:
            print("  无相关文档（文档库为空或无匹配）")

    except Exception as e:
        # 文档检索失败不应阻断分析流程
        print(f"  [警告] 文档检索异常: {e}")
        state.retrieved_docs = []
        state.retrieved_docs_text = None

    return state


def generate_report(state: AnalysisState) -> AnalysisState:
    """
    生成报告草稿

    基于分析结果和证据生成报告
    """
    print("[节点] 生成报告...")

    if not state.analysis_result:
        state.errors.append("无分析结果可生成报告")
        state.next_action = "error"
        return state

    try:
        llm = get_llm()

        # 准备报告数据
        result = state.analysis_result

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

        # 文档检索结果（RAG）
        retrieved_docs = state.retrieved_docs_text or "无相关业务文档"

        # 附件查询结果由受控的 Python 查询器生成；截断后再交给 LLM，避免大表
        # 直接挤占报告上下文。报告仍须经过下游证据校验。
        attachment_evidence = "无相关附件证据"
        if state.attachment_evidence:
            attachment_evidence = json.dumps(
                state.attachment_evidence[:5], ensure_ascii=False, default=str
            )[:4000]

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

        response = llm.invoke([
            SystemMessage(content="你是一个经营分析报告撰写助手，必须基于提供的证据撰写报告，不能编造数据。"),
            HumanMessage(content=prompt)
        ])

        state.report_draft = response.content

    except Exception as e:
        state.errors.append(f"生成报告失败: {str(e)}")
        state.next_action = "error"

    return state


def validate_report(state: AnalysisState) -> AnalysisState:
    """
    校验报告

    检查报告中的每条结论是否有证据支持
    """
    print("[节点] 校验证据...")

    if not state.report_draft or not state.evidence:
        state.errors.append("无报告或证据可校验")
        state.is_valid = False
        state.next_action = "error"
        return state

    try:
        llm = get_llm()

        # 准备完整证据摘要。校验器必须看到报告生成器可见的所有数字与业务事件。
        evidence = state.evidence
        evidence_lines = []

        # 漏斗指标
        for m in evidence.get("metrics", []):
            value = m["metric_value"]
            if m["metric_unit"] == "%":
                value_text = f"{value * 100:.4f}%"
            else:
                value_text = str(value)
            evidence_lines.append(
                f"- 指标 | {m['metric_name']} | {value_text} | 周期={m['metric_period']}"
            )

        # 维度证据：总效应、结构效应、表现效应都需要进入校验上下文。
        for d in evidence.get("dimension_evidences", []):
            evidence_lines.append(
                f"- 维度 | {d['dimension_name']}-{d['group_name']} | {d['metric_name']} | "
                f"基准{d['baseline_value']*100:.4f}% → 当前{d['current_value']*100:.4f}% | "
                f"变化{d['change_value']*100:+.4f}% | 效应{d['effect_value']*100:+.4f}%"
            )

        # 业务事件：允许作为关联因素，但不能被写成因果证明。
        for event in evidence.get("business_events", []):
            evidence_lines.append(
                f"- 业务事件（仅关联） | {event['title']} | {event['description']}"
            )

        for attachment in evidence.get("attachment_evidence", []):
            evidence_lines.append(
                f"- 附件证据 | {attachment.get('filename', '未命名附件')} | "
                f"{attachment.get('description', '受控查询结果')}"
            )

        evidence_summary = "\n".join(evidence_lines)

        prompt = VALIDATE_REPORT_PROMPT.format(
            report=state.report_draft,
            evidence_summary=evidence_summary
        )

        response = llm.invoke([
            SystemMessage(content="你是一个证据校验助手。"),
            HumanMessage(content=prompt)
        ])

        # 解析校验结果
        content = response.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]

        validation = json.loads(content.strip())

        state.is_valid = validation.get("is_valid", True)
        state.validation_errors = validation.get("errors", [])

        if not state.is_valid:
            print(f"  [警告] 发现 {len(state.validation_errors)} 个证据问题")

    except Exception as e:
        state.errors.append(f"校验失败: {str(e)}")
        state.validation_errors.append("证据校验无法完成，报告不能作为已验证结果输出。")
        state.is_valid = False
        state.next_action = "error"

    return state


def finalize(state: AnalysisState) -> AnalysisState:
    """
    最终输出

    整合所有结果，生成最终报告
    """
    print("[节点] 生成最终报告...")

    if not state.is_valid:
        state.next_action = "error"
        return state

    if state.report_draft:
        # 添加证据声明
        disclaimer = "\n\n---\n*本报告基于数据分析生成，所有结论均有数据支持。业务事件仅作为关联因素，不构成因果关系证明。*"

        state.report_final = state.report_draft + disclaimer

    # 让持久化结果、导出和前端回放都能看到实际使用过的附件/文档来源。
    if state.evidence is not None:
        state.evidence["attachment_evidence"] = state.attachment_evidence
        state.evidence["retrieved_docs"] = state.retrieved_docs

    state.next_action = "end"
    return state


def handle_error(state: AnalysisState) -> AnalysisState:
    """终止不可信流程，保留错误和草稿供上层界面提示。"""
    print("[节点] 处理流程错误...")

    if state.validation_errors:
        state.errors.extend(
            error for error in state.validation_errors if error not in state.errors
        )

    state.next_action = "error"
    return state
