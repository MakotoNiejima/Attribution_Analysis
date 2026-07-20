"""
结构效应和表现效应拆解

核心算法：对称分解（Symmetric Decomposition）

优点：
- 各分组效应之和严格等于总效应
- 不存在交叉项归属争议
- 结果与分解顺序无关

公式：
对于维度拆解：
  总效应 = Σ [Δsi × (ri0 + ri1) / 2 + Δri × (si0 + si1) / 2]
  其中 si 是流量占比，ri 是分组转化率

对于漏斗环节拆解：
  Δ(ab) = Δa × (b0 + b1) / 2 + Δb × (a0 + a1) / 2
  其中 a 是加购率，b 是加购后下单率
"""

from dataclasses import dataclass
from typing import Dict, List

from app.analysis_core.cohort import CohortResult
from app.analysis_core.metrics import FunnelMetrics, calculate_funnel
from app.analysis_core.dimensions import DimensionBreakdown, calculate_dimension_breakdown


# ============================================================
# 数据结构
# ============================================================

@dataclass
class GroupContribution:
    """单个分组的贡献度"""
    group_name: str

    # 基准期数据
    baseline_visit: int
    baseline_order: int
    baseline_rate: float
    baseline_share: float  # 流量占比

    # 当前期数据
    current_visit: int
    current_order: int
    current_rate: float
    current_share: float  # 流量占比

    # 贡献度
    share_change: float  # 流量占比变化
    rate_change: float  # 转化率变化
    share_effect: float  # 流量结构效应（对整体转化率的影响）
    rate_effect: float  # 转化率效应（对整体转化率的影响）
    total_effect: float  # 总效应 = share_effect + rate_effect

    def to_dict(self) -> dict:
        return {
            "group_name": self.group_name,
            "baseline_visit": self.baseline_visit,
            "baseline_order": self.baseline_order,
            "baseline_rate": round(self.baseline_rate, 4),
            "baseline_share": round(self.baseline_share, 4),
            "current_visit": self.current_visit,
            "current_order": self.current_order,
            "current_rate": round(self.current_rate, 4),
            "current_share": round(self.current_share, 4),
            "share_change": round(self.share_change, 4),
            "rate_change": round(self.rate_change, 4),
            "share_effect": round(self.share_effect, 6),
            "rate_effect": round(self.rate_effect, 6),
            "total_effect": round(self.total_effect, 6)
        }


@dataclass
class DecompositionResult:
    """拆解结果"""
    dimension_name: str

    # 整体数据
    baseline_total_visit: int
    baseline_total_order: int
    baseline_overall_rate: float

    current_total_visit: int
    current_total_order: int
    current_overall_rate: float

    # 效应汇总
    total_effect: float  # 总效应
    total_share_effect: float  # 流量结构效应合计
    total_rate_effect: float  # 转化率效应合计

    # 各分组贡献
    contributions: List[GroupContribution]

    def get_contributions_sorted_by_total_effect(self) -> List[GroupContribution]:
        """按总效应排序（绝对值大的在前）"""
        return sorted(self.contributions, key=lambda x: abs(x.total_effect), reverse=True)

    def get_contributions_sorted_by_share_effect(self) -> List[GroupContribution]:
        """按流量结构效应排序"""
        return sorted(self.contributions, key=lambda x: abs(x.share_effect), reverse=True)

    def get_contributions_sorted_by_rate_effect(self) -> List[GroupContribution]:
        """按转化率效应排序"""
        return sorted(self.contributions, key=lambda x: abs(x.rate_effect), reverse=True)

    def to_dict(self) -> dict:
        return {
            "dimension_name": self.dimension_name,
            "baseline": {
                "total_visit": self.baseline_total_visit,
                "total_order": self.baseline_total_order,
                "overall_rate": round(self.baseline_overall_rate, 4)
            },
            "current": {
                "total_visit": self.current_total_visit,
                "total_order": self.current_total_order,
                "overall_rate": round(self.current_overall_rate, 4)
            },
            "effects": {
                "total_effect": round(self.total_effect, 6),
                "total_share_effect": round(self.total_share_effect, 6),
                "total_rate_effect": round(self.total_rate_effect, 6)
            },
            "contributions": [c.to_dict() for c in self.contributions]
        }


