"""
漏斗指标计算

职责：
- 计算访问、加购、有效下单会话数
- 计算加购率、加购后下单率、下单转化率
- 支持整体计算和分组计算
"""

from dataclasses import dataclass
from typing import List, Optional

from app.analysis_core.cohort import SessionRecord, CohortResult


# ============================================================
# 数据结构
# ============================================================

@dataclass
class FunnelMetrics:
    """漏斗指标"""
    visit_sessions: int
    cart_sessions: int
    order_sessions: int

    @property
    def cart_rate(self) -> float:
        """加购率 = 加购会话 / 访问会话"""
        return self.cart_sessions / self.visit_sessions if self.visit_sessions > 0 else 0.0

    @property
    def cart_to_order_rate(self) -> float:
        """加购后下单率 = 下单会话 / 加购会话"""
        return self.order_sessions / self.cart_sessions if self.cart_sessions > 0 else 0.0

    @property
    def order_rate(self) -> float:
        """下单转化率 = 下单会话 / 访问会话"""
        return self.order_sessions / self.visit_sessions if self.visit_sessions > 0 else 0.0

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "visit_sessions": self.visit_sessions,
            "cart_sessions": self.cart_sessions,
            "order_sessions": self.order_sessions,
            "cart_rate": round(self.cart_rate, 4),
            "cart_to_order_rate": round(self.cart_to_order_rate, 4),
            "order_rate": round(self.order_rate, 4)
        }


@dataclass
class FunnelChange:
    """漏斗变化量"""
    baseline: FunnelMetrics
    current: FunnelMetrics

    @property
    def visit_change(self) -> int:
        return self.current.visit_sessions - self.baseline.visit_sessions

    @property
    def cart_change(self) -> int:
        return self.current.cart_sessions - self.baseline.cart_sessions

    @property
    def order_change(self) -> int:
        return self.current.order_sessions - self.baseline.order_sessions

    @property
    def cart_rate_change(self) -> float:
        return self.current.cart_rate - self.baseline.cart_rate

    @property
    def cart_to_order_rate_change(self) -> float:
        return self.current.cart_to_order_rate - self.baseline.cart_to_order_rate

    @property
    def order_rate_change(self) -> float:
        return self.current.order_rate - self.baseline.order_rate

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "visit_change": self.visit_change,
            "cart_change": self.cart_change,
            "order_change": self.order_change,
            "cart_rate_change": round(self.cart_rate_change, 4),
            "cart_to_order_rate_change": round(self.cart_to_order_rate_change, 4),
            "order_rate_change": round(self.order_rate_change, 4)
        }


# ============================================================
# 核心函数
# ============================================================

def calculate_funnel(sessions: List[SessionRecord]) -> FunnelMetrics:
    """
    计算漏斗指标

    Args:
        sessions: 会话记录列表

    Returns:
        FunnelMetrics: 漏斗指标
    """
    visit_count = sum(1 for s in sessions if s.has_visit)
    cart_count = sum(1 for s in sessions if s.has_cart)
    order_count = sum(1 for s in sessions if s.has_order)

    return FunnelMetrics(
        visit_sessions=visit_count,
        cart_sessions=cart_count,
        order_sessions=order_count
    )


def calculate_funnel_from_cohort(cohort: CohortResult) -> FunnelMetrics:
    """
    从会话集合计算漏斗指标

    Args:
        cohort: 会话集合

    Returns:
        FunnelMetrics: 漏斗指标
    """
    return calculate_funnel(cohort.sessions)


def calculate_funnel_change(baseline: FunnelMetrics, current: FunnelMetrics) -> FunnelChange:
    """
    计算漏斗变化量

    Args:
        baseline: 基准期指标
        current: 当前期指标

    Returns:
        FunnelChange: 变化量
    """
    return FunnelChange(baseline=baseline, current=current)


# ============================================================
# 分组计算
# ============================================================

def calculate_funnel_by_channel(cohort: CohortResult) -> dict:
    """
    按渠道分组计算漏斗

    Returns:
        {channel: FunnelMetrics}
    """
    # 按渠道分组
    groups = {}
    for session in cohort.sessions:
        channel = session.channel
        if channel not in groups:
            groups[channel] = []
        groups[channel].append(session)

    # 计算每个分组的指标
    result = {}
    for channel, sessions in groups.items():
        result[channel] = calculate_funnel(sessions)

    return result


def calculate_funnel_by_device(cohort: CohortResult) -> dict:
    """
    按设备分组计算漏斗

    Returns:
        {device_type: FunnelMetrics}
    """
    groups = {}
    for session in cohort.sessions:
        device = session.device_type
        groups.setdefault(device, []).append(session)

    result = {}
    for device, sessions in groups.items():
        result[device] = calculate_funnel(sessions)

    return result


