r"""
GMV（销售额）分析内核测试

验证：
- GMV 总量计算正确
- GMV 变化 = 当前期 GMV - 基准期 GMV
- GMV 渠道拆解：各分组效应之和严格等于总效应
- GMV 设备拆解：各分组效应之和严格等于总效应
- 原 order_conversion_rate 行为不受影响

使用方式：
    uv run python -m pytest tests/test_gmv_analysis.py -v
"""

import pytest
from datetime import datetime, timezone

from app.analysis_core.cohort import SessionRecord, CohortResult
from app.analysis_core.gmv import (
    GmvMetrics, GmvChange,
    calculate_gmv, calculate_gmv_from_cohort, calculate_gmv_change,
    calculate_gmv_by_channel, calculate_gmv_by_device,
    decompose_gmv_channel, decompose_gmv_device,
    decompose_gmv_region, decompose_gmv_user_type,
    GmvDecompositionResult,
)
from app.analysis_core.metrics import (
    calculate_funnel_from_cohort, FunnelMetrics,
    calculate_funnel_by_channel,
)
from app.analysis_core.decomposition import decompose_channel


# ============================================================
# 测试数据生成辅助
# ============================================================

def make_session(
    session_id: int,
    channel: str = "organic",
    device_type: str = "mobile_web",
    region_code: str = "east_china",
    user_type: str = "returning",
    has_visit: bool = True,
    has_cart: bool = False,
    has_order: bool = False,
    order_amount: float = 0.0,
) -> SessionRecord:
    """创建测试用 SessionRecord"""
    return SessionRecord(
        session_id=session_id,
        session_key=f"sess_{session_id:06d}",
        store_id="store_001",
        user_id=session_id,
        channel=channel,
        device_type=device_type,
        region_code=region_code,
        user_type_snapshot=user_type,
        started_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        has_visit=has_visit,
        has_cart=has_cart,
        has_order=has_order,
        order_amount=order_amount,
    )


def make_cohort(sessions: list[SessionRecord], period_name: str = "test") -> CohortResult:
    """从会话列表创建 CohortResult"""
    visit_count = sum(1 for s in sessions if s.has_visit)
    cart_count = sum(1 for s in sessions if s.has_cart)
    order_count = sum(1 for s in sessions if s.has_order)
    return CohortResult(
        period_name=period_name,
        start=datetime(2026, 7, 1, tzinfo=timezone.utc),
        end=datetime(2026, 7, 15, tzinfo=timezone.utc),
        total_sessions=len(sessions),
        visit_sessions=visit_count,
        cart_sessions=cart_count,
        order_sessions=order_count,
        sessions=sessions,
    )


# ============================================================
# 测试数据：简单场景（仅有机渠道，便于手算验证）
# ============================================================

def build_simple_baseline() -> CohortResult:
    """
    简单基准期：仅 organic 渠道，便于手算验证

    10 个会话，均有访问，其中 5 个有订单
    - 有机渠道：10 visits, 5 orders, GMV = 100+200+300+400+500 = 1500
      单访客收入 = 1500/10 = 150
    """
    sessions = []
    amounts = [100, 200, 300, 400, 500]
    for i in range(10):
        has_order = i < 5
        sessions.append(make_session(
            session_id=i + 1,
            channel="organic",
            device_type="app",
            has_order=has_order,
            order_amount=amounts[i] if has_order else 0.0,
        ))
    return make_cohort(sessions, "baseline")


def build_simple_current() -> CohortResult:
    """
    简单当前期：仅 organic 渠道

    10 个会话，均有访问，其中 4 个有订单
    - 有机渠道：10 visits, 4 orders, GMV = 150+250+350+450 = 1200
      单访客收入 = 1200/10 = 120
    变化：单访客收入 -30
    """
    sessions = []
    amounts = [150, 250, 350, 450]
    for i in range(10):
        has_order = i < 4
        sessions.append(make_session(
            session_id=i + 1,
            channel="organic",
            device_type="app",
            has_order=has_order,
            order_amount=amounts[i] if has_order else 0.0,
        ))
    return make_cohort(sessions, "current")


# ============================================================
# 测试数据：多维度场景（用于拆解测试）
# ============================================================

