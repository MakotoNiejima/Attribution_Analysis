"""工具函数"""

import os
from datetime import datetime
from typing import Optional

from langchain_openai import ChatOpenAI

from app.agent.nodes.constants import _UNSUPPORTED_METRIC_KEYWORDS


def get_llm():
    """获取LLM实例"""
    return ChatOpenAI(
        model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        temperature=0,
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL")
    )


def _unsupported_metric_label(question: str) -> str | None:
    """检查是否包含不支持的指标关键词"""
    normalized = question.lower()
    return next((label for keyword, label in _UNSUPPORTED_METRIC_KEYWORDS.items() if keyword in normalized), None)


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
        elif status == "success" and findings:
            lines.append(f"第{i}轮 | 分析结论: {findings}")
        elif status == "failed":
            lines.append(f"第{i}轮 | 分析未成功")
    return "\n".join(lines)
