"""
GMV（销售额）指标计算与归因拆解

职责：
- 计算基线与当前期 GMV 总量、变化
- 按 channel/device/region/user_type 进行对称分解
- 复用现有订单/归因数据（SessionRecord.order_amount）

GMV 计算公式：
  GMV = Σ order_amount，仅统计有效订单会话（has_order=True）

GMV 拆解公式（对称分解，与 order_conversion_rate 同构）：
  对每个维度分组 i：
    定义 revenue_per_visit_i = GMV_i / visit_sessions_i（类比 order_rate）
    定义 visit_share_i       = visit_sessions_i / total_visit_sessions

    整体指标 = total_GMV / total_visits（单访客收入）

    Δ(整体指标) = Σ [Δ(visit_share_i) × (r0_i + r1_i) / 2
                   + Δ(revenue_per_visit_i) × (s0_i + s1_i) / 2]

    其中：
      share_effect_i（流量结构效应）= Δs_i × (r0_i + r1_i) / 2
      rate_effect_i（收入效率效应）  = Δr_i × (s0_i + s1_i) / 2
      total_effect_i = share_effect_i + rate_effect_i

  效应之和严格等于总效应，无交叉项残留。
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from app.analysis_core.cohort import SessionRecord, CohortResult
from app.analysis_core.dimensions import group_sessions_by_field


# ============================================================
# 数据结构
# ============================================================

@dataclass
class GmvMetrics:
    """GMV 指标"""
    total_gmv: float
    order_sessions: int
    visit_sessions: int

    @property
    def avg_order_value(self) -> float:
        """客单价 = GMV / 订单会话数"""
        return self.total_gmv / self.order_sessions if self.order_sessions > 0 else 0.0

    @property
    def revenue_per_visit(self) -> float:
        """单访客收入（类比 order_rate）= GMV / 访问会话数"""
        return self.total_gmv / self.visit_sessions if self.visit_sessions > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "total_gmv": round(self.total_gmv, 2),
            "order_sessions": self.order_sessions,
            "visit_sessions": self.visit_sessions,
            "avg_order_value": round(self.avg_order_value, 2),
            "revenue_per_visit": round(self.revenue_per_visit, 4),
        }


@dataclass
class GmvChange:
    """GMV 变化量"""
    baseline: GmvMetrics
    current: GmvMetrics

    @property
    def gmv_change(self) -> float:
        """GMV 绝对变化"""
        return self.current.total_gmv - self.baseline.total_gmv

    @property
    def gmv_change_rate(self) -> float:
        """GMV 变化率"""
        return self.gmv_change / self.baseline.total_gmv if self.baseline.total_gmv > 0 else 0.0

    @property
    def revenue_per_visit_change(self) -> float:
        """单访客收入变化（用于拆解）"""
        return self.current.revenue_per_visit - self.baseline.revenue_per_visit

    def to_dict(self) -> dict:
        return {
            "baseline_gmv": round(self.baseline.total_gmv, 2),
            "current_gmv": round(self.current.total_gmv, 2),
            "gmv_change": round(self.gmv_change, 2),
            "gmv_change_rate": round(self.gmv_change_rate, 4),
            "revenue_per_visit_change": round(self.revenue_per_visit_change, 6),
        }


# ============================================================
# GMV 计算
# ============================================================

def calculate_gmv(sessions: List[SessionRecord]) -> GmvMetrics:
    """
    计算 GMV 指标

    Args:
        sessions: 会话记录列表

    Returns:
        GmvMetrics: GMV 指标
    """
    total_gmv = sum(s.order_amount for s in sessions if s.has_order)
    order_count = sum(1 for s in sessions if s.has_order)
    visit_count = sum(1 for s in sessions if s.has_visit)

    return GmvMetrics(
        total_gmv=total_gmv,
        order_sessions=order_count,
        visit_sessions=visit_count,
    )


def calculate_gmv_from_cohort(cohort: CohortResult) -> GmvMetrics:
    """
    从会话集合计算 GMV 指标

    Args:
        cohort: 会话集合

    Returns:
        GmvMetrics: GMV 指标
    """
    return calculate_gmv(cohort.sessions)


def calculate_gmv_change(baseline: GmvMetrics, current: GmvMetrics) -> GmvChange:
    """
    计算 GMV 变化量

    Args:
        baseline: 基准期 GMV 指标
        current: 当前期 GMV 指标

    Returns:
        GmvChange: 变化量
    """
    return GmvChange(baseline=baseline, current=current)


# ============================================================
# 按维度分组计算 GMV
# ============================================================

def calculate_gmv_by_channel(cohort: CohortResult) -> dict:
    """按渠道分组计算 GMV"""
    groups = group_sessions_by_field(cohort.sessions, "channel")
    return {channel: calculate_gmv(sessions) for channel, sessions in groups.items()}


def calculate_gmv_by_device(cohort: CohortResult) -> dict:
    """按设备分组计算 GMV"""
    groups = group_sessions_by_field(cohort.sessions, "device_type")
    return {device: calculate_gmv(sessions) for device, sessions in groups.items()}


def calculate_gmv_by_region(cohort: CohortResult) -> dict:
    """按地区分组计算 GMV"""
    groups = group_sessions_by_field(cohort.sessions, "region_code")
    return {region: calculate_gmv(sessions) for region, sessions in groups.items()}


def calculate_gmv_by_user_type(cohort: CohortResult) -> dict:
    """按用户类型分组计算 GMV"""
    groups = group_sessions_by_field(cohort.sessions, "user_type_snapshot")
    return {ut: calculate_gmv(sessions) for ut, sessions in groups.items()}


# ============================================================
# GMV 拆解（对称分解）
# ============================================================

@dataclass
class GmvGroupContribution:
    """单个分组的 GMV 贡献度"""
    group_name: str

    # 基准期数据
    baseline_visit: int
    baseline_gmv: float
    baseline_revenue_per_visit: float
    baseline_visit_share: float

    # 当前期数据
    current_visit: int
    current_gmv: float
    current_revenue_per_visit: float
    current_visit_share: float

    # 变化量
    share_change: float
    rate_change: float

    # 贡献度（对整体 revenue_per_visit 的影响，以元/访客为单位）
    share_effect: float
    rate_effect: float
    total_effect: float

    def to_dict(self) -> dict:
        return {
            "group_name": self.group_name,
            "baseline_visit": self.baseline_visit,
            "baseline_gmv": round(self.baseline_gmv, 2),
            "baseline_revenue_per_visit": round(self.baseline_revenue_per_visit, 4),
            "baseline_visit_share": round(self.baseline_visit_share, 4),
            "current_visit": self.current_visit,
            "current_gmv": round(self.current_gmv, 2),
            "current_revenue_per_visit": round(self.current_revenue_per_visit, 4),
            "current_visit_share": round(self.current_visit_share, 4),
            "share_change": round(self.share_change, 4),
            "rate_change": round(self.rate_change, 4),
            "share_effect": round(self.share_effect, 6),
            "rate_effect": round(self.rate_effect, 6),
            "total_effect": round(self.total_effect, 6),
        }


@dataclass
class GmvDecompositionResult:
    """GMV 拆解结果"""
    dimension_name: str

    # 整体数据
    baseline_total_visit: int
    baseline_total_gmv: float
    baseline_revenue_per_visit: float

    current_total_visit: int
    current_total_gmv: float
    current_revenue_per_visit: float

    # 效应汇总
    total_effect: float  # 总效应（元/访客）
    total_share_effect: float
    total_rate_effect: float

    # 各分组贡献
    contributions: List[GmvGroupContribution]

    # GMV 绝对变化（元）
    gmv_change_absolute: float

    def get_contributions_sorted_by_total_effect(self) -> List[GmvGroupContribution]:
        return sorted(self.contributions, key=lambda x: abs(x.total_effect), reverse=True)

    def to_dict(self) -> dict:
        return {
            "dimension_name": self.dimension_name,
            "baseline": {
                "total_visit": self.baseline_total_visit,
                "total_gmv": round(self.baseline_total_gmv, 2),
                "revenue_per_visit": round(self.baseline_revenue_per_visit, 4),
            },
            "current": {
                "total_visit": self.current_total_visit,
                "total_gmv": round(self.current_total_gmv, 2),
                "revenue_per_visit": round(self.current_revenue_per_visit, 4),
            },
            "effects": {
                "total_effect": round(self.total_effect, 6),
                "total_share_effect": round(self.total_share_effect, 6),
                "total_rate_effect": round(self.total_rate_effect, 6),
            },
            "gmv_change_absolute": round(self.gmv_change_absolute, 2),
            "contributions": [c.to_dict() for c in self.contributions],
        }


def decompose_gmv_dimension(
    baseline_cohort: CohortResult,
    current_cohort: CohortResult,
    dimension_name: str,
    field_name: str,
) -> GmvDecompositionResult:
    """
    对单个维度进行 GMV 对称分解

    使用对称分解公式，确保各分组效应之和严格等于总效应。

    对每个分组 i：
      share_effect_i = Δ(visit_share_i) × (r0_i + r1_i) / 2   （流量结构效应）
      rate_effect_i  = Δ(revenue_per_visit_i) × (s0_i + s1_i) / 2 （收入效率效应）
      total_effect_i = share_effect_i + rate_effect_i

    其中：
      s_i = visit_share_i（访问量占比）
      r_i = revenue_per_visit_i（单访客收入 = GMV_i / visit_i）
      0 = 基准期，1 = 当前期

    Args:
        baseline_cohort: 基准期会话集合
        current_cohort: 当前期会话集合
        dimension_name: 维度名称（用于展示）
        field_name: 数据库字段名

    Returns:
        GmvDecompositionResult: 拆解结果
    """
    # 分组
    baseline_groups = group_sessions_by_field(baseline_cohort.sessions, field_name)
    current_groups = group_sessions_by_field(current_cohort.sessions, field_name)

    # 计算各分组 GMV
    baseline_gmv_by_group = {k: calculate_gmv(v) for k, v in baseline_groups.items()}
    current_gmv_by_group = {k: calculate_gmv(v) for k, v in current_groups.items()}

    # 整体指标
    baseline_total_visit = baseline_cohort.visit_sessions
    baseline_total_gmv = sum(m.total_gmv for m in baseline_gmv_by_group.values())
    baseline_rpv = baseline_total_gmv / baseline_total_visit if baseline_total_visit > 0 else 0.0

    current_total_visit = current_cohort.visit_sessions
    current_total_gmv = sum(m.total_gmv for m in current_gmv_by_group.values())
    current_rpv = current_total_gmv / current_total_visit if current_total_visit > 0 else 0.0

    # 总效应（元/访客）
    total_effect = current_rpv - baseline_rpv

    # GMV 绝对变化
    gmv_change_absolute = current_total_gmv - baseline_total_gmv

    # 所有分组
    all_groups = sorted(set(
        list(baseline_gmv_by_group.keys()) + list(current_gmv_by_group.keys())
    ))

    # 计算各分组贡献
    contributions = []
    total_share_effect = 0.0
    total_rate_effect = 0.0

    for group_name in all_groups:
        b_metrics = baseline_gmv_by_group.get(group_name)
        c_metrics = current_gmv_by_group.get(group_name)

        # 基准期
        b_visit = b_metrics.visit_sessions if b_metrics else 0
        b_gmv = b_metrics.total_gmv if b_metrics else 0.0
        b_rpv = b_metrics.revenue_per_visit if b_metrics else 0.0
        b_share = b_visit / baseline_total_visit if baseline_total_visit > 0 else 0.0

        # 当前期
        c_visit = c_metrics.visit_sessions if c_metrics else 0
        c_gmv = c_metrics.total_gmv if c_metrics else 0.0
        c_rpv = c_metrics.revenue_per_visit if c_metrics else 0.0
        c_share = c_visit / current_total_visit if current_total_visit > 0 else 0.0

        # 变化量
        share_change = c_share - b_share
        rate_change = c_rpv - b_rpv

        # 对称分解
        share_effect = share_change * (b_rpv + c_rpv) / 2
        rate_effect = rate_change * (b_share + c_share) / 2
        group_total_effect = share_effect + rate_effect

        total_share_effect += share_effect
        total_rate_effect += rate_effect

        contributions.append(GmvGroupContribution(
            group_name=group_name,
            baseline_visit=b_visit,
            baseline_gmv=b_gmv,
            baseline_revenue_per_visit=b_rpv,
            baseline_visit_share=b_share,
            current_visit=c_visit,
            current_gmv=c_gmv,
            current_revenue_per_visit=c_rpv,
            current_visit_share=c_share,
            share_change=share_change,
            rate_change=rate_change,
            share_effect=share_effect,
            rate_effect=rate_effect,
            total_effect=group_total_effect,
        ))

    return GmvDecompositionResult(
        dimension_name=dimension_name,
        baseline_total_visit=baseline_total_visit,
        baseline_total_gmv=baseline_total_gmv,
        baseline_revenue_per_visit=baseline_rpv,
        current_total_visit=current_total_visit,
        current_total_gmv=current_total_gmv,
        current_revenue_per_visit=current_rpv,
        total_effect=total_effect,
        total_share_effect=total_share_effect,
        total_rate_effect=total_rate_effect,
        contributions=contributions,
        gmv_change_absolute=gmv_change_absolute,
    )


# ============================================================
# 便捷函数
# ============================================================

def decompose_gmv_channel(
    baseline_cohort: CohortResult,
    current_cohort: CohortResult,
) -> GmvDecompositionResult:
    """按渠道拆解 GMV"""
    return decompose_gmv_dimension(baseline_cohort, current_cohort, "渠道", "channel")


def decompose_gmv_device(
    baseline_cohort: CohortResult,
    current_cohort: CohortResult,
) -> GmvDecompositionResult:
    """按设备拆解 GMV"""
    return decompose_gmv_dimension(baseline_cohort, current_cohort, "设备", "device_type")


def decompose_gmv_region(
    baseline_cohort: CohortResult,
    current_cohort: CohortResult,
) -> GmvDecompositionResult:
    """按地区拆解 GMV"""
    return decompose_gmv_dimension(baseline_cohort, current_cohort, "地区", "region_code")


def decompose_gmv_user_type(
    baseline_cohort: CohortResult,
    current_cohort: CohortResult,
) -> GmvDecompositionResult:
    """按用户类型拆解 GMV"""
    return decompose_gmv_dimension(baseline_cohort, current_cohort, "用户类型", "user_type_snapshot")


# ============================================================
# 辅助函数
# ============================================================

def format_currency(value: float) -> str:
    """格式化金额"""
    return f"¥{value:,.2f}"


def print_gmv_comparison(
    label: str,
    baseline: GmvMetrics,
    current: GmvMetrics,
):
    """打印 GMV 对比"""
    change = calculate_gmv_change(baseline, current)

    print(f"\n{label}:")
    print(f"  {'指标':<20} {'基准期':>15} {'当前期':>15} {'变化':>15}")
    print(f"  {'-'*68}")
    print(f"  {'GMV':<20} {format_currency(baseline.total_gmv):>15} {format_currency(current.total_gmv):>15} {format_currency(change.gmv_change):>15}")
    print(f"  {'订单会话':<20} {baseline.order_sessions:>15} {current.order_sessions:>15} {current.order_sessions - baseline.order_sessions:>+15}")
    print(f"  {'客单价':<20} {format_currency(baseline.avg_order_value):>15} {format_currency(current.avg_order_value):>15} {format_currency(current.avg_order_value - baseline.avg_order_value):>15}")
    print(f"  {'单访客收入':<20} {baseline.revenue_per_visit:>15.4f} {current.revenue_per_visit:>15.4f} {change.revenue_per_visit_change:>+15.4f}")


def print_gmv_decomposition(result: GmvDecompositionResult):
    """打印 GMV 拆解结果"""
    print(f"\n{'='*60}")
    print(f"{result.dimension_name} GMV 拆解")
    print(f"{'='*60}")

    print(f"\nGMV 变化: {format_currency(result.baseline_total_gmv)} → {format_currency(result.current_total_gmv)}")
    print(f"  GMV 绝对变化: {format_currency(result.gmv_change_absolute)}")
    print(f"  单访客收入变化: {result.baseline_revenue_per_visit:.4f} → {result.current_revenue_per_visit:.4f} ({result.total_effect:+.6f})")
    print(f"  流量结构效应合计: {result.total_share_effect:+.6f} 元/访客")
    print(f"  收入效率效应合计: {result.total_rate_effect:+.6f} 元/访客")
    print(f"  验证: {result.total_share_effect + result.total_rate_effect:.6f} = {result.total_effect:.6f}")

    print(f"\n{'分组':<12} {'基准占比':>8} {'当前占比':>8} {'占比变化':>8} {'基准单访客收入':>14} {'当前单访客收入':>14} {'收入变化':>10} {'结构效应':>10} {'效率效应':>10} {'总效应':>10}")
    print("-" * 115)

    for c in result.get_contributions_sorted_by_total_effect():
        print(f"  {c.group_name:<12} "
              f"{c.baseline_visit_share*100:>7.2f}% "
              f"{c.current_visit_share*100:>7.2f}% "
              f"{c.share_change*100:>+7.2f}% "
              f"{format_currency(c.baseline_revenue_per_visit):>14} "
              f"{format_currency(c.current_revenue_per_visit):>14} "
              f"{c.rate_change:>+10.4f} "
              f"{c.share_effect:>+10.6f} "
              f"{c.rate_effect:>+10.6f} "
              f"{c.total_effect:>+10.6f}")


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    from datetime import datetime, timezone
    from app.analysis_core.cohort import build_cohort

    baseline_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    baseline_end = datetime(2026, 6, 15, tzinfo=timezone.utc)
    current_start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    current_end = datetime(2026, 7, 15, tzinfo=timezone.utc)

    print("=" * 60)
    print("GMV 指标计算测试")
    print("=" * 60)

    baseline_cohort = build_cohort(baseline_start, baseline_end, "baseline")
    current_cohort = build_cohort(current_start, current_end, "current")

    baseline_gmv = calculate_gmv_from_cohort(baseline_cohort)
    current_gmv = calculate_gmv_from_cohort(current_cohort)

    print_gmv_comparison("整体 GMV", baseline_gmv, current_gmv)

    # 渠道拆解
    channel_result = decompose_gmv_channel(baseline_cohort, current_cohort)
    print_gmv_decomposition(channel_result)

    # 设备拆解
    device_result = decompose_gmv_device(baseline_cohort, current_cohort)
    print_gmv_decomposition(device_result)