def build_multi_dim_baseline() -> CohortResult:
    """
    多维度基准期

    30 个会话（均访问）:
    - organic:  10 visits, 5 orders, GMV = 5000  (单访客收入=500)
    - douyin:   10 visits, 3 orders, GMV = 1500  (单访客收入=150)
    - search_ads: 10 visits, 4 orders, GMV = 2000 (单访客收入=200)

    总计: 30 visits, 12 orders, GMV = 8500
    整体单访客收入 = 8500/30 ≈ 283.3333
    """
    sessions = []

    # organic: 5000 GMV over 5 orders, 10 visits
    org_amounts = [800, 900, 1000, 1100, 1200]  # sum=5000
    for i in range(10):
        has_order = i < 5
        sessions.append(make_session(
            session_id=len(sessions) + 1, channel="organic", device_type="app",
            has_order=has_order,
            order_amount=org_amounts[i] if has_order else 0.0,
        ))

    # douyin: 1500 GMV over 3 orders, 10 visits
    dy_amounts = [400, 500, 600]  # sum=1500
    for i in range(10):
        has_order = i < 3
        sessions.append(make_session(
            session_id=len(sessions) + 1, channel="douyin", device_type="mobile_web",
            has_order=has_order,
            order_amount=dy_amounts[i] if has_order else 0.0,
        ))

    # search_ads: 2000 GMV over 4 orders, 10 visits
    sa_amounts = [300, 400, 600, 700]  # sum=2000
    for i in range(10):
        has_order = i < 4
        sessions.append(make_session(
            session_id=len(sessions) + 1, channel="search_ads", device_type="pc",
            has_order=has_order,
            order_amount=sa_amounts[i] if has_order else 0.0,
        ))

    return make_cohort(sessions, "baseline")


def build_multi_dim_current() -> CohortResult:
    """
    多维度当前期（流量结构变化 + 单访客收入变化）

    36 个会话（均访问）:
    - organic:  8 visits,  4 orders, GMV = 4400  (单访客收入=550)
    - douyin:   16 visits, 5 orders, GMV = 2750  (单访客收入=171.875)
    - search_ads: 12 visits, 5 orders, GMV = 2800 (单访客收入=233.333)

    总计: 36 visits, 14 orders, GMV = 9950
    整体单访客收入 = 9950/36 ≈ 276.3889

    变化:
    - 整体单访客收入: 283.333 → 276.389, delta = -6.944
    - 整体 GMV: 8500 → 9950, delta = +1450
    """
    sessions = []

    # organic: 8 visits, 4 orders, GMV = 4400
    org_amounts = [1000, 1100, 1100, 1200]  # sum=4400
    for i in range(8):
        has_order = i < 4
        sessions.append(make_session(
            session_id=len(sessions) + 1, channel="organic", device_type="app",
            has_order=has_order,
            order_amount=org_amounts[i] if has_order else 0.0,
        ))

    # douyin: 16 visits, 5 orders, GMV = 2750
    dy_amounts = [500, 500, 550, 600, 600]  # sum=2750
    for i in range(16):
        has_order = i < 5
        sessions.append(make_session(
            session_id=len(sessions) + 1, channel="douyin", device_type="mobile_web",
            has_order=has_order,
            order_amount=dy_amounts[i] if has_order else 0.0,
        ))

    # search_ads: 12 visits, 5 orders, GMV = 2800
    sa_amounts = [500, 500, 550, 600, 650]  # sum=2800
    for i in range(12):
        has_order = i < 5
        sessions.append(make_session(
            session_id=len(sessions) + 1, channel="search_ads", device_type="pc",
            has_order=has_order,
            order_amount=sa_amounts[i] if has_order else 0.0,
        ))

    return make_cohort(sessions, "current")


# ============================================================
# 测试数据：设备维度拆解
# ============================================================

