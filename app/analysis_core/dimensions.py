"""
按渠道、设备、地区、用户类型、商品做同口径统计

职责：
- 按各维度分组计算漏斗指标
- 维度间的汇总一致性校验
- 为后续的贡献度拆解提供数据基础
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from app.analysis_core.cohort import SessionRecord, CohortResult
from app.analysis_core.metrics import FunnelMetrics, calculate_funnel


# ============================================================
# 数据结构
# ============================================================

@dataclass
class DimensionBreakdown:
    """维度拆解结果"""
    dimension_name: str  # 维度名称：channel/device/region/user_type
    groups: Dict[str, FunnelMetrics]  # 分组 -> 指标

    @property
    def total_visit(self) -> int:
        """访问会话总数"""
        return sum(m.visit_sessions for m in self.groups.values())

    @property
    def total_cart(self) -> int:
        """加购会话总数"""
        return sum(m.cart_sessions for m in self.groups.values())

    @property
    def total_order(self) -> int:
        """下单会话总数"""
        return sum(m.order_sessions for m in self.groups.values())

    def get_group_names(self) -> List[str]:
        """获取所有分组名称"""
        return sorted(self.groups.keys())

    def get_group(self, name: str) -> Optional[FunnelMetrics]:
        """获取指定分组的指标"""
        return self.groups.get(name)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "dimension_name": self.dimension_name,
            "groups": {name: m.to_dict() for name, m in self.groups.items()},
            "total_visit": self.total_visit,
            "total_cart": self.total_cart,
            "total_order": self.total_order
        }


@dataclass
class DimensionComparison:
    """维度对比结果"""
    dimension_name: str
    baseline: DimensionBreakdown
    current: DimensionBreakdown

    def get_group_names(self) -> List[str]:
        """获取所有分组名称"""
        return sorted(set(
            list(self.baseline.groups.keys()) +
            list(self.current.groups.keys())
        ))

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "dimension_name": self.dimension_name,
            "baseline": self.baseline.to_dict(),
            "current": self.current.to_dict()
        }


# ============================================================
# 核心函数
# ============================================================

def group_sessions_by_field(
    sessions: List[SessionRecord],
    field_name: str
) -> Dict[str, List[SessionRecord]]:
    """
    按字段分组会话

    Args:
        sessions: 会话列表
        field_name: 字段名（channel/device_type/region_code/user_type_snapshot）

    Returns:
        {field_value: [SessionRecord, ...]}
    """
    groups = {}
    for session in sessions:
        if field_name == "channel":
            key = session.channel
        elif field_name == "device_type":
            key = session.device_type
        elif field_name == "region_code":
            key = session.region_code or "unknown"
        elif field_name == "user_type_snapshot":
            key = session.user_type_snapshot
        else:
            raise ValueError(f"Unknown field: {field_name}")

        groups.setdefault(key, []).append(session)

    return groups


def calculate_dimension_breakdown(
    cohort: CohortResult,
    dimension_name: str,
    field_name: str
) -> DimensionBreakdown:
    """
    计算单个维度的拆解结果

    Args:
        cohort: 会话集合
        dimension_name: 维度名称（用于展示）
        field_name: 数据库字段名

    Returns:
        DimensionBreakdown: 维度拆解结果
    """
    groups = group_sessions_by_field(cohort.sessions, field_name)

    result = {}
    for key, sessions in groups.items():
        result[key] = calculate_funnel(sessions)

    return DimensionBreakdown(
        dimension_name=dimension_name,
        groups=result
    )


def calculate_all_dimensions(cohort: CohortResult) -> Dict[str, DimensionBreakdown]:
    """
    计算所有维度的拆解结果

    Returns:
        {dimension_name: DimensionBreakdown}
    """
    dimensions = {
        "channel": calculate_dimension_breakdown(cohort, "渠道", "channel"),
        "device": calculate_dimension_breakdown(cohort, "设备", "device_type"),
        "region": calculate_dimension_breakdown(cohort, "地区", "region_code"),
        "user_type": calculate_dimension_breakdown(cohort, "用户类型", "user_type_snapshot"),
    }

    return dimensions


def compare_dimensions(
    baseline_cohort: CohortResult,
    current_cohort: CohortResult,
    dimension_name: str,
    field_name: str
) -> DimensionComparison:
    """
    对比两个周期的维度拆解

    Args:
        baseline_cohort: 基准期会话集合
        current_cohort: 当前期会话集合
        dimension_name: 维度名称
        field_name: 数据库字段名

    Returns:
        DimensionComparison: 对比结果
    """
    baseline = calculate_dimension_breakdown(baseline_cohort, dimension_name, field_name)
    current = calculate_dimension_breakdown(current_cohort, dimension_name, field_name)

    return DimensionComparison(
        dimension_name=dimension_name,
        baseline=baseline,
        current=current
    )


def compare_all_dimensions(
    baseline_cohort: CohortResult,
    current_cohort: CohortResult
) -> Dict[str, DimensionComparison]:
    """
    对比所有维度

    Returns:
        {dimension_name: DimensionComparison}
    """
    comparisons = {
        "channel": compare_dimensions(baseline_cohort, current_cohort, "渠道", "channel"),
        "device": compare_dimensions(baseline_cohort, current_cohort, "设备", "device_type"),
        "region": compare_dimensions(baseline_cohort, current_cohort, "地区", "region_code"),
        "user_type": compare_dimensions(baseline_cohort, current_cohort, "用户类型", "user_type_snapshot"),
    }

    return comparisons


# ============================================================
# 校验函数
# ============================================================

def validate_dimension_sum(
    cohort: CohortResult,
    dimension: DimensionBreakdown
) -> bool:
    """
    校验维度拆解的汇总是否等于整体

    Returns:
        True 如果校验通过
    """
    total_visit = sum(m.visit_sessions for m in dimension.groups.values())
    total_cart = sum(m.cart_sessions for m in dimension.groups.values())
    total_order = sum(m.order_sessions for m in dimension.groups.values())

    return (
        total_visit == cohort.visit_sessions and
        total_cart == cohort.cart_sessions and
        total_order == cohort.order_sessions
    )


# ============================================================
# 辅助函数
# ============================================================

def format_percentage(value: float) -> str:
    """格式化百分比"""
    return f"{value * 100:.2f}%"


def print_dimension_comparison(comparison: DimensionComparison):
    """打印维度对比"""
    print(f"\n{comparison.dimension_name}对比:")
    print(f"  {'分组':<15} {'基准期访问':>10} {'基准期下单':>10} {'基准期转化率':>12} {'当前期访问':>10} {'当前期下单':>10} {'当前期转化率':>12} {'变化':>10}")
    print("  " + "-" * 100)

    for name in comparison.get_group_names():
        b = comparison.baseline.get_group(name)
        c = comparison.current.get_group(name)

        b_visit = b.visit_sessions if b else 0
        b_order = b.order_sessions if b else 0
        b_rate = b.order_rate if b else 0

        c_visit = c.visit_sessions if c else 0
        c_order = c.order_sessions if c else 0
        c_rate = c.order_rate if c else 0

        change = c_rate - b_rate

        print(f"  {name:<15} {b_visit:>10} {b_order:>10} {format_percentage(b_rate):>12} {c_visit:>10} {c_order:>10} {format_percentage(c_rate):>12} {change:>+10.2f}%")


# ============================================================
# 测试代码
# ============================================================

if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    from datetime import datetime, timezone
    from analysis_core.cohort import build_cohort

    baseline_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    baseline_end = datetime(2026, 6, 15, tzinfo=timezone.utc)
    current_start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    current_end = datetime(2026, 7, 15, tzinfo=timezone.utc)

    print("=" * 60)
    print("维度拆解测试")
    print("=" * 60)

    # 构建会话集合
    baseline_cohort = build_cohort(baseline_start, baseline_end, "baseline")
    current_cohort = build_cohort(current_start, current_end, "current")

    # 计算所有维度对比
    comparisons = compare_all_dimensions(baseline_cohort, current_cohort)

    # 打印渠道对比
    print_dimension_comparison(comparisons["channel"])

    # 打印设备对比
    print_dimension_comparison(comparisons["device"])

    # 校验维度汇总
    print("\n" + "=" * 60)
    print("维度汇总校验")
    print("=" * 60)

    for dim_name, comp in comparisons.items():
        b_valid = validate_dimension_sum(baseline_cohort, comp.baseline)
        c_valid = validate_dimension_sum(current_cohort, comp.current)
        print(f"  {comp.dimension_name}: 基准期={'PASS' if b_valid else 'FAIL'}, 当前期={'PASS' if c_valid else 'FAIL'}")
