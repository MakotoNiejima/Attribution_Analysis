"""
构造分析周期内的有效会话集合

职责：
- 按时间范围筛选会话
- 排除机器人流量
- 关联访问、加购、订单事件
- 返回可直接用于漏斗计算的会话集合
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List

from sqlalchemy import text

# 从配置模块导入
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app.config import get_engine


# ============================================================
# 数据结构
# ============================================================

@dataclass
class SessionRecord:
    """单条会话记录"""
    session_id: int
    session_key: str
    store_id: str
    user_id: Optional[int]
    channel: str
    device_type: str
    region_code: Optional[str]
    user_type_snapshot: str
    started_at: datetime
    has_visit: bool
    has_cart: bool
    has_order: bool
    order_amount: float = 0.0


@dataclass
class CohortResult:
    """会话集合结果"""
    period_name: str  # baseline / current
    start: datetime
    end: datetime
    total_sessions: int
    visit_sessions: int
    cart_sessions: int
    order_sessions: int
    sessions: List[SessionRecord]

    @property
    def visit_session_ids(self) -> List[int]:
        """有访问的会话ID列表"""
        return [s.session_id for s in self.sessions if s.has_visit]

    @property
    def cart_session_ids(self) -> List[int]:
        """有加购的会话ID列表"""
        return [s.session_id for s in self.sessions if s.has_cart]

    @property
    def order_session_ids(self) -> List[int]:
        """有下单的会话ID列表"""
        return [s.session_id for s in self.sessions if s.has_order]


# ============================================================
# 核心函数
# ============================================================

def build_cohort(
    start: datetime,
    end: datetime,
    period_name: str = "unknown",
    store_id: Optional[str] = None,
    channel: Optional[str] = None,
    device_type: Optional[str] = None,
    region_code: Optional[str] = None,
    user_type: Optional[str] = None,
    exclude_bot: bool = True,
    engine=None
) -> CohortResult:
    """
    构建会话集合

    Args:
        start: 周期开始时间
        end: 周期结束时间
        period_name: 周期名称（baseline/current）
        store_id: 店铺筛选
        channel: 渠道筛选
        device_type: 设备筛选
        region_code: 地区筛选
        user_type: 用户类型筛选
        exclude_bot: 是否排除机器人
        engine: 数据库引擎（可选）

    Returns:
        CohortResult: 会话集合结果
    """

    # 构建筛选条件
    conditions = []
    params = {}

    conditions.append("s.started_at >= :start")
    params["start"] = start

    conditions.append("s.started_at < :end")
    params["end"] = end

    if exclude_bot:
        conditions.append("s.is_bot = 0")

    if store_id:
        conditions.append("s.store_id = :store_id")
        params["store_id"] = store_id

    if channel:
        conditions.append("s.channel = :channel")
        params["channel"] = channel

    if device_type:
        conditions.append("s.device_type = :device_type")
        params["device_type"] = device_type

    if region_code:
        conditions.append("s.region_code = :region_code")
        params["region_code"] = region_code

    if user_type:
        conditions.append("s.user_type_snapshot = :user_type")
        params["user_type"] = user_type

    where_clause = " AND ".join(conditions)

    # SQL 查询：关联访问、加购、订单事件
    # 有效订单条件：order_status IN ('paid', 'completed') AND paid_at IS NOT NULL
    # 24小时窗口：事件发生在会话开始后24小时内
    sql = text(f"""
        SELECT
            s.id as session_id,
            s.session_key,
            s.store_id,
            s.user_id,
            s.channel,
            s.device_type,
            s.region_code,
            s.user_type_snapshot,
            s.started_at,
            CASE WHEN v.id IS NOT NULL THEN 1 ELSE 0 END as has_visit,
            CASE WHEN c.id IS NOT NULL THEN 1 ELSE 0 END as has_cart,
            CASE WHEN o.id IS NOT NULL THEN 1 ELSE 0 END as has_order,
            COALESCE(o.total_amount, 0) as order_amount
        FROM sessions s
        LEFT JOIN (
            SELECT session_id, MIN(id) as id
            FROM visit_events
            WHERE occurred_at >= (
                SELECT started_at FROM sessions s2 WHERE s2.id = visit_events.session_id
            )
            AND occurred_at < DATE_ADD(
                (SELECT started_at FROM sessions s2 WHERE s2.id = visit_events.session_id),
                INTERVAL 24 HOUR
            )
            GROUP BY session_id
        ) v ON v.session_id = s.id
        LEFT JOIN (
            SELECT session_id, MIN(id) as id
            FROM cart_events
            WHERE action = 'add'
              AND occurred_at >= (
                SELECT started_at FROM sessions s2 WHERE s2.id = cart_events.session_id
              )
              AND occurred_at < DATE_ADD(
                (SELECT started_at FROM sessions s2 WHERE s2.id = cart_events.session_id),
                INTERVAL 24 HOUR
              )
            GROUP BY session_id
        ) c ON c.session_id = s.id
        LEFT JOIN (
            SELECT session_id, MIN(id) as id, SUM(order_amount) as total_amount
            FROM orders
            WHERE order_status IN ('paid', 'completed')
              AND paid_at IS NOT NULL
              AND paid_at >= (
                SELECT started_at FROM sessions s2 WHERE s2.id = orders.session_id
              )
              AND paid_at < DATE_ADD(
                (SELECT started_at FROM sessions s2 WHERE s2.id = orders.session_id),
                INTERVAL 24 HOUR
              )
            GROUP BY session_id
        ) o ON o.session_id = s.id
        WHERE {where_clause}
        ORDER BY s.id
    """)

    # 执行查询
    close_engine = False
    if engine is None:
        engine = get_engine()
        close_engine = True

    try:
        with engine.connect() as conn:
            result = conn.execute(sql, params)
            rows = result.fetchall()

        # 构建会话记录
        sessions = []
        for row in rows:
            session = SessionRecord(
                session_id=row[0],
                session_key=row[1],
                store_id=row[2],
                user_id=row[3],
                channel=row[4],
                device_type=row[5],
                region_code=row[6],
                user_type_snapshot=row[7],
                started_at=row[8],
                has_visit=bool(row[9]),
                has_cart=bool(row[10]),
                has_order=bool(row[11]),
                order_amount=float(row[12]) if row[12] is not None else 0.0
            )
            sessions.append(session)

        # 统计
        visit_count = sum(1 for s in sessions if s.has_visit)
        cart_count = sum(1 for s in sessions if s.has_cart)
        order_count = sum(1 for s in sessions if s.has_order)

        return CohortResult(
            period_name=period_name,
            start=start,
            end=end,
            total_sessions=len(sessions),
            visit_sessions=visit_count,
            cart_sessions=cart_count,
            order_sessions=order_count,
            sessions=sessions
        )

    finally:
        if close_engine:
            engine.dispose()


def build_baseline_and_current(
    baseline_start: datetime,
    baseline_end: datetime,
    current_start: datetime,
    current_end: datetime,
    **kwargs
) -> tuple:
    """
    同时构建基准期和当前期会话集合

    Returns:
        (baseline_cohort, current_cohort)
    """
    engine = get_engine()

    try:
        baseline = build_cohort(
            start=baseline_start,
            end=baseline_end,
            period_name="baseline",
            engine=engine,
            **kwargs
        )

        current = build_cohort(
            start=current_start,
            end=current_end,
            period_name="current",
            engine=engine,
            **kwargs
        )

        return baseline, current

    finally:
        engine.dispose()


# ============================================================
# 辅助函数
# ============================================================

def filter_sessions_by_channel(cohort: CohortResult, channel: str) -> List[SessionRecord]:
    """按渠道筛选会话"""
    return [s for s in cohort.sessions if s.channel == channel]


def filter_sessions_by_device(cohort: CohortResult, device_type: str) -> List[SessionRecord]:
    """按设备筛选会话"""
    return [s for s in cohort.sessions if s.device_type == device_type]


def filter_sessions_by_region(cohort: CohortResult, region_code: str) -> List[SessionRecord]:
    """按地区筛选会话"""
    return [s for s in cohort.sessions if s.region_code == region_code]


def get_sessions_by_visit_status(cohort: CohortResult, has_visit: bool = True) -> List[SessionRecord]:
    """按访问状态筛选会话"""
    return [s for s in cohort.sessions if s.has_visit == has_visit]


def get_sessions_by_cart_status(cohort: CohortResult, has_cart: bool = True) -> List[SessionRecord]:
    """按加购状态筛选会话"""
    return [s for s in cohort.sessions if s.has_cart == has_cart]


def get_sessions_by_order_status(cohort: CohortResult, has_order: bool = True) -> List[SessionRecord]:
    """按下单状态筛选会话"""
    return [s for s in cohort.sessions if s.has_order == has_order]


# ============================================================
# 测试代码
# ============================================================

if __name__ == "__main__":
    from datetime import timezone

    # 测试构建会话集合
    baseline_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    baseline_end = datetime(2026, 6, 15, tzinfo=timezone.utc)
    current_start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    current_end = datetime(2026, 7, 15, tzinfo=timezone.utc)

    print("构建基准期会话集合...")
    baseline = build_cohort(baseline_start, baseline_end, "baseline")
    print(f"  总会话: {baseline.total_sessions}")
    print(f"  访问会话: {baseline.visit_sessions}")
    print(f"  加购会话: {baseline.cart_sessions}")
    print(f"  下单会话: {baseline.order_sessions}")

    print("\n构建当前期会话集合...")
    current = build_cohort(current_start, current_end, "current")
    print(f"  总会话: {current.total_sessions}")
    print(f"  访问会话: {current.visit_sessions}")
    print(f"  加购会话: {current.cart_sessions}")
    print(f"  下单会话: {current.order_sessions}")

    print("\n按渠道筛选（抖音）...")
    douyin_sessions = filter_sessions_by_channel(current, "douyin")
    print(f"  抖音会话数: {len(douyin_sessions)}")
    douyin_visit = sum(1 for s in douyin_sessions if s.has_visit)
    douyin_order = sum(1 for s in douyin_sessions if s.has_order)
    print(f"  抖音访问: {douyin_visit}")
    print(f"  抖音下单: {douyin_order}")
    if douyin_visit > 0:
        print(f"  抖音转化率: {douyin_order/douyin_visit*100:.2f}%")
    else:
        print("  抖音转化率: 0%")