def build_device_baseline() -> CohortResult:
    """
    设备维度基准期

    20 个会话:
    - app:        10 visits, 4 orders, GMV = 4000  (单访客收入=400)
    - mobile_web: 6 visits,  2 orders, GMV = 800   (单访客收入≈133.33)
    - pc:         4 visits,  2 orders, GMV = 1200  (单访客收入=300)

    总计: 20 visits, 8 orders, GMV = 6000
    整体单访客收入 = 6000/20 = 300
    """
    sessions = []

    # app
    app_amounts = [800, 900, 1100, 1200]
    for i in range(10):
        has_order = i < 4
        sessions.append(make_session(
            session_id=len(sessions) + 1, device_type="app",
            has_order=has_order,
            order_amount=app_amounts[i] if has_order else 0.0,
        ))

    # mobile_web
    mw_amounts = [350, 450]
    for i in range(6):
        has_order = i < 2
        sessions.append(make_session(
            session_id=len(sessions) + 1, device_type="mobile_web",
            has_order=has_order,
            order_amount=mw_amounts[i] if has_order else 0.0,
        ))

    # pc
    pc_amounts = [500, 700]
    for i in range(4):
        has_order = i < 2
        sessions.append(make_session(
            session_id=len(sessions) + 1, device_type="pc",
            has_order=has_order,
            order_amount=pc_amounts[i] if has_order else 0.0,
        ))

    return make_cohort(sessions, "baseline")


def build_device_current() -> CohortResult:
    """
    设备维度当前期

    24 个会话:
    - app:        8 visits,  3 orders, GMV = 3300  (单访客收入=412.5)
    - mobile_web: 10 visits, 3 orders, GMV = 1200  (单访客收入=120)
    - pc:         6 visits,  3 orders, GMV = 2100  (单访客收入=350)

    总计: 24 visits, 9 orders, GMV = 6600
    整体单访客收入 = 6600/24 = 275
    """
    sessions = []

    # app
    app_amounts = [1000, 1100, 1200]
    for i in range(8):
        has_order = i < 3
        sessions.append(make_session(
            session_id=len(sessions) + 1, device_type="app",
            has_order=has_order,
            order_amount=app_amounts[i] if has_order else 0.0,
        ))

    # mobile_web
    mw_amounts = [350, 400, 450]
    for i in range(10):
        has_order = i < 3
        sessions.append(make_session(
            session_id=len(sessions) + 1, device_type="mobile_web",
            has_order=has_order,
            order_amount=mw_amounts[i] if has_order else 0.0,
        ))

    # pc
    pc_amounts = [600, 700, 800]
    for i in range(6):
        has_order = i < 3
        sessions.append(make_session(
            session_id=len(sessions) + 1, device_type="pc",
            has_order=has_order,
            order_amount=pc_amounts[i] if has_order else 0.0,
        ))

    return make_cohort(sessions, "current")


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def simple_baseline():
    return build_simple_baseline()


@pytest.fixture
def simple_current():
    return build_simple_current()


@pytest.fixture
def multi_dim_baseline():
    return build_multi_dim_baseline()


@pytest.fixture
def multi_dim_current():
    return build_multi_dim_current()


@pytest.fixture
def device_baseline():
    return build_device_baseline()


@pytest.fixture
def device_current():
    return build_device_current()


# ============================================================
# 测试1: GMV 总量计算
# ============================================================