# ============================================================
# 核心算法：对称分解
# ============================================================

def decompose_dimension(
    baseline_dimension: DimensionBreakdown,
    current_dimension: DimensionBreakdown,
    dimension_name: str
) -> DecompositionResult:
    """
    对单个维度进行对称分解

    使用对称分解公式，确保各分组效应之和严格等于总效应。

    公式：
    对于每个分组 i：
      share_effect_i = Δsi × (ri0 + ri1) / 2
      rate_effect_i = Δri × (si0 + si1) / 2
      total_effect_i = share_effect_i + rate_effect_i

    其中：
      si = 分组 i 的流量占比
      ri = 分组 i 的转化率
      0 = 基准期，1 = 当前期

    Args:
        baseline_dimension: 基准期维度拆解
        current_dimension: 当前期维度拆解
        dimension_name: 维度名称

    Returns:
        DecompositionResult: 拆解结果
    """
    # 计算整体指标
    baseline_total_visit = baseline_dimension.total_visit
    baseline_total_order = baseline_dimension.total_order
    baseline_overall_rate = baseline_total_order / baseline_total_visit if baseline_total_visit > 0 else 0

    current_total_visit = current_dimension.total_visit
    current_total_order = current_dimension.total_order
    current_overall_rate = current_total_order / current_total_visit if current_total_visit > 0 else 0

    # 总效应
    total_effect = current_overall_rate - baseline_overall_rate

    # 获取所有分组
    all_groups = sorted(set(
        list(baseline_dimension.groups.keys()) +
        list(current_dimension.groups.keys())
    ))

    # 计算各分组贡献
    contributions = []
    total_share_effect = 0.0
    total_rate_effect = 0.0

    for group_name in all_groups:
        b_metrics = baseline_dimension.groups.get(group_name)
        c_metrics = current_dimension.groups.get(group_name)

        # 基准期数据
        b_visit = b_metrics.visit_sessions if b_metrics else 0
        b_order = b_metrics.order_sessions if b_metrics else 0
        b_rate = b_metrics.order_rate if b_metrics else 0.0
        b_share = b_visit / baseline_total_visit if baseline_total_visit > 0 else 0.0

        # 当前期数据
        c_visit = c_metrics.visit_sessions if c_metrics else 0
        c_order = c_metrics.order_sessions if c_metrics else 0
        c_rate = c_metrics.order_rate if c_metrics else 0.0
        c_share = c_visit / current_total_visit if current_total_visit > 0 else 0.0

        # 计算变化量
        share_change = c_share - b_share
        rate_change = c_rate - b_rate

        # 对称分解公式
        # 流量结构效应 = Δsi × (ri0 + ri1) / 2
        share_effect = share_change * (b_rate + c_rate) / 2

        # 转化率效应 = Δri × (si0 + si1) / 2
        rate_effect = rate_change * (b_share + c_share) / 2

        # 总效应
        group_total_effect = share_effect + rate_effect

        total_share_effect += share_effect
        total_rate_effect += rate_effect

        contributions.append(GroupContribution(
            group_name=group_name,
            baseline_visit=b_visit,
            baseline_order=b_order,
            baseline_rate=b_rate,
            baseline_share=b_share,
            current_visit=c_visit,
            current_order=c_order,
            current_rate=c_rate,
            current_share=c_share,
            share_change=share_change,
            rate_change=rate_change,
            share_effect=share_effect,
            rate_effect=rate_effect,
            total_effect=group_total_effect
        ))

    return DecompositionResult(
        dimension_name=dimension_name,
        baseline_total_visit=baseline_total_visit,
        baseline_total_order=baseline_total_order,
        baseline_overall_rate=baseline_overall_rate,
        current_total_visit=current_total_visit,
        current_total_order=current_total_order,
        current_overall_rate=current_overall_rate,
        total_effect=total_effect,
        total_share_effect=total_share_effect,
        total_rate_effect=total_rate_effect,
        contributions=contributions
    )


# ============================================================
# 便捷函数
# ============================================================

def decompose_channel(
    baseline_cohort: CohortResult,
    current_cohort: CohortResult
) -> DecompositionResult:
    """按渠道拆解"""
    baseline_dim = calculate_dimension_breakdown(baseline_cohort, "渠道", "channel")
    current_dim = calculate_dimension_breakdown(current_cohort, "渠道", "channel")
    return decompose_dimension(baseline_dim, current_dim, "渠道")


