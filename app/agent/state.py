"""
LangGraph 图状态定义

状态在各节点之间传递，包含：
- 用户输入
- 解析结果
- 分析结果
- 证据
- 报告
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime

@dataclass
class AnalysisState:
    """分析状态"""

    # 用户输入
    user_question: str = ""
    conversation_id: Optional[str] = None

    # 多轮对话历史（由 persistence 层注入，parse_question 节点消费）
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)

    # 解析结果
    parsed_problem: Optional[str] = None
    parsed_start: Optional[datetime] = None
    parsed_end: Optional[datetime] = None
    parsed_compare_start: Optional[datetime] = None
    parsed_compare_end: Optional[datetime] = None
    parsed_dimensions: List[str] = field(default_factory=list)
    is_info_complete: bool = False
    clarification_question: Optional[str] = None

    # 分析请求
    analysis_request: Optional[Dict[str, Any]] = None

    # 分析结果
    analysis_result: Optional[Dict[str, Any]] = None

    # 主要发现
    key_findings: List[Dict[str, Any]] = field(default_factory=list)

    # 证据
    evidence: Optional[Dict[str, Any]] = None
    matched_events: List[Dict[str, Any]] = field(default_factory=list)

    # 文档检索结果（RAG）
    retrieved_docs: List[Dict[str, Any]] = field(default_factory=list)
    retrieved_docs_text: Optional[str] = None

    # 附件证据（结构化文件查询结果）
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    attachment_evidence: List[Dict[str, Any]] = field(default_factory=list)

    # 报告
    report_draft: Optional[str] = None
    report_final: Optional[str] = None

    # 验证
    validation_errors: List[str] = field(default_factory=list)
    is_valid: bool = True

    # 错误
    errors: List[str] = field(default_factory=list)

    # 流程控制
    next_action: str = "continue"  # continue / clarify / error / end


@dataclass
class Finding:
    """单个发现"""
    dimension: str  # 渠道/设备/地区/漏斗环节
    group: str  # 分组名称
    effect: float  # 效应值
    effect_type: str  # share/rate/total
    evidence_ref: str  # 证据引用
    description: str  # 描述

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension,
            "group": self.group,
            "effect": self.effect,
            "effect_type": self.effect_type,
            "evidence_ref": self.evidence_ref,
            "description": self.description
        }