class TestGmvTotals:
    """GMV 总量计算"""

    def test_simple_baseline_gmv(self, simple_baseline):
        """简单基准期 GMV = 1500"""
        gmv = calculate_gmv_from_cohort(simple_baseline)
        assert gmv.total_gmv == 1500.0
        assert gmv.order_sessions == 5
        assert gmv.visit_sessions == 10
        assert gmv.avg_order_value == 300.0  # 1500/5
        assert gmv.revenue_per_visit == 150.0  # 1500/10

    def test_simple_current_gmv(self, simple_current):
        """简单当前期 GMV = 1200"""
        gmv = calculate_gmv_from_cohort(simple_current)
        assert gmv.total_gmv == 1200.0
        assert gmv.order_sessions == 4
        assert gmv.visit_sessions == 10

    def test_multi_dim_baseline_gmv(self, multi_dim_baseline):
        """多维度基准期 GMV = 8500"""
        gmv = calculate_gmv_from_cohort(multi_dim_baseline)
        assert gmv.total_gmv == 8500.0
        assert gmv.order_sessions == 12
        assert gmv.visit_sessions == 30

    def test_multi_dim_current_gmv(self, multi_dim_current):
        """多维度当前期 GMV = 9950"""
        gmv = calculate_gmv_from_cohort(multi_dim_current)
        assert gmv.total_gmv == 9950.0
        assert gmv.order_sessions == 14
        assert gmv.visit_sessions == 36

    def test_zero_visits_handled_gracefully(self):
        """空会话列表应返回零值而不报错"""
        empty_cohort = make_cohort([])
        gmv = calculate_gmv_from_cohort(empty_cohort)
        assert gmv.total_gmv == 0.0
        assert gmv.order_sessions == 0
        assert gmv.visit_sessions == 0
        assert gmv.avg_order_value == 0.0
        assert gmv.revenue_per_visit == 0.0

    def test_visits_without_orders(self):
        """有访问但无订单的会话不影响 GMV 但计入 visit_sessions"""
        sessions = [
            make_session(1, has_visit=True, has_order=False),
            make_session(2, has_visit=True, has_order=False),
            make_session(3, has_visit=True, has_order=False),
        ]
        cohort = make_cohort(sessions)
        gmv = calculate_gmv_from_cohort(cohort)
        assert gmv.total_gmv == 0.0
        assert gmv.order_sessions == 0
        assert gmv.visit_sessions == 3
        assert gmv.revenue_per_visit == 0.0


# ============================================================
# 测试2: GMV 变化计算
# ============================================================

class TestGmvChange:
    """GMV 变化计算"""

    def test_simple_gmv_change(self, simple_baseline, simple_current):
        """简单场景：GMV 从 1500 降到 1200"""
        b_gmv = calculate_gmv_from_cohort(simple_baseline)
        c_gmv = calculate_gmv_from_cohort(simple_current)
        change = calculate_gmv_change(b_gmv, c_gmv)

        assert change.gmv_change == -300.0
        assert change.revenue_per_visit_change == -30.0  # 120-150

    def test_multi_dim_gmv_change(self, multi_dim_baseline, multi_dim_current):
        """多维度场景：GMV 从 8500 涨到 9950"""
        b_gmv = calculate_gmv_from_cohort(multi_dim_baseline)
        c_gmv = calculate_gmv_from_cohort(multi_dim_current)
        change = calculate_gmv_change(b_gmv, c_gmv)

        assert change.gmv_change == 1450.0
        assert abs(change.baseline.revenue_per_visit - 8500 / 30) < 0.01
        assert abs(change.current.revenue_per_visit - 9950 / 36) < 0.01

    def test_gmv_change_rate(self, simple_baseline, simple_current):
        """GMV 变化率"""
        b_gmv = calculate_gmv_from_cohort(simple_baseline)
        c_gmv = calculate_gmv_from_cohort(simple_current)
        change = calculate_gmv_change(b_gmv, c_gmv)

        assert change.gmv_change_rate == pytest.approx(-0.2)  # -300/1500


# ============================================================
# 测试3: GMV 渠道拆解（效应加总一致性）
# ============================================================

