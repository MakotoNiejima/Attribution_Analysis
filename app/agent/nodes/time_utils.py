"""
时间处理模块

支持灵活的时间范围解析、聚合和多时间段对比
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum


class TimeGranularity(Enum):
    """时间粒度"""
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"


@dataclass
class TimePeriod:
    """时间周期"""
    start: datetime
    end: datetime
    label: str = ""
    
    @property
    def duration_days(self) -> int:
        """周期天数"""
        return (self.end - self.start).days
    
    def contains(self, dt: datetime) -> bool:
        """判断时间点是否在周期内"""
        return self.start <= dt < self.end
    
    def overlaps(self, other: TimePeriod) -> bool:
        """判断两个周期是否重叠"""
        return self.start < other.end and other.start < self.end


@dataclass
class TimeRange:
    """时间范围（可包含多个周期）"""
    periods: List[TimePeriod]
    granularity: TimeGranularity = TimeGranularity.DAY
    
    @property
    def total_start(self) -> datetime:
        """总起始时间"""
        return min(p.start for p in self.periods)
    
    @property
    def total_end(self) -> datetime:
        """总结束时间"""
        return max(p.end for p in self.periods)
    
    @property
    def total_days(self) -> int:
        """总天数"""
        return (self.total_end - self.total_start).days


def parse_relative_time(expression: str, reference_date: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    """
    解析相对时间表达式
    
    支持：
    - "上周"、"本周"
    - "上月"、"本月"
    - "上季度"、"本季度"
    - "过去7天"、"过去30天"
    - "最近一周"
    
    Args:
        expression: 时间表达式
        reference_date: 参考日期（默认为当前日期）
    
    Returns:
        (start, end) 时间范围
    """
    if reference_date is None:
        reference_date = datetime.now(timezone.utc)
    
    # 标准化表达式
    expr = expression.strip().lower()
    
    # 本周
    if expr in ["本周", "这周", "this week"]:
        # 周一到周日
        weekday = reference_date.weekday()  # 0=周一, 6=周日
        start = reference_date - timedelta(days=weekday)
        end = start + timedelta(days=7)
        return start.replace(hour=0, minute=0, second=0, microsecond=0), \
               end.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # 上周
    if expr in ["上周", "last week"]:
        weekday = reference_date.weekday()
        start = reference_date - timedelta(days=weekday + 7)
        end = start + timedelta(days=7)
        return start.replace(hour=0, minute=0, second=0, microsecond=0), \
               end.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # 本月
    if expr in ["本月", "这个月", "this month"]:
        start = reference_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # 下个月第一天
        if reference_date.month == 12:
            end = reference_date.replace(year=reference_date.year + 1, month=1, day=1)
        else:
            end = reference_date.replace(month=reference_date.month + 1, day=1)
        return start, end
    
    # 上月
    if expr in ["上月", "上个月", "last month"]:
        if reference_date.month == 1:
            start = reference_date.replace(year=reference_date.year - 1, month=12, day=1)
        else:
            start = reference_date.replace(month=reference_date.month - 1, day=1)
        end = reference_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start.replace(hour=0, minute=0, second=0, microsecond=0), end
    
    # 本季度
    if expr in ["本季度", "这个季度", "this quarter"]:
        quarter = (reference_date.month - 1) // 3
        start_month = quarter * 3 + 1
        start = reference_date.replace(month=start_month, day=1, hour=0, minute=0, second=0, microsecond=0)
        end_month = start_month + 3
        if end_month > 12:
            end = reference_date.replace(year=reference_date.year + 1, month=1, day=1)
        else:
            end = reference_date.replace(month=end_month, day=1)
        return start, end
    
    # 上季度
    if expr in ["上季度", "上个季度", "last quarter"]:
        quarter = (reference_date.month - 1) // 3
        if quarter == 0:
            start = reference_date.replace(year=reference_date.year - 1, month=10, day=1)
        else:
            start_month = (quarter - 1) * 3 + 1
            start = reference_date.replace(month=start_month, day=1)
        end = reference_date.replace(month=(quarter * 3 + 1), day=1)
        return start.replace(hour=0, minute=0, second=0, microsecond=0), end
    
    # 过去N天
    import re
    match = re.search(r'过去(\d+)天', expr)
    if match:
        days = int(match.group(1))
        end = reference_date.replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=days)
        return start, end
    
    # 最近N天/周
    match = re.search(r'最近(\d+)(天|周)', expr)
    if match:
        num = int(match.group(1))
        unit = match.group(2)
        end = reference_date.replace(hour=0, minute=0, second=0, microsecond=0)
        if unit == "天":
            start = end - timedelta(days=num)
        else:  # 周
            start = end - timedelta(weeks=num)
        return start, end
    
    # 默认：过去30天
    end = reference_date.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=30)
    return start, end


def split_by_granularity(
    start: datetime,
    end: datetime,
    granularity: TimeGranularity
) -> List[TimePeriod]:
    """
    按时间粒度分割时间范围
    
    Args:
        start: 起始时间
        end: 结束时间
        granularity: 时间粒度
    
    Returns:
        时间周期列表
    """
    periods = []
    current = start
    
    if granularity == TimeGranularity.DAY:
        while current < end:
            next_day = current + timedelta(days=1)
            periods.append(TimePeriod(
                start=current,
                end=min(next_day, end),
                label=current.strftime("%Y-%m-%d")
            ))
            current = next_day
    
    elif granularity == TimeGranularity.WEEK:
        # 按周分割（周一到周日）
        while current < end:
            # 找到本周日
            days_until_sunday = 6 - current.weekday()
            week_end = current + timedelta(days=days_until_sunday + 1)
            week_end = min(week_end, end)
            
            week_label = f"{current.strftime('%Y-%m-%d')}~{(week_end - timedelta(days=1)).strftime('%m-%d')}"
            periods.append(TimePeriod(
                start=current,
                end=week_end,
                label=week_label
            ))
            current = week_end
    
    elif granularity == TimeGranularity.MONTH:
        while current < end:
            # 下个月第一天
            if current.month == 12:
                next_month = current.replace(year=current.year + 1, month=1, day=1)
            else:
                next_month = current.replace(month=current.month + 1, day=1)
            
            month_end = min(next_month, end)
            periods.append(TimePeriod(
                start=current,
                end=month_end,
                label=current.strftime("%Y年%m月")
            ))
            current = next_month
    
    elif granularity == TimeGranularity.QUARTER:
        while current < end:
            # 计算当前季度
            quarter = (current.month - 1) // 3
            quarter_start_month = quarter * 3 + 1
            
            # 下季度第一天
            if quarter_start_month + 3 > 12:
                next_quarter = current.replace(year=current.year + 1, month=1, day=1)
            else:
                next_quarter = current.replace(month=quarter_start_month + 3, day=1)
            
            quarter_end = min(next_quarter, end)
            quarter_label = f"{current.year}Q{quarter + 1}"
            periods.append(TimePeriod(
                start=current,
                end=quarter_end,
                label=quarter_label
            ))
            current = next_quarter
    
    return periods


def detect_granularity(start: datetime, end: datetime, question: str) -> TimeGranularity:
    """
    根据问题内容智能检测时间粒度
    
    Args:
        start: 起始时间
        end: 结束时间
        question: 用户问题
    
    Returns:
        推荐的时间粒度
    """
    question_lower = question.lower()
    
    # 明确提到"周"
    if any(keyword in question for keyword in ["周", "每周", "按周", "weekly"]):
        return TimeGranularity.WEEK
    
    # 明确提到"月"
    if any(keyword in question for keyword in ["月", "每月", "按月", "monthly"]):
        return TimeGranularity.MONTH
    
    # 明确提到"季度"
    if any(keyword in question for keyword in ["季度", "每季", "按季", "quarterly"]):
        return TimeGranularity.QUARTER
    
    # 根据时间跨度自动推断
    days = (end - start).days
    if days <= 30:
        return TimeGranularity.DAY
    elif days <= 90:
        return TimeGranularity.WEEK
    elif days <= 365:
        return TimeGranularity.MONTH
    else:
        return TimeGranularity.QUARTER


def create_comparison_periods(
    current_start: datetime,
    current_end: datetime,
    num_periods: int = 2,
    granularity: Optional[TimeGranularity] = None
) -> List[TimePeriod]:
    """
    创建对比时间段（当前期 + 历史对比期）
    
    Args:
        current_start: 当前期起始
        current_end: 当前期结束
        num_periods: 对比期数量（默认2：当前期 + 1个对比期）
        granularity: 时间粒度（用于自动推断对比期长度）
    
    Returns:
        时间周期列表（从旧到新排序）
    """
    periods = []
    duration = current_end - current_start
    
    # 生成历史对比期（从旧到新）
    for i in range(num_periods - 1, 0, -1):
        period_start = current_start - duration * i
        period_end = current_end - duration * i
        periods.append(TimePeriod(
            start=period_start,
            end=period_end,
            label=f"对比期{i}"
        ))
    
    # 当前期
    periods.append(TimePeriod(
        start=current_start,
        end=current_end,
        label="当前期"
    ))
    
    return periods


def format_time_range_for_llm(
    available_start: datetime,
    available_end: datetime,
    granularity: Optional[TimeGranularity] = None
) -> str:
    """
    格式化时间范围信息供 LLM 使用
    
    Args:
        available_start: 可用数据起始时间
        available_end: 可用数据结束时间
        granularity: 推荐粒度
    
    Returns:
        格式化的时间描述
    """
    days = (available_end - available_start).days
    
    lines = [
        f"可用数据范围：{available_start.strftime('%Y-%m-%d')} 至 {available_end.strftime('%Y-%m-%d')}",
        f"总共 {days} 天的数据",
    ]
    
    if granularity:
        lines.append(f"推荐时间粒度：{granularity.value}")
    
    # 添加使用建议
    if days <= 30:
        lines.append("建议：数据跨度较短，适合按天分析")
    elif days <= 90:
        lines.append("建议：可按周分析趋势")
    elif days <= 365:
        lines.append("建议：可按月分析长期趋势")
    else:
        lines.append("建议：可按季度分析年度趋势")
    
    return "\n".join(lines)