def decompose_device(
    baseline_cohort: CohortResult,
    current_cohort: CohortResult
) -> DecompositionResult:
    """按设备拆解"""
    baseline_dim = calculate_dimension_breakdown(baseline_cohort, "设备", "device_type")
    current_dim = calculate_dimension_breakdown(current_cohort, "设备", "device_type")
    return decompose_dimension(baseline_dim, current_dim, "设备")


def decompose_region(
    baseline_cohort: CohortResult,
    current_cohort: CohortResult
) -> DecompositionResult:
    """按地区拆解"""
    baseline_dim = calculate_dimension_breakdown(baseline_cohort, "地区", "region_code")
    current_dim = calculate_dimension_breakdown(current_cohort, "地区", "region_code")
    return decompose_dimension(baseline_dim, current_dim, "地区")


def decompose_user_type(
    baseline_cohort: CohortResult,
    current_cohort: CohortResult
) -> DecompositionResult:
    """按用户类型拆解"""
    baseline_dim = calculate_dimension_breakdown(baseline_cohort, "用户类型", "user_type_snapshot")
    current_dim = calculate_dimension_breakdown(current_cohort, "用户类型", "user_type_snapshot")
    return decompose_dimension(baseline_dim, current_dim, "用户类型")


# ============================================================
# 漏斗环节拆解（对称分解）
# ============================================================

@dataclass
class StageContribution:
    """漏斗环节贡献"""
    stage_name: str  # cart / order
    baseline_rate: float
    current_rate: float
    rate_change: float
    effect_on_overall: float  # 对整体转化率的影响

    def to_dict(self) -> dict:
        return {
            "stage_name": self.stage_name,
            "baseline_rate": round(self.baseline_rate, 4),
            "current_rate": round(self.current_rate, 4),
            "rate_change": round(self.rate_change, 4),
            "effect_on_overall": round(self.effect_on_overall, 6)
        }


@dataclass
class FunnelStageDecomposition:
    """漏斗环节拆解结果"""
    baseline_overall_rate: float
    current_overall_rate: float
    total_effect: float
    stages: List[StageContribution]

    @property
    def stages_sum(self) -> float:
        """各环节效应之和"""
        return sum(s.effect_on_overall for s in self.stages)

    def to_dict(self) -> dict:
        return {
            "baseline_overall_rate": round(self.baseline_overall_rate, 4),
            "current_overall_rate": round(self.current_overall_rate, 4),
            "total_effect": round(self.total_effect, 6),
            "stages_sum": round(self.stages_sum, 6),
            "stages": [s.to_dict() for s in self.stages]
        }


def decompose_funnel_stages(
    baseline_cohort: CohortResult,
    current_cohort: CohortResult
) -> FunnelStageDecomposition:
    """
    拆解漏斗各环节的贡献（对称分解）

    使用对称分解公式：
    Δ(ab) = Δa × (b0 + b1) / 2 + Δb × (a0 + a1) / 2

    其中：
      a = 加购率 = cart / visit
      b = 加购后下单率 = order / cart
      ab = 下单转化率 = order / visit

    这样两个环节的影响之和严格等于整体转化率变化。
    """
    # 基准期
    b_visit = baseline_cohort.visit_sessions
    b_cart = baseline_cohort.cart_sessions
    b_order = baseline_cohort.order_sessions
    b_a = b_cart / b_visit if b_visit > 0 else 0  # 加购率
    b_b = b_order / b_cart if b_cart > 0 else 0  # 加购后下单率
    b_ab = b_order / b_visit if b_visit > 0 else 0  # 下单转化率

    # 当前期
    c_visit = current_cohort.visit_sessions
    c_cart = current_cohort.cart_sessions
    c_order = current_cohort.order_sessions
    c_a = c_cart / c_visit if c_visit > 0 else 0  # 加购率
    c_b = c_order / c_cart if c_cart > 0 else 0  # 加购后下单率
    c_ab = c_order / c_visit if c_visit > 0 else 0  # 下单转化率

    # 总效应
    total_effect = c_ab - b_ab

    # 对称分解
    delta_a = c_a - b_a  # 加购率变化
    delta_b = c_b - b_b  # 加购后下单率变化

    # 加购率变化的影响 = Δa × (b0 + b1) / 2
    a_effect = delta_a * (b_b + c_b) / 2

    # 加购后下单率变化的影响 = Δb × (a0 + a1) / 2
    b_effect = delta_b * (b_a + c_a) / 2

    stages = [
        StageContribution(
            stage_name="访问→加购",
            baseline_rate=b_a,
            current_rate=c_a,
            rate_change=delta_a,
            effect_on_overall=a_effect
        ),
        StageContribution(
            stage_name="加购→下单",
            baseline_rate=b_b,
            current_rate=c_b,
            rate_change=delta_b,
            effect_on_overall=b_effect
        )
    ]

    return FunnelStageDecomposition(
        baseline_overall_rate=b_ab,
        current_overall_rate=c_ab,
        total_effect=total_effect,
        stages=stages
    )