class TestGmvChannelDecomposition:
    """GMV 渠道拆解"""

    def test_channel_decomposition_sum_equals_total(
        self, multi_dim_baseline, multi_dim_current
    ):
        """渠道拆解：各分组效应之和严格等于总效应"""
        result = decompose_gmv_channel(multi_dim_baseline, multi_dim_current)

        total_from_contributions = sum(c.total_effect for c in result.contributions)
        assert abs(total_from_contributions - result.total_effect) < 0.0001, (
            f"contributions_sum={total_from_contributions:.6f}, "
            f"total_effect={result.total_effect:.6f}"
        )

    def test_channel_decomposition_share_rate_sum(
        self, multi_dim_baseline, multi_dim_current
    ):
        """渠道拆解：share_effect + rate_effect 合计应等于总效应"""
        result = decompose_gmv_channel(multi_dim_baseline, multi_dim_current)

        assert abs(result.total_share_effect + result.total_rate_effect
                   - result.total_effect) < 0.0001

    def test_channel_decomposition_total_effect_matches_manual(
        self, multi_dim_baseline, multi_dim_current
    ):
        """渠道拆解：总效应等于手动计算的 revenue_per_visit 变化"""
        b_gmv = calculate_gmv_from_cohort(multi_dim_baseline)
        c_gmv = calculate_gmv_from_cohort(multi_dim_current)
        manual_delta = c_gmv.revenue_per_visit - b_gmv.revenue_per_visit

        result = decompose_gmv_channel(multi_dim_baseline, multi_dim_current)
        assert abs(result.total_effect - manual_delta) < 0.0001, (
            f"result.total_effect={result.total_effect:.6f}, "
            f"manual_delta={manual_delta:.6f}"
        )

    def test_channel_decomposition_has_all_groups(
        self, multi_dim_baseline, multi_dim_current
    ):
        """渠道拆解：包含所有渠道分组"""
        result = decompose_gmv_channel(multi_dim_baseline, multi_dim_current)
        group_names = {c.group_name for c in result.contributions}
        assert group_names == {"organic", "douyin", "search_ads"}

    def test_channel_visit_sum_equals_total(
        self, multi_dim_baseline, multi_dim_current
    ):
        """渠道拆解：各渠道 visit 加总等于整体"""
        result = decompose_gmv_channel(multi_dim_baseline, multi_dim_current)
        baseline_visit_sum = sum(c.baseline_visit for c in result.contributions)
        current_visit_sum = sum(c.current_visit for c in result.contributions)
        assert baseline_visit_sum == multi_dim_baseline.visit_sessions
        assert current_visit_sum == multi_dim_current.visit_sessions

    def test_channel_gmv_sum_equals_total(
        self, multi_dim_baseline, multi_dim_current
    ):
        """渠道拆解：各渠道 GMV 加总等于整体"""
        result = decompose_gmv_channel(multi_dim_baseline, multi_dim_current)
        baseline_gmv_sum = sum(c.baseline_gmv for c in result.contributions)
        current_gmv_sum = sum(c.current_gmv for c in result.contributions)
        assert abs(baseline_gmv_sum - result.baseline_total_gmv) < 0.01
        assert abs(current_gmv_sum - result.current_total_gmv) < 0.01

    def test_channel_decomposition_single_group_zero_effect(self):
        """单分组渠道：效应为零"""
        sessions = [make_session(i + 1, channel="organic", has_order=True, order_amount=100) for i in range(10)]
        cohort = make_cohort(sessions, "baseline")
        result = decompose_gmv_channel(cohort, cohort)  # 同周期对比
        assert abs(result.total_effect) < 0.0001
        for c in result.contributions:
            assert abs(c.total_effect) < 0.0001


# ============================================================
# 测试4: GMV 设备拆解（第二个维度拆解）
# ============================================================

class TestGmvDeviceDecomposition:
    """GMV 设备拆解"""

    def test_device_decomposition_sum_equals_total(
        self, device_baseline, device_current
    ):
        """设备拆解：各分组效应之和严格等于总效应"""
        result = decompose_gmv_device(device_baseline, device_current)

        total_from_contributions = sum(c.total_effect for c in result.contributions)
        assert abs(total_from_contributions - result.total_effect) < 0.0001, (
            f"contributions_sum={total_from_contributions:.6f}, "
            f"total_effect={result.total_effect:.6f}"
        )

    def test_device_decomposition_total_effect_matches_manual(
        self, device_baseline, device_current
    ):
        """设备拆解：总效应等于手动计算的 revenue_per_visit 变化"""
        b_gmv = calculate_gmv_from_cohort(device_baseline)
        c_gmv = calculate_gmv_from_cohort(device_current)
        manual_delta = c_gmv.revenue_per_visit - b_gmv.revenue_per_visit

        result = decompose_gmv_device(device_baseline, device_current)
        assert abs(result.total_effect - manual_delta) < 0.0001

    def test_device_decomposition_has_all_groups(
        self, device_baseline, device_current
    ):
        """设备拆解：包含所有设备分组"""
        result = decompose_gmv_device(device_baseline, device_current)
        group_names = {c.group_name for c in result.contributions}
        assert group_names == {"app", "mobile_web", "pc"}

    def test_device_decomposition_gmv_change_is_absolute(
        self, device_baseline, device_current
    ):
        """设备拆解：gmv_change_absolute 正确"""
        result = decompose_gmv_device(device_baseline, device_current)
        expected = 6600.0 - 6000.0
        assert result.gmv_change_absolute == expected