def calculate_funnel_by_region(cohort: CohortResult) -> dict:
    """
    按地区分组计算漏斗

    Returns:
        {region_code: FunnelMetrics}
    """
    groups = {}
    for session in cohort.sessions:
        region = session.region_code or "unknown"
        groups.setdefault(region, []).append(session)

    result = {}
    for region, sessions in groups.items():
        result[region] = calculate_funnel(sessions)

    return result


def calculate_funnel_by_user_type(cohort: CohortResult) -> dict:
    """
    按用户类型分组计算漏斗

    Returns:
        {user_type: FunnelMetrics}
    """
    groups = {}
    for session in cohort.sessions:
        user_type = session.user_type_snapshot
        groups.setdefault(user_type, []).append(session)

    result = {}
    for user_type, sessions in groups.items():
        result[user_type] = calculate_funnel(sessions)

    return result


# ============================================================
# 辅助函数
# ============================================================

def format_percentage(value: float) -> str:
    """格式化百分比"""
    return f"{value * 100:.2f}%"


def format_change(value: float) -> str:
    """格式化变化量"""
    return f"{value * 100:+.2f}%"


def print_funnel_comparison(
    label: str,
    baseline: FunnelMetrics,
    current: FunnelMetrics
):
    """打印漏斗对比"""
    change = calculate_funnel_change(baseline, current)

    print(f"\n{label}:")
    print(f"  {'指标':<15} {'基准期':>10} {'当前期':>10} {'变化':>10}")
    print(f"  {'-'*48}")
    print(f"  {'访问会话':<15} {baseline.visit_sessions:>10} {current.visit_sessions:>10} {change.visit_change:>+10}")
    print(f"  {'加购会话':<15} {baseline.cart_sessions:>10} {current.cart_sessions:>10} {change.cart_change:>+10}")
    print(f"  {'下单会话':<15} {baseline.order_sessions:>10} {current.order_sessions:>10} {change.order_change:>+10}")
    print(f"  {'加购率':<15} {format_percentage(baseline.cart_rate):>10} {format_percentage(current.cart_rate):>10} {format_change(change.cart_rate_change):>10}")
    print(f"  {'加购后下单率':<15} {format_percentage(baseline.cart_to_order_rate):>10} {format_percentage(current.cart_to_order_rate):>10} {format_change(change.cart_to_order_rate_change):>10}")
    print(f"  {'下单转化率':<15} {format_percentage(baseline.order_rate):>10} {format_percentage(current.order_rate):>10} {format_change(change.order_rate_change):>10}")


# ============================================================
# 测试代码
# ============================================================

if __name__ == "__main__":
    from datetime import datetime, timezone
    from analysis_core.cohort import build_cohort

    baseline_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    baseline_end = datetime(2026, 6, 15, tzinfo=timezone.utc)
    current_start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    current_end = datetime(2026, 7, 15, tzinfo=timezone.utc)

    print("=" * 60)
    print("漏斗指标计算测试")
    print("=" * 60)

    # 构建会话集合
    baseline_cohort = build_cohort(baseline_start, baseline_end, "baseline")
    current_cohort = build_cohort(current_start, current_end, "current")

    # 计算整体漏斗
    baseline_funnel = calculate_funnel_from_cohort(baseline_cohort)
    current_funnel = calculate_funnel_from_cohort(current_cohort)

    print_funnel_comparison("整体漏斗", baseline_funnel, current_funnel)

    # 按渠道分组
    print("\n" + "=" * 60)
    print("按渠道分组")
    print("=" * 60)

    baseline_by_channel = calculate_funnel_by_channel(baseline_cohort)
    current_by_channel = calculate_funnel_by_channel(current_cohort)

    print(f"\n{'渠道':<15} {'基准期转化率':>12} {'当前期转化率':>12} {'变化':>10}")
    print("-" * 52)

    for channel in sorted(set(list(baseline_by_channel.keys()) + list(current_by_channel.keys()))):
        b = baseline_by_channel.get(channel)
        c = current_by_channel.get(channel)
        b_rate = b.order_rate if b else 0
        c_rate = c.order_rate if c else 0
        change = c_rate - b_rate
        print(f"  {channel:<15} {format_percentage(b_rate):>12} {format_percentage(c_rate):>12} {format_change(change):>10}")

    # 按设备分组
    print("\n" + "=" * 60)
    print("按设备分组")
    print("=" * 60)

    baseline_by_device = calculate_funnel_by_device(baseline_cohort)
    current_by_device = calculate_funnel_by_device(current_cohort)

    print(f"\n{'设备':<15} {'基准期转化率':>12} {'当前期转化率':>12} {'变化':>10}")
    print("-" * 52)

    for device in sorted(set(list(baseline_by_device.keys()) + list(current_by_device.keys()))):
        b = baseline_by_device.get(device)
        c = current_by_device.get(device)
        b_rate = b.order_rate if b else 0
        c_rate = c.order_rate if c else 0
        change = c_rate - b_rate
        print(f"  {device:<15} {format_percentage(b_rate):>12} {format_percentage(c_rate):>12} {format_change(change):>10}")
