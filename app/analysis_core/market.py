"""
市场表现分析模块

职责：
- 计算各渠道 ROI、CPC、CPA、CTR 等效率指标
- 对比基准期与当前期的渠道效率变化
- 识别 ROI 下降最大的渠道
- 提供渠道投放效果归因

核心指标：
- ROI = revenue / ad_spend（投资回报率）
- CPC = ad_spend / clicks（单次点击成本）
- CPA = ad_spend / conversions（单次转化成本）
- CTR = clicks / impressions（点击率）
- CVR = conversions / clicks（转化率）
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Dict, Optional, Any

from sqlalchemy import text
from app.config import get_engine


# ============================================================
# 数据结构
# ============================================================

@dataclass
class ChannelEfficiencyMetrics:
    """渠道效率指标"""
    channel: str
    impressions: int
    clicks: int
    conversions: int
    revenue: float
    ad_spend: float

    @property
    def roi(self) -> float:
        """投资回报率 = revenue / ad_spend"""
        return self.revenue / self.ad_spend if self.ad_spend > 0 else 0.0

    @property
    def cpc(self) -> float:
        """单次点击成本 = ad_spend / clicks"""
        return self.ad_spend / self.clicks if self.clicks > 0 else 0.0

    @property
    def cpa(self) -> float:
        """单次转化成本 = ad_spend / conversions"""
        return self.ad_spend / self.conversions if self.conversions > 0 else 0.0

    @property
    def ctr(self) -> float:
        """点击率 = clicks / impressions"""
        return self.clicks / self.impressions if self.impressions > 0 else 0.0

    @property
    def cvr(self) -> float:
        """转化率 = conversions / clicks"""
        return self.conversions / self.clicks if self.clicks > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "channel": self.channel,
            "impressions": self.impressions,
            "clicks": self.clicks,
            "conversions": self.conversions,
            "revenue": round(self.revenue, 2),
            "ad_spend": round(self.ad_spend, 2),
            "roi": round(self.roi, 4),
            "cpc": round(self.cpc, 4),
            "cpa": round(self.cpa, 4),
            "ctr": round(self.ctr, 6),
            "cvr": round(self.cvr, 6),
        }


@dataclass
class ChannelEfficiencyChange:
    """渠道效率变化"""
    channel: str
    baseline: ChannelEfficiencyMetrics
    current: ChannelEfficiencyMetrics

    @property
    def roi_change(self) -> float:
        """ROI 变化"""
        return self.current.roi - self.baseline.roi

    @property
    def roi_change_rate(self) -> float:
        """ROI 变化率"""
        return self.roi_change / self.baseline.roi if self.baseline.roi > 0 else 0.0

    @property
    def cpc_change(self) -> float:
        """CPC 变化"""
        return self.current.cpc - self.baseline.cpc

    @property
    def cpa_change(self) -> float:
        """CPA 变化"""
        return self.current.cpa - self.baseline.cpa

    @property
    def revenue_change(self) -> float:
        """收入变化"""
        return self.current.revenue - self.baseline.revenue

    @property
    def ad_spend_change(self) -> float:
        """广告花费变化"""
        return self.current.ad_spend - self.baseline.ad_spend

    def to_dict(self) -> dict:
        return {
            "channel": self.channel,
            "baseline": self.baseline.to_dict(),
            "current": self.current.to_dict(),
            "roi_change": round(self.roi_change, 4),
            "roi_change_rate": round(self.roi_change_rate, 4),
            "cpc_change": round(self.cpc_change, 4),
            "cpa_change": round(self.cpa_change, 4),
            "revenue_change": round(self.revenue_change, 2),
            "ad_spend_change": round(self.ad_spend_change, 2),
        }


@dataclass
class MarketAnalysisResult:
    """市场表现分析结果"""
    baseline_start: date
    baseline_end: date
    current_start: date
    current_end: date

    # 整体数据
    baseline_total_revenue: float
    baseline_total_ad_spend: float
    current_total_revenue: float
    current_total_ad_spend: float

    # 各渠道效率
    baseline_channel_metrics: Dict[str, ChannelEfficiencyMetrics]
    current_channel_metrics: Dict[str, ChannelEfficiencyMetrics]

    # 渠道效率变化
    channel_changes: List[ChannelEfficiencyChange]

    # 异常渠道（ROI 下降最大的）
    abnormal_channels: List[Dict[str, Any]]

    def to_dict(self) -> dict:
        return {
            "baseline_period": {
                "start": self.baseline_start.isoformat(),
                "end": self.baseline_end.isoformat(),
            },
            "current_period": {
                "start": self.current_start.isoformat(),
                "end": self.current_end.isoformat(),
            },
            "baseline_summary": {
                "total_revenue": round(self.baseline_total_revenue, 2),
                "total_ad_spend": round(self.baseline_total_ad_spend, 2),
                "overall_roi": round(self.baseline_total_revenue / self.baseline_total_ad_spend, 4)
                    if self.baseline_total_ad_spend > 0 else 0.0,
            },
            "current_summary": {
                "total_revenue": round(self.current_total_revenue, 2),
                "total_ad_spend": round(self.current_total_ad_spend, 2),
                "overall_roi": round(self.current_total_revenue / self.current_total_ad_spend, 4)
                    if self.current_total_ad_spend > 0 else 0.0,
            },
            "channel_changes": [c.to_dict() for c in self.channel_changes],
            "abnormal_channels": self.abnormal_channels,
        }


# ============================================================
# 数据查询
# ============================================================

def query_campaign_metrics_by_period(
    start_date: date,
    end_date: date,
    engine=None
) -> Dict[str, ChannelEfficiencyMetrics]:
    """
    查询指定时间段内各渠道的营销指标

    Args:
        start_date: 开始日期
        end_date: 结束日期
        engine: 数据库引擎

    Returns:
        Dict[str, ChannelEfficiencyMetrics]: 各渠道效率指标
    """
    close_engine = False
    if engine is None:
        engine = get_engine()
        close_engine = True

    try:
        sql = text("""
            SELECT
                c.channel,
                SUM(m.impressions) as impressions,
                SUM(m.clicks) as clicks,
                SUM(m.conversions) as conversions,
                SUM(m.revenue) as revenue,
                SUM(m.ad_spend) as ad_spend
            FROM campaigns c
            JOIN campaign_daily_metrics m ON c.id = m.campaign_id
            WHERE m.metric_date >= :start_date
              AND m.metric_date <= :end_date
            GROUP BY c.channel
        """)

        with engine.connect() as conn:
            result = conn.execute(sql, {
                "start_date": start_date,
                "end_date": end_date,
            })
            rows = result.fetchall()

        metrics = {}
        for row in rows:
            channel = row[0]
            metrics[channel] = ChannelEfficiencyMetrics(
                channel=channel,
                impressions=int(row[1] or 0),
                clicks=int(row[2] or 0),
                conversions=int(row[3] or 0),
                revenue=float(row[4] or 0),
                ad_spend=float(row[5] or 0),
            )

        return metrics

    finally:
        if close_engine:
            engine.dispose()


# ============================================================
# 分析函数
# ============================================================

def analyze_market_performance(
    baseline_start: date,
    baseline_end: date,
    current_start: date,
    current_end: date,
    engine=None
) -> MarketAnalysisResult:
    """
    分析市场表现（渠道效率对比）

    Args:
        baseline_start: 基准期开始日期
        baseline_end: 基准期结束日期
        current_start: 当前期开始日期
        current_end: 当前期结束日期
        engine: 数据库引擎

    Returns:
        MarketAnalysisResult: 市场表现分析结果
    """
    close_engine = False
    if engine is None:
        engine = get_engine()
        close_engine = True

    try:
        # 1. 查询基准期和当前期各渠道指标
        baseline_metrics = query_campaign_metrics_by_period(
            baseline_start, baseline_end, engine
        )
        current_metrics = query_campaign_metrics_by_period(
            current_start, current_end, engine
        )

        # 2. 计算整体数据
        baseline_total_revenue = sum(m.revenue for m in baseline_metrics.values())
        baseline_total_ad_spend = sum(m.ad_spend for m in baseline_metrics.values())
        current_total_revenue = sum(m.revenue for m in current_metrics.values())
        current_total_ad_spend = sum(m.ad_spend for m in current_metrics.values())

        # 3. 计算各渠道效率变化
        all_channels = sorted(set(
            list(baseline_metrics.keys()) + list(current_metrics.keys())
        ))

        channel_changes = []
        for channel in all_channels:
            b_metrics = baseline_metrics.get(channel)
            c_metrics = current_metrics.get(channel)

            if b_metrics and c_metrics:
                change = ChannelEfficiencyChange(
                    channel=channel,
                    baseline=b_metrics,
                    current=c_metrics,
                )
                channel_changes.append(change)

        # 4. 识别异常渠道（ROI 下降最大的）
        # 按 ROI 变化率排序，找出下降最大的渠道
        abnormal_channels = []
        for change in channel_changes:
            if change.roi_change_rate < -0.1:  # ROI 下降超过 10%
                abnormal_channels.append({
                    "channel": change.channel,
                    "roi_change_rate": round(change.roi_change_rate, 4),
                    "roi_change": round(change.roi_change, 4),
                    "baseline_roi": round(change.baseline.roi, 4),
                    "current_roi": round(change.current.roi, 4),
                    "ad_spend_change": round(change.ad_spend_change, 2),
                    "revenue_change": round(change.revenue_change, 2),
                })

        # 按 ROI 变化率排序（下降最多的在前）
        abnormal_channels.sort(key=lambda x: x["roi_change_rate"])

        return MarketAnalysisResult(
            baseline_start=baseline_start,
            baseline_end=baseline_end,
            current_start=current_start,
            current_end=current_end,
            baseline_total_revenue=baseline_total_revenue,
            baseline_total_ad_spend=baseline_total_ad_spend,
            current_total_revenue=current_total_revenue,
            current_total_ad_spend=current_total_ad_spend,
            baseline_channel_metrics=baseline_metrics,
            current_channel_metrics=current_metrics,
            channel_changes=channel_changes,
            abnormal_channels=abnormal_channels,
        )

    finally:
        if close_engine:
            engine.dispose()


# ============================================================
# 辅助函数
# ============================================================

def print_market_analysis(result: MarketAnalysisResult):
    """打印市场表现分析结果"""
    print("\n" + "=" * 80)
    print("市场表现分析")
    print("=" * 80)

    print(f"\n基准期: {result.baseline_start} ~ {result.baseline_end}")
    print(f"当前期: {result.current_start} ~ {result.current_end}")

    print("\n整体数据:")
    baseline_roi = result.baseline_total_revenue / result.baseline_total_ad_spend if result.baseline_total_ad_spend > 0 else 0
    current_roi = result.current_total_revenue / result.current_total_ad_spend if result.current_total_ad_spend > 0 else 0
    print(f"  基准期: 收入 ¥{result.baseline_total_revenue:,.2f}, 花费 ¥{result.baseline_total_ad_spend:,.2f}, ROI {baseline_roi:.2f}")
    print(f"  当前期: 收入 ¥{result.current_total_revenue:,.2f}, 花费 ¥{result.current_total_ad_spend:,.2f}, ROI {current_roi:.2f}")
    print(f"  变化: 收入 ¥{result.current_total_revenue - result.baseline_total_revenue:+,.2f}, "
          f"花费 ¥{result.current_total_ad_spend - result.baseline_total_ad_spend:+,.2f}, "
          f"ROI {current_roi - baseline_roi:+.2f}")

    print("\n各渠道效率对比:")
    print(f"  {'渠道':<12} {'基准ROI':>10} {'当前ROI':>10} {'ROI变化':>10} {'变化率':>10} {'基准花费':>12} {'当前花费':>12}")
    print("  " + "-" * 90)

    for change in sorted(result.channel_changes, key=lambda x: x.roi_change_rate):
        print(f"  {change.channel:<12} "
              f"{change.baseline.roi:>10.2f} "
              f"{change.current.roi:>10.2f} "
              f"{change.roi_change:>+10.2f} "
              f"{change.roi_change_rate:>+10.2%} "
              f"¥{change.baseline.ad_spend:>10,.2f} "
              f"¥{change.current.ad_spend:>10,.2f}")

    if result.abnormal_channels:
        print("\n异常渠道（ROI 下降超过 10%）:")
        for ch in result.abnormal_channels:
            print(f"  - {ch['channel']}: ROI 下降 {ch['roi_change_rate']:.2%}")
            print(f"    基准 ROI: {ch['baseline_roi']:.2f} → 当前 ROI: {ch['current_roi']:.2f}")
            print(f"    广告花费变化: ¥{ch['ad_spend_change']:+,.2f}")
            print(f"    收入变化: ¥{ch['revenue_change']:+,.2f}")


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    from datetime import date

    baseline_start = date(2026, 6, 1)
    baseline_end = date(2026, 6, 15)
    current_start = date(2026, 7, 1)
    current_end = date(2026, 7, 15)

    result = analyze_market_performance(
        baseline_start, baseline_end,
        current_start, current_end
    )

    print_market_analysis(result)

    # 保存结果
    import json
    with open("market_analysis_result.json", "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
    print("\n结果已保存到 market_analysis_result.json")