# ============================================================
# 测试5: GMV 按地区拆解
# ============================================================

class TestGmvRegionDecomposition:
    """GMV 地区拆解"""

    def test_region_decomposition_sum_equals_total(self):
        """地区拆解：效应之和等于总效应"""
        # 构造简单的两地区数据
        b_sessions = [
            make_session(1, region_code="east_china", has_order=True, order_amount=500),
            make_session(2, region_code="east_china", has_order=True, order_amount=300),
            make_session(3, region_code="north_china", has_order=True, order_amount=200),
            make_session(4, region_code="north_china", has_order=False),
        ]
        c_sessions = [
            make_session(11, region_code="east_china", has_order=True, order_amount=600),
            make_session(12, region_code="east_china", has_order=False),
            make_session(13, region_code="north_china", has_order=True, order_amount=400),
            make_session(14, region_code="north_china", has_order=True, order_amount=300),
        ]
        b = make_cohort(b_sessions, "baseline")
        c = make_cohort(c_sessions, "current")

        result = decompose_gmv_region(b, c)
        contributions_sum = sum(ct.total_effect for ct in result.contributions)
        assert abs(contributions_sum - result.total_effect) < 0.0001

    def test_region_decomposition_handle_unknown(self):
        """地区拆解：region_code 为 None 时归类为 unknown"""
        sessions = [
            make_session(1, region_code=None, has_order=True, order_amount=100),
            make_session(2, region_code=None, has_order=False),
        ]
        cohort = make_cohort(sessions, "test")
        result = decompose_gmv_region(cohort, cohort)
        group_names = {c.group_name for c in result.contributions}
        assert "unknown" in group_names


# ============================================================
# 测试6: GMV 按用户类型拆解
# ============================================================

class TestGmvUserTypeDecomposition:
    """GMV 用户类型拆解"""

    def test_user_type_decomposition_sum_equals_total(self):
        """用户类型拆解：效应之和等于总效应"""
        b_sessions = [
            make_session(1, user_type="new", has_order=True, order_amount=100),
            make_session(2, user_type="new", has_order=True, order_amount=200),
            make_session(3, user_type="returning", has_order=True, order_amount=500),
            make_session(4, user_type="returning", has_order=False),
        ]
        c_sessions = [
            make_session(11, user_type="new", has_order=True, order_amount=150),
            make_session(12, user_type="new", has_order=False),
            make_session(13, user_type="returning", has_order=True, order_amount=600),
            make_session(14, user_type="returning", has_order=True, order_amount=400),
        ]
        b = make_cohort(b_sessions, "baseline")
        c = make_cohort(c_sessions, "current")

        result = decompose_gmv_user_type(b, c)
        contributions_sum = sum(ct.total_effect for ct in result.contributions)
        assert abs(contributions_sum - result.total_effect) < 0.0001


# ============================================================
# 测试7: 原 order_conversion_rate 不回归
# ============================================================

class TestConversionRateRegression:
    """确保原 order_conversion_rate 行为不受 GMV 改动影响"""

    def test_funnel_metrics_unchanged(self, simple_baseline):
        """漏斗指标计算不受 order_amount 字段影响"""
        funnel = calculate_funnel_from_cohort(simple_baseline)
        assert funnel.visit_sessions == 10
        assert funnel.cart_sessions == 0
        assert funnel.order_sessions == 5
        assert funnel.order_rate == 0.5

    def test_funnel_by_channel_unchanged(self, multi_dim_baseline):
        """渠道漏斗分组不受影响"""
        by_channel = calculate_funnel_by_channel(multi_dim_baseline)
        assert "organic" in by_channel
        assert "douyin" in by_channel
        assert by_channel["organic"].visit_sessions == 10

    def test_decomposition_unchanged(self, multi_dim_baseline, multi_dim_current):
        """渠道拆解不受 order_amount 字段影响"""
        result = decompose_channel(multi_dim_baseline, multi_dim_current)
        contributions_sum = sum(c.total_effect for c in result.contributions)
        assert abs(contributions_sum - result.total_effect) < 0.0001

    def test_session_record_backward_compatible(self):
        """SessionRecord 默认 order_amount=0.0，向后兼容"""
        s = SessionRecord(
            session_id=1, session_key="test", store_id="s1",
            user_id=1, channel="organic", device_type="app",
            region_code="east", user_type_snapshot="new",
            started_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            has_visit=True, has_cart=False, has_order=False,
        )
        assert s.order_amount == 0.0
        # 不提供 order_amount 的老代码也能工作
        gmv = calculate_gmv([s])
        assert gmv.total_gmv == 0.0


