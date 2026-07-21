"""时间类型定义（独立模块，避免循环导入）"""

from enum import Enum


class TimeGranularity(Enum):
    """时间粒度"""
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
