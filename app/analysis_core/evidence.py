"""
生成证据对象

职责：
- 把计算结果保存成可引用的证据结构
- 证据包含：来源、数值、时间范围、置信度
- 不直接生成自然语言，只保存结构化数据
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any

from app.analysis_core.cohort import CohortResult
from app.analysis_core.metrics import FunnelMetrics
from app.analysis_core.decomposition import DecompositionResult, FunnelStageDecomposition


# ============================================================
# 证据数据结构
# ============================================================

@dataclass
class MetricEvidence:
    """指标证据"""
    metric_name: str  # 指标名称
    metric_value: float  # 指标值
    metric_unit: str  # 单位（%，个）
    metric_period: str  # 时间范围
    numerator: int  # 分子
    denominator: int  # 分母

    def to_dict(self) -> dict:
        return {
            "metric_name": self.metric_name,
            "metric_value": round(self.metric_value, 6),
            "metric_unit": self.metric_unit,
            "metric_period": self.metric_period,
            "numerator": self.numerator,
            "denominator": self.denominator
        }


@dataclass
class DimensionEvidence:
    """维度证据"""
    dimension_name: str  # 维度名称
    group_name: str  # 分组名称
    metric_name: str  # 指标名称
    baseline_value: float  # 基准期值
    current_value: float  # 当前期值
    change_value: float  # 变化量
    effect_value: float  # 对整体的影响

    def to_dict(self) -> dict:
        return {
            "dimension_name": self.dimension_name,
            "group_name": self.group_name,
            "metric_name": self.metric_name,
            "baseline_value": round(self.baseline_value, 6),
            "current_value": round(self.current_value, 6),
            "change_value": round(self.change_value, 6),
            "effect_value": round(self.effect_value, 6)
        }


@dataclass
class BusinessEventEvidence:
    """业务事件证据"""
    event_code: str
    event_type: str
    title: str
    description: str
    started_at: datetime
    ended_at: Optional[datetime]
    severity: str
    scope: Dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "event_code": self.event_code,
            "event_type": self.event_type,
            "title": self.title,
            "description": self.description,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "severity": self.severity,
            "scope": self.scope
        }


@dataclass
class EvidenceCollection:
    """证据集合"""
    problem_definition: str  # 问题定义
    time_range: Dict[str, str]  # 时间范围
    metrics: List[MetricEvidence] = field(default_factory=list)
    dimension_evidences: List[DimensionEvidence] = field(default_factory=list)
    business_events: List[BusinessEventEvidence] = field(default_factory=list)
    missing_data: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "problem_definition": self.problem_definition,
            "time_range": self.time_range,
            "metrics": [m.to_dict() for m in self.metrics],
            "dimension_evidences": [d.to_dict() for d in self.dimension_evidences],
            "business_events": [e.to_dict() for e in self.business_events],
            "missing_data": self.missing_data
        }


# ============================================================
# 证据生成函数
# ============================================================

def build_funnel_evidence(
    baseline: CohortResult,
    current: CohortResult
) -> List[MetricEvidence]:
    """构建漏斗指标证据"""

    b_visit = baseline.visit_sessions
    b_cart = baseline.cart_sessions
    b_order = baseline.order_sessions

    c_visit = current.visit_sessions
    c_cart = current.cart_sessions
    c_order = current.order_sessions

    b_period = f"{baseline.start.strftime('%Y-%m-%d')} ~ {baseline.end.strftime('%Y-%m-%d')}"
    c_period = f"{current.start.strftime('%Y-%m-%d')} ~ {current.end.strftime('%Y-%m-%d')}"

    evidence = [
        MetricEvidence(
            metric_name="基准期访问会话数",
            metric_value=b_visit,
            metric_unit="个",
            metric_period=b_period,
            numerator=b_visit,
            denominator=b_visit
        ),
        MetricEvidence(
            metric_name="基准期加购会话数",
            metric_value=b_cart,
            metric_unit="个",
            metric_period=b_period,
            numerator=b_cart,
            denominator=b_visit
        ),
        MetricEvidence(
            metric_name="基准期下单会话数",
            metric_value=b_order,
            metric_unit="个",
            metric_period=b_period,
            numerator=b_order,
            denominator=b_visit
        ),
        MetricEvidence(
            metric_name="基准期下单转化率",
            metric_value=b_order / b_visit if b_visit > 0 else 0,
            metric_unit="%",
            metric_period=b_period,
            numerator=b_order,
            denominator=b_visit
        ),
        MetricEvidence(
            metric_name="当前期访问会话数",
            metric_value=c_visit,
            metric_unit="个",
            metric_period=c_period,
            numerator=c_visit,
            denominator=c_visit
        ),
        MetricEvidence(
            metric_name="当前期加购会话数",
            metric_value=c_cart,
            metric_unit="个",
            metric_period=c_period,
            numerator=c_cart,
            denominator=c_visit
        ),
        MetricEvidence(
            metric_name="当前期下单会话数",
            metric_value=c_order,
            metric_unit="个",
            metric_period=c_period,
            numerator=c_order,
            denominator=c_visit
        ),
        MetricEvidence(
            metric_name="当前期下单转化率",
            metric_value=c_order / c_visit if c_visit > 0 else 0,
            metric_unit="%",
            metric_period=c_period,
            numerator=c_order,
            denominator=c_visit
        ),
    ]

    return evidence


def build_dimension_evidence(
    decomposition: DecompositionResult
) -> List[DimensionEvidence]:
    """构建维度证据"""

    evidence = []

    for contrib in decomposition.contributions:
        # 流量结构效应证据
        evidence.append(DimensionEvidence(
            dimension_name=decomposition.dimension_name,
            group_name=contrib.group_name,
            metric_name="流量结构效应",
            baseline_value=contrib.baseline_share,
            current_value=contrib.current_share,
            change_value=contrib.share_change,
            effect_value=contrib.share_effect
        ))

        # 转化率效应证据
        evidence.append(DimensionEvidence(
            dimension_name=decomposition.dimension_name,
            group_name=contrib.group_name,
            metric_name="转化率效应",
            baseline_value=contrib.baseline_rate,
            current_value=contrib.current_rate,
            change_value=contrib.rate_change,
            effect_value=contrib.rate_effect
        ))

        # 总效应证据
        evidence.append(DimensionEvidence(
            dimension_name=decomposition.dimension_name,
            group_name=contrib.group_name,
            metric_name="总效应",
            baseline_value=contrib.baseline_rate,
            current_value=contrib.current_rate,
            change_value=contrib.rate_change,
            effect_value=contrib.total_effect
        ))

    return evidence


def build_stage_evidence(
    stage_decomposition: FunnelStageDecomposition
) -> List[MetricEvidence]:
    """构建漏斗环节证据"""

    evidence = []

    for stage in stage_decomposition.stages:
        evidence.append(MetricEvidence(
            metric_name=f"{stage.stage_name}基准期转化率",
            metric_value=stage.baseline_rate,
            metric_unit="%",
            metric_period="基准期",
            numerator=0,
            denominator=0
        ))
        evidence.append(MetricEvidence(
            metric_name=f"{stage.stage_name}当前期转化率",
            metric_value=stage.current_rate,
            metric_unit="%",
            metric_period="当前期",
            numerator=0,
            denominator=0
        ))
        evidence.append(MetricEvidence(
            metric_name=f"{stage.stage_name}对整体转化率的影响",
            metric_value=stage.effect_on_overall,
            metric_unit="%",
            metric_period="变化",
            numerator=0,
            denominator=0
        ))

    return evidence


def build_business_event_evidence(
    events: List[Dict]
) -> List[BusinessEventEvidence]:
    """构建业务事件证据"""

    evidence = []

    for event in events:
        evidence.append(BusinessEventEvidence(
            event_code=event.get("event_code", ""),
            event_type=event.get("event_type", ""),
            title=event.get("title", ""),
            description=event.get("description", ""),
            started_at=event.get("started_at"),
            ended_at=event.get("ended_at"),
            severity=event.get("severity", "medium"),
            scope=event.get("scope_json", {})
        ))

    return evidence


# ============================================================
# 完整证据构建
# ============================================================

def build_evidence_collection(
    baseline: CohortResult,
    current: CohortResult,
    channel_decomposition: DecompositionResult,
    device_decomposition: DecompositionResult,
    stage_decomposition: FunnelStageDecomposition,
    business_events: List[Dict] = None,
    missing_data: List[str] = None
) -> EvidenceCollection:
    """
    构建完整的证据集合

    Args:
        baseline: 基准期会话集合
        current: 当前期会话集合
        channel_decomposition: 渠道拆解结果
        device_decomposition: 设备拆解结果
        stage_decomposition: 漏斗环节拆解结果
        business_events: 业务事件列表
        missing_data: 缺失数据列表

    Returns:
        EvidenceCollection: 证据集合
    """

    problem_definition = "有效下单转化率的周期对比与归因分析"

    time_range = {
        "baseline_start": baseline.start.strftime("%Y-%m-%d"),
        "baseline_end": baseline.end.strftime("%Y-%m-%d"),
        "current_start": current.start.strftime("%Y-%m-%d"),
        "current_end": current.end.strftime("%Y-%m-%d")
    }

    # 漏斗指标证据
    metrics = build_funnel_evidence(baseline, current)

    # 环节证据
    metrics.extend(build_stage_evidence(stage_decomposition))

    # 维度证据
    dimension_evidences = []
    dimension_evidences.extend(build_dimension_evidence(channel_decomposition))
    dimension_evidences.extend(build_dimension_evidence(device_decomposition))

    # 业务事件证据
    biz_events = []
    if business_events:
        biz_events = build_business_event_evidence(business_events)

    # 缺失数据
    missing = missing_data or []

    return EvidenceCollection(
        problem_definition=problem_definition,
        time_range=time_range,
        metrics=metrics,
        dimension_evidences=dimension_evidences,
        business_events=biz_events,
        missing_data=missing
    )


# ============================================================
# 辅助函数
# ============================================================

def save_evidence_to_json(evidence: EvidenceCollection, filepath: str):
    """保存证据到 JSON 文件"""
    import json

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(evidence.to_dict(), f, indent=2, ensure_ascii=False, default=str)


def format_evidence_summary(evidence: EvidenceCollection) -> str:
    """格式化证据摘要"""

    lines = []
    lines.append("=" * 60)
    lines.append("证据摘要")
    lines.append("=" * 60)
    lines.append(f"\n问题: {evidence.problem_definition}")
    lines.append(f"基准期: {evidence.time_range['baseline_start']} ~ {evidence.time_range['baseline_end']}")
    lines.append(f"当前期: {evidence.time_range['current_start']} ~ {evidence.time_range['current_end']}")

    lines.append("\n关键指标:")
    for m in evidence.metrics:
        if "转化率" in m.metric_name and "影响" not in m.metric_name:
            lines.append(f"  {m.metric_name}: {m.metric_value*100:.2f}{m.metric_unit}")

    lines.append("\n主要影响因素（按总效应排序）:")
    # 按总效应分组
    channel_effects = {}
    device_effects = {}
    for d in evidence.dimension_evidences:
        if d.metric_name == "总效应":
            if d.dimension_name == "渠道":
                channel_effects[d.group_name] = d.effect_value
            elif d.dimension_name == "设备":
                device_effects[d.group_name] = d.effect_value

    lines.append("\n  渠道维度:")
    for name, effect in sorted(channel_effects.items(), key=lambda x: abs(x[1]), reverse=True):
        lines.append(f"    {name}: {effect*100:+.4f}%")

    lines.append("\n  设备维度:")
    for name, effect in sorted(device_effects.items(), key=lambda x: abs(x[1]), reverse=True):
        lines.append(f"    {name}: {effect*100:+.4f}%")

    if evidence.business_events:
        lines.append("\n关联业务事件:")
        for event in evidence.business_events:
            lines.append(f"  - {event.title}")

    if evidence.missing_data:
        lines.append("\n待补充数据:")
        for item in evidence.missing_data:
            lines.append(f"  - {item}")

    return "\n".join(lines)


# ============================================================
# 测试代码
# ============================================================

if __name__ == "__main__":
    from datetime import datetime, timezone
    from analysis_core.cohort import build_cohort
    from analysis_core.decomposition import decompose_channel, decompose_device, decompose_funnel_stages

    baseline_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    baseline_end = datetime(2026, 6, 15, tzinfo=timezone.utc)
    current_start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    current_end = datetime(2026, 7, 15, tzinfo=timezone.utc)

    print("=" * 60)
    print("证据生成测试")
    print("=" * 60)

    # 构建会话集合
    baseline = build_cohort(baseline_start, baseline_end, "baseline")
    current = build_cohort(current_start, current_end, "current")

    # 拆解
    channel_decomposition = decompose_channel(baseline, current)
    device_decomposition = decompose_device(baseline, current)
    stage_decomposition = decompose_funnel_stages(baseline, current)

    # 构建证据
    evidence = build_evidence_collection(
        baseline=baseline,
        current=current,
        channel_decomposition=channel_decomposition,
        device_decomposition=device_decomposition,
        stage_decomposition=stage_decomposition,
        business_events=[
            {
                "event_code": "evt_douyin_campaign",
                "event_type": "campaign",
                "title": "抖音渠道大规模投放活动",
                "description": "7月1日-15日期间在抖音渠道进行大规模流量投放",
                "started_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
                "ended_at": datetime(2026, 7, 15, tzinfo=timezone.utc),
                "severity": "medium",
                "scope_json": {"channel": ["douyin"]}
            }
        ],
        missing_data=[
            "抖音渠道具体投放策略和人群定位",
            "移动端结算页性能监控详细数据"
        ]
    )

    # 打印摘要
    print(format_evidence_summary(evidence))

    # 保存到文件
    save_evidence_to_json(evidence, "evidence_output.json")
    print("\n证据已保存到 evidence_output.json")
