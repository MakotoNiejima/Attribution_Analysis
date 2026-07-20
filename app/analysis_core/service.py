"""
归因分析服务

提供唯一入口：
    run_conversion_analysis(request) -> AnalysisResult

内部依次完成：
1. 构造基准期/当前期 cohort
2. 算整体漏斗
3. 算渠道、设备、地区、用户类型拆解
4. 算漏斗阶段拆解
5. 匹配 business_events
6. 生成 evidence_collection
7. 返回结构化 JSON
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, List, Optional, Dict, Any

from sqlalchemy import text

from app.analysis_core.cohort import build_cohort, CohortResult
from app.analysis_core.metrics import (
    calculate_funnel_from_cohort, FunnelMetrics, FunnelChange,
    calculate_funnel_by_channel, calculate_funnel_by_device,
    calculate_funnel_by_region, calculate_funnel_by_user_type
)
from app.analysis_core.decomposition import (
    decompose_channel, decompose_device, decompose_region, decompose_user_type,
    decompose_funnel_stages, DecompositionResult, FunnelStageDecomposition
)
from app.analysis_core.evidence import (
    build_evidence_collection, EvidenceCollection,
    save_evidence_to_json, format_evidence_summary
)
from app.analysis_core.dimensions import compare_all_dimensions, DimensionComparison


# ============================================================
# 请求和响应数据结构
# ============================================================

@dataclass
class AnalysisRequest:
    """分析请求"""
    problem: str  # 问题描述
    baseline_start: datetime
    baseline_end: datetime
    current_start: datetime
    current_end: datetime
    store_id: Optional[str] = None
    channel: Optional[str] = None
    device_type: Optional[str] = None
    region_code: Optional[str] = None
    user_type: Optional[str] = None


@dataclass
class AnalysisResult:
    """分析结果"""
    problem: str
    time_range: Dict[str, str]

    # 整体漏斗
    baseline_funnel: Dict[str, Any]
    current_funnel: Dict[str, Any]
    funnel_change: Dict[str, Any]

    # 漏斗阶段拆解
    stage_decomposition: Dict[str, Any]

    # 维度拆解
    channel_decomposition: Dict[str, Any]
    device_decomposition: Dict[str, Any]
    region_decomposition: Optional[Dict[str, Any]] = None
    user_type_decomposition: Optional[Dict[str, Any]] = None

    # 证据
    evidence: Optional[Dict[str, Any]] = None

    # 业务事件
    business_events: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "problem": self.problem,
            "time_range": self.time_range,
            "baseline_funnel": self.baseline_funnel,
            "current_funnel": self.current_funnel,
            "funnel_change": self.funnel_change,
            "stage_decomposition": self.stage_decomposition,
            "channel_decomposition": self.channel_decomposition,
            "device_decomposition": self.device_decomposition,
            "region_decomposition": self.region_decomposition,
            "user_type_decomposition": self.user_type_decomposition,
            "business_events": self.business_events,
            "evidence": self.evidence
        }

    def to_json(self, indent=2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, default=str)


# ============================================================
# 业务事件查询与匹配
# ============================================================

def find_all_business_events(
    start: datetime,
    end: datetime,
    store_id: Optional[str] = None,
    engine=None
) -> List[Dict]:
    """
    查找时间范围内的所有业务事件

    Args:
        start: 开始时间
        end: 结束时间
        store_id: 店铺筛选。未传入时查询所有店铺。
        engine: 数据库引擎

    Returns:
        业务事件列表
    """
    from app.config import get_engine

    close_engine = False
    if engine is None:
        engine = get_engine()
        close_engine = True

    try:
        conditions = [
            "started_at < :end",
            "(ended_at IS NULL OR ended_at >= :start)"
        ]
        params = {"start": start, "end": end}

        if store_id:
            conditions.append("store_id = :store_id")
            params["store_id"] = store_id

        sql = text(f"""
            SELECT
                event_code,
                event_type,
                title,
                description,
                started_at,
                ended_at,
                severity,
                scope_json
            FROM business_events
            WHERE {' AND '.join(conditions)}
            ORDER BY started_at
        """)

        with engine.connect() as conn:
            result = conn.execute(sql, params)
            rows = result.fetchall()

        events = []
        for row in rows:
            scope = row[7]
            if isinstance(scope, str):
                try:
                    scope = json.loads(scope)
                except:
                    scope = {}

            events.append({
                "event_code": row[0],
                "event_type": row[1],
                "title": row[2],
                "description": row[3],
                "started_at": row[4],
                "ended_at": row[5],
                "severity": row[6],
                "scope_json": scope
            })

        return events

    finally:
        if close_engine:
            engine.dispose()


def match_event_to_groups(
    event: Dict,
    channel_groups: List[str] = None,
    device_groups: List[str] = None,
    region_groups: List[str] = None,
    user_type_groups: List[str] = None,
    product_groups: List[str] = None
) -> bool:
    """
    判断业务事件是否与当前异常分组相关

    匹配规则：
    - 如果事件 scope 为空，认为是全局事件，匹配所有分组
    - 如果事件 scope 包含 channel，检查是否与异常渠道匹配
    - 如果事件 scope 包含 device_type，检查是否与异常设备匹配
    - 如果事件 scope 包含 region_code，检查是否与异常地区匹配
    - 如果事件 scope 包含 user_type，检查是否与异常用户类型匹配
    - 如果事件 scope 包含 product_id，必须存在对应的商品归因结果才可匹配
    - 仅有尚未分析维度的 scope 不得作为相关证据

    Args:
        event: 业务事件
        channel_groups: 异常渠道列表
        device_groups: 异常设备列表
        region_groups: 异常地区列表
        user_type_groups: 异常用户类型列表
        product_groups: 异常商品列表

    Returns:
        True 如果事件与异常分组相关
    """
    scope = event.get("scope_json", {})

    # 如果 scope 为空，认为是全局事件
    if not scope:
        return True

    def as_value_set(value: Any) -> set[str]:
        """scope 既兼容 JSON 数组，也兼容单个字符串。"""
        if isinstance(value, (list, tuple, set)):
            return {str(item) for item in value}
        return {str(value)}

    abnormal_groups = {
        "channel": set(channel_groups or []),
        "device_type": set(device_groups or []),
        "region_code": set(region_groups or []),
        "user_type": set(user_type_groups or []),
        "product_id": set(product_groups or []),
    }

    # 只有至少一个已分析维度与事件 scope 相交，事件才能成为相关证据。
    # 比如尚未做商品归因时，prod_001 的库存事件不能自动解释整体转化率下降。
    for field_name, groups in abnormal_groups.items():
        if field_name in scope and groups:
            if as_value_set(scope[field_name]).intersection(groups):
                return True

    return False


def find_related_business_events(
    start: datetime,
    end: datetime,
    store_id: Optional[str] = None,
    channel_decomposition: DecompositionResult = None,
    device_decomposition: DecompositionResult = None,
    region_decomposition: DecompositionResult = None,
    user_type_decomposition: DecompositionResult = None,
    effect_threshold: float = -0.001,
    engine=None
) -> List[Dict]:
    """
    查找与异常分组相关的业务事件

    逻辑：
    1. 从各维度拆解结果中找出效应值低于阈值的分组（异常分组）
    2. 查询时间范围内的所有业务事件
    3. 根据事件的 scope_json 判断是否与异常分组相关

    Args:
        start: 开始时间
        end: 结束时间
        channel_decomposition: 渠道拆解结果
        device_decomposition: 设备拆解结果
        region_decomposition: 地区拆解结果
        user_type_decomposition: 用户类型拆解结果
        effect_threshold: 效应阈值（低于此值认为是异常）
        engine: 数据库引擎

    Returns:
        匹配的业务事件列表
    """
    # 1. 找出异常分组
    channel_groups = []
    if channel_decomposition:
        channel_groups = [
            c.group_name for c in channel_decomposition.contributions
            if c.total_effect < effect_threshold
        ]

    device_groups = []
    if device_decomposition:
        device_groups = [
            c.group_name for c in device_decomposition.contributions
            if c.total_effect < effect_threshold
        ]

    region_groups = []
    if region_decomposition:
        region_groups = [
            c.group_name for c in region_decomposition.contributions
            if c.total_effect < effect_threshold
        ]

    user_type_groups = []
    if user_type_decomposition:
        user_type_groups = [
            c.group_name for c in user_type_decomposition.contributions
            if c.total_effect < effect_threshold
        ]

    # 2. 查询所有事件
    all_events = find_all_business_events(
        start=start,
        end=end,
        store_id=store_id,
        engine=engine
    )

    # 3. 匹配事件
    matched_events = []
    for event in all_events:
        if match_event_to_groups(
            event,
            channel_groups=channel_groups,
            device_groups=device_groups,
            region_groups=region_groups,
            user_type_groups=user_type_groups
        ):
            event["matched_groups"] = {
                "channels": channel_groups,
                "devices": device_groups,
                "regions": region_groups,
                "user_types": user_type_groups
            }
            matched_events.append(event)

    return matched_events


# ============================================================
# 主入口函数
# ============================================================

def run_conversion_analysis(
    request: AnalysisRequest,
    progress_callback: Optional[Callable[[str, str], None]] = None,
) -> AnalysisResult:
    """
    运行转化率分析

    Args:
        request: 分析请求

    Returns:
        AnalysisResult: 分析结果
    """
    def report_progress(step: str, message: str) -> None:
        if progress_callback:
            progress_callback(step, message)

    print(f"[分析开始] {request.problem}")

    # 1. 构造基准期/当前期 cohort
    print("  [1/7] 构造会话集合...")
    report_progress("cohort", "读取基准期与当前期会话")

    kwargs = {}
    if request.store_id:
        kwargs["store_id"] = request.store_id
    if request.channel:
        kwargs["channel"] = request.channel
    if request.device_type:
        kwargs["device_type"] = request.device_type
    if request.region_code:
        kwargs["region_code"] = request.region_code
    if request.user_type:
        kwargs["user_type"] = request.user_type

    baseline = build_cohort(
        start=request.baseline_start,
        end=request.baseline_end,
        period_name="baseline",
        **kwargs
    )

    current = build_cohort(
        start=request.current_start,
        end=request.current_end,
        period_name="current",
        **kwargs
    )

    # 2. 算整体漏斗
    print("  [2/7] 计算整体漏斗...")
    report_progress("funnel", "计算整体漏斗与转化变化")

    baseline_funnel = calculate_funnel_from_cohort(baseline)
    current_funnel = calculate_funnel_from_cohort(current)

    funnel_change = {
        "visit_change": current_funnel.visit_sessions - baseline_funnel.visit_sessions,
        "cart_change": current_funnel.cart_sessions - baseline_funnel.cart_sessions,
        "order_change": current_funnel.order_sessions - baseline_funnel.order_sessions,
        "cart_rate_change": current_funnel.cart_rate - baseline_funnel.cart_rate,
        "cart_to_order_rate_change": current_funnel.cart_to_order_rate - baseline_funnel.cart_to_order_rate,
        "order_rate_change": current_funnel.order_rate - baseline_funnel.order_rate
    }

    # 3. 算渠道拆解
    print("  [3/7] 渠道拆解...")
    report_progress("channel", "拆解各渠道的结构与转化率影响")
    channel_decomposition = decompose_channel(baseline, current)

    # 4. 算设备拆解
    print("  [4/7] 设备拆解...")
    report_progress("device", "拆解设备维度的影响")
    device_decomposition = decompose_device(baseline, current)

    # 5. 算地区拆解
    print("  [5/7] 地区拆解...")
    report_progress("region", "拆解地区维度的影响")
    region_decomposition = decompose_region(baseline, current)

    # 6. 算用户类型拆解
    print("  [6/7] 用户类型拆解...")
    report_progress("user_type", "拆解新老用户维度的影响")
    user_type_decomposition = decompose_user_type(baseline, current)

    # 7. 算漏斗阶段拆解
    print("  [7/7] 漏斗阶段拆解...")
    report_progress("stage", "拆解访问、加购、下单环节")
    stage_decomposition = decompose_funnel_stages(baseline, current)

    # 查询业务事件（根据维度拆解结果匹配相关事件）
    print("  查询并匹配业务事件...")
    report_progress("events", "匹配相关经营事件")
    business_events = find_related_business_events(
        start=min(request.baseline_start, request.current_start),
        end=max(request.baseline_end, request.current_end),
        store_id=request.store_id,
        channel_decomposition=channel_decomposition,
        device_decomposition=device_decomposition,
        region_decomposition=region_decomposition,
        user_type_decomposition=user_type_decomposition
    )

    # 生成证据
    print("  生成证据...")
    report_progress("evidence", "生成可校验的指标与归因证据")
    evidence = build_evidence_collection(
        baseline=baseline,
        current=current,
        channel_decomposition=channel_decomposition,
        device_decomposition=device_decomposition,
        stage_decomposition=stage_decomposition,
        business_events=business_events
    )

    # 构建结果
    result = AnalysisResult(
        problem=request.problem,
        time_range={
            "baseline_start": request.baseline_start.strftime("%Y-%m-%d"),
            "baseline_end": request.baseline_end.strftime("%Y-%m-%d"),
            "current_start": request.current_start.strftime("%Y-%m-%d"),
            "current_end": request.current_end.strftime("%Y-%m-%d")
        },
        baseline_funnel=baseline_funnel.to_dict(),
        current_funnel=current_funnel.to_dict(),
        funnel_change=funnel_change,
        stage_decomposition=stage_decomposition.to_dict(),
        channel_decomposition=channel_decomposition.to_dict(),
        device_decomposition=device_decomposition.to_dict(),
        region_decomposition=region_decomposition.to_dict(),
        user_type_decomposition=user_type_decomposition.to_dict(),
        business_events=business_events,
        evidence=evidence.to_dict()
    )

    print("[分析完成]")
    return result


# ============================================================
# 测试代码
# ============================================================

if __name__ == "__main__":
    from datetime import timezone

    request = AnalysisRequest(
        problem="为什么本月整体转化率比上月下降？",
        baseline_start=datetime(2026, 6, 1, tzinfo=timezone.utc),
        baseline_end=datetime(2026, 6, 15, tzinfo=timezone.utc),
        current_start=datetime(2026, 7, 1, tzinfo=timezone.utc),
        current_end=datetime(2026, 7, 15, tzinfo=timezone.utc)
    )

    result = run_conversion_analysis(request)

    print("\n" + "=" * 60)
    print("分析结果摘要")
    print("=" * 60)

    print(f"\n问题: {result.problem}")
    print(f"基准期: {result.time_range['baseline_start']} ~ {result.time_range['baseline_end']}")
    print(f"当前期: {result.time_range['current_start']} ~ {result.time_range['current_end']}")

    print(f"\n基准期转化率: {result.baseline_funnel['order_rate']*100:.2f}%")
    print(f"当前期转化率: {result.current_funnel['order_rate']*100:.2f}%")
    print(f"变化: {result.funnel_change['order_rate_change']*100:+.2f}%")

    print(f"\n漏斗阶段贡献:")
    for stage in result.stage_decomposition['stages']:
        print(f"  {stage['stage_name']}: {stage['effect_on_overall']*100:+.4f}%")
    print(f"  合计: {result.stage_decomposition['stages_sum']*100:+.4f}%")

    print(f"\n渠道贡献（按总效应排序）:")
    channel_contribs = sorted(
        result.channel_decomposition['contributions'],
        key=lambda x: abs(x['total_effect']),
        reverse=True
    )
    for c in channel_contribs[:3]:
        print(f"  {c['group_name']}: {c['total_effect']*100:+.4f}% (结构{c['share_effect']*100:+.4f}% + 表现{c['rate_effect']*100:+.4f}%)")

    print(f"\n设备贡献（按总效应排序）:")
    device_contribs = sorted(
        result.device_decomposition['contributions'],
        key=lambda x: abs(x['total_effect']),
        reverse=True
    )
    for c in device_contribs[:3]:
        print(f"  {c['group_name']}: {c['total_effect']*100:+.4f}% (结构{c['share_effect']*100:+.4f}% + 表现{c['rate_effect']*100:+.4f}%)")

    if result.business_events:
        print(f"\n关联业务事件:")
        for event in result.business_events:
            print(f"  - {event['title']}")

    # 保存到文件
    with open("analysis_result.json", "w", encoding="utf-8") as f:
        f.write(result.to_json())
    print("\n完整结果已保存到 analysis_result.json")