# ============================================================
# 测试8: GMV 分组计算
# ============================================================

class TestGmvByDimension:
    """按维度分组计算 GMV"""

    def test_gmv_by_channel_sum_equals_total(self, multi_dim_baseline):
        """按渠道分组 GMV 之和等于总 GMV"""
        by_channel = calculate_gmv_by_channel(multi_dim_baseline)
        total = calculate_gmv_from_cohort(multi_dim_baseline)
        gmv_sum = sum(m.total_gmv for m in by_channel.values())
        assert abs(gmv_sum - total.total_gmv) < 0.01

    def test_gmv_by_device_sum_equals_total(self, device_baseline):
        """按设备分组 GMV 之和等于总 GMV"""
        by_device = calculate_gmv_by_device(device_baseline)
        total = calculate_gmv_from_cohort(device_baseline)
        gmv_sum = sum(m.total_gmv for m in by_device.values())
        assert abs(gmv_sum - total.total_gmv) < 0.01


# ============================================================
# 测试9: GMV 拆解手算验证
# ============================================================

class TestGmvDecompositionManual:
    """手算验证 GMV 拆解公式"""

    def test_simple_channel_manual_verification(self):
        """
        手工验证简单两渠道场景的对称分解公式

        基准期:
          organic: 4 visits, 2 orders, GMV=300 (revenue_per_visit=75)
          douyin:  6 visits, 3 orders, GMV=600 (revenue_per_visit=100)
          整体: 10 visits, 5 orders, GMV=900, revenue_per_visit=90

        当前期:
          organic: 6 visits, 3 orders, GMV=480 (revenue_per_visit=80)
          douyin:  4 visits, 1 orders, GMV=120 (revenue_per_visit=30)
          整体: 10 visits, 4 orders, GMV=600, revenue_per_visit=60

        整体 revenue_per_visit 变化 = 60 - 90 = -30

        手算拆解:
          organic:
            s0=0.4, s1=0.6, r0=75, r1=80
            share_effect = (0.6-0.4) * (75+80)/2 = 0.2 * 77.5 = 15.5
            rate_effect  = (80-75) * (0.4+0.6)/2 = 5 * 0.5 = 2.5
            total = 18.0

          douyin:
            s0=0.6, s1=0.4, r0=100, r1=30
            share_effect = (0.4-0.6) * (100+30)/2 = -0.2 * 65 = -13.0
            rate_effect  = (30-100) * (0.6+0.4)/2 = -70 * 0.5 = -35.0
            total = -48.0

          分组效应之和: 18.0 + (-48.0) = -30.0 ✓
        """
        b_sessions = [
            make_session(1, channel="organic", has_order=True, order_amount=100),
            make_session(2, channel="organic", has_order=True, order_amount=200),
            make_session(3, channel="organic", has_order=False),
            make_session(4, channel="organic", has_order=False),
            make_session(5, channel="douyin", has_order=True, order_amount=150),
            make_session(6, channel="douyin", has_order=True, order_amount=200),
            make_session(7, channel="douyin", has_order=True, order_amount=250),
            make_session(8, channel="douyin", has_order=False),
            make_session(9, channel="douyin", has_order=False),
            make_session(10, channel="douyin", has_order=False),
        ]
        c_sessions = [
            make_session(11, channel="organic", has_order=True, order_amount=120),
            make_session(12, channel="organic", has_order=True, order_amount=160),
            make_session(13, channel="organic", has_order=True, order_amount=200),
            make_session(14, channel="organic", has_order=False),
            make_session(15, channel="organic", has_order=False),
            make_session(16, channel="organic", has_order=False),
            make_session(17, channel="douyin", has_order=True, order_amount=120),
            make_session(18, channel="douyin", has_order=False),
            make_session(19, channel="douyin", has_order=False),
            make_session(20, channel="douyin", has_order=False),
        ]
        b = make_cohort(b_sessions, "baseline")
        c = make_cohort(c_sessions, "current")

        result = decompose_gmv_channel(b, c)

        # 总效应 = -30（revenue_per_visit 从 90 到 60）
        assert abs(result.total_effect - (-30.0)) < 0.0001

        # 手算验证各分组
        organic = next(ct for ct in result.contributions if ct.group_name == "organic")
        douyin = next(ct for ct in result.contributions if ct.group_name == "douyin")

        assert abs(organic.share_effect - 15.5) < 0.0001
        assert abs(organic.rate_effect - 2.5) < 0.0001
        assert abs(organic.total_effect - 18.0) < 0.0001

        assert abs(douyin.share_effect - (-13.0)) < 0.0001
        assert abs(douyin.rate_effect - (-35.0)) < 0.0001
        assert abs(douyin.total_effect - (-48.0)) < 0.0001

        # 效应之和 = 总效应
        contributions_sum = sum(ct.total_effect for ct in result.contributions)
        assert abs(contributions_sum - result.total_effect) < 0.0001


