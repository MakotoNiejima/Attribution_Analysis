"""
LangGraph 节点模块

将原有的 nodes.py 拆分为多个独立文件，提高代码可维护性
"""

from app.agent.nodes.constants import (
    SUPPORTED_METRIC,
    MARKET_METRIC,
    _METRIC_ALIASES,
    _UNSUPPORTED_METRIC_KEYWORDS,
)

from app.agent.nodes.utils import (
    get_llm,
    _unsupported_metric_label,
    _format_conversation_history,
)

from app.agent.nodes.parse_question import parse_question
from app.agent.nodes.check_completeness import check_completeness
from app.agent.nodes.ask_clarification import ask_clarification
from app.agent.nodes.build_request import build_request
from app.agent.nodes.run_analysis import run_analysis
from app.agent.nodes.extract_findings import extract_findings
from app.agent.nodes.generate_report import generate_report
from app.agent.nodes.validate_report import validate_report
from app.agent.nodes.query_attachments import query_attachments
from app.agent.nodes.retrieve_documents import retrieve_documents
from app.agent.nodes.finalize import finalize
from app.agent.nodes.error_handler import handle_error

# 时间工具模块
from app.agent.nodes.time_utils import (
    TimeGranularity,
    TimePeriod,
    TimeRange,
    parse_relative_time,
    split_by_granularity,
    detect_granularity,
    create_comparison_periods,
    format_time_range_for_llm,
)

__all__ = [
    # 常量
    "SUPPORTED_METRIC",
    "MARKET_METRIC",
    
    # 工具函数
    "get_llm",
    
    # 节点函数
    "parse_question",
    "check_completeness",
    "ask_clarification",
    "build_request",
    "run_analysis",
    "extract_findings",
    "generate_report",
    "validate_report",
    "query_attachments",
    "retrieve_documents",
    "finalize",
    "handle_error",
]