# ============================================================
# 辅助函数
# ============================================================

def format_percentage(value: float) -> str:
    """格式化百分比"""
    return f"{value * 100:.2f}%"


def print_decomposition_result(result: DecompositionResult):
    """打印拆解结果"""
    print(f"\n{'='*60}")
    print(f"{result.dimension_name}拆解")
    print(f"{'='*60}")

    print(f"\n整体变化: {format_percentage(result.baseline_overall_rate)} → {format_percentage(result.current_overall_rate)} ({result.total_effect*100:+.4f}%)")
    print(f"  流量结构效应合计: {result.total_share_effect*100:+.4f}%")
    print(f"  转化率效应合计: {result.total_rate_effect*100:+.4f}%")
    print(f"  验证: {result.total_share_effect + result.total_rate_effect:.6f} = {result.total_effect:.6f}")

    print(f"\n{'分组':<12} {'基准占比':>8} {'当前占比':>8} {'占比变化':>8} {'基准转化':>8} {'当前转化':>8} {'转化变化':>8} {'结构效应':>10} {'表现效应':>10} {'总效应':>10}")
    print("-" * 105)

    for c in result.get_contributions_sorted_by_total_effect():
        print(f"  {c.group_name:<12} "
              f"{c.baseline_share*100:>7.2f}% "
              f"{c.current_share*100:>7.2f}% "
              f"{c.share_change*100:>+7.2f}% "
              f"{c.baseline_rate*100:>7.2f}% "
              f"{c.current_rate*100:>7.2f}% "
              f"{c.rate_change*100:>+7.2f}% "
              f"{c.share_effect*100:>+9.4f}% "
              f"{c.rate_effect*100:>+9.4f}% "
              f"{c.total_effect*100:>+9.4f}%")

    # 验证汇总
    sum_effect = sum(c.total_effect for c in result.contributions)
    print(f"\n  分组效应之和: {sum_effect*100:+.4f}% (应等于总效应 {result.total_effect*100:+.4f}%)")


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
    print("归因拆解测试（对称分解）")
    print("=" * 60)

    # 构建会话集合
    baseline_cohort = build_cohort(baseline_start, baseline_end, "baseline")
    current_cohort = build_cohort(current_start, current_end, "current")

    # 渠道拆解
    channel_result = decompose_channel(baseline_cohort, current_cohort)
    print_decomposition_result(channel_result)

    # 设备拆解
    device_result = decompose_device(baseline_cohort, current_cohort)
    print_decomposition_result(device_result)

    # 漏斗环节拆解
    print(f"\n{'='*60}")
    print("漏斗环节拆解（对称分解）")
    print(f"{'='*60}")

    stage_result = decompose_funnel_stages(baseline_cohort, current_cohort)
    print(f"\n整体变化: {format_percentage(stage_result.baseline_overall_rate)} → {format_percentage(stage_result.current_overall_rate)} ({stage_result.total_effect*100:+.4f}%)")
    print(f"  环节效应之和: {stage_result.stages_sum*100:+.4f}%")

    for stage in stage_result.stages:
        print(f"\n  {stage.stage_name}:")
        print(f"    基准期: {format_percentage(stage.baseline_rate)}")
        print(f"    当前期: {format_percentage(stage.current_rate)}")
        print(f"    变化: {stage.rate_change*100:+.2f}%")
        print(f"    对整体影响: {stage.effect_on_overall*100:+.4f}%")