# ============================================================
# 测试10: GmvMetrics 和 GmvChange dataclass 方法
# ============================================================

class TestGmvDataclasses:
    """GmvMetrics 和 GmvChange 数据类"""

    def test_gmv_metrics_properties(self):
        gmv = GmvMetrics(total_gmv=1000.0, order_sessions=5, visit_sessions=20)
        assert gmv.avg_order_value == 200.0
        assert gmv.revenue_per_visit == 50.0

    def test_gmv_metrics_zero_orders(self):
        gmv = GmvMetrics(total_gmv=0.0, order_sessions=0, visit_sessions=10)
        assert gmv.avg_order_value == 0.0
        assert gmv.revenue_per_visit == 0.0

    def test_gmv_change_properties(self):
        b = GmvMetrics(total_gmv=1000.0, order_sessions=5, visit_sessions=20)
        c = GmvMetrics(total_gmv=1500.0, order_sessions=8, visit_sessions=25)
        change = GmvChange(baseline=b, current=c)
        assert change.gmv_change == 500.0
        assert change.gmv_change_rate == 0.5

    def test_gmv_change_zero_baseline(self):
        b = GmvMetrics(total_gmv=0.0, order_sessions=0, visit_sessions=10)
        c = GmvMetrics(total_gmv=100.0, order_sessions=1, visit_sessions=10)
        change = GmvChange(baseline=b, current=c)
        assert change.gmv_change == 100.0
        assert change.gmv_change_rate == 0.0  # 基准期 GMV=0，变化率定义为 0

    def test_gmv_metrics_to_dict(self):
        gmv = GmvMetrics(total_gmv=1234.56, order_sessions=10, visit_sessions=100)
        d = gmv.to_dict()
        assert d["total_gmv"] == 1234.56
        assert d["order_sessions"] == 10
        assert d["visit_sessions"] == 100

    def test_gmv_decomposition_to_dict(self, multi_dim_baseline, multi_dim_current):
        result = decompose_gmv_channel(multi_dim_baseline, multi_dim_current)
        d = result.to_dict()
        assert d["dimension_name"] == "渠道"
        assert "contributions" in d
        assert "effects" in d
        assert "gmv_change_absolute" in d


# ============================================================
# 测试11: 独立 GmvMetrics 构造
# ============================================================

class TestGmvMetricsDirect:
    """直接使用 calculate_gmv 计算原始 session 列表"""

    def test_calculate_gmv_empty(self):
        assert calculate_gmv([]).total_gmv == 0.0

    def test_calculate_gmv_only_orders_matter(self):
        """只有 has_order=True 的会话才计入 GMV"""
        sessions = [
            make_session(1, has_order=False, order_amount=999),
            make_session(2, has_order=True, order_amount=100),
            make_session(3, has_order=True, order_amount=200),
        ]
        gmv = calculate_gmv(sessions)
        assert gmv.total_gmv == 300.0
        assert gmv.order_sessions == 2
