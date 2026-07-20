r"""
归因内核测试

验证：
- 基准期/当前期漏斗数值
- 总体转化率变化等于每个维度的贡献之和
- 总体转化率变化等于两个漏斗阶段贡献之和
- 分组会话数加总等于整体会话数
- 有效订单都满足支付时间条件

使用方式：
    cd D:\dev\归因分析
    python -m pytest app/analysis_core/test_core.py -v
    或者
    python app/analysis_core/test_core.py
"""

import sys
import os

# 确保能找到 app 模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from datetime import datetime, timezone

from app.analysis_core.cohort import build_cohort
from app.analysis_core.metrics import calculate_funnel_from_cohort
from app.analysis_core.decomposition import decompose_channel, decompose_device, decompose_funnel_stages
from app.analysis_core.service import AnalysisRequest, match_event_to_groups, run_conversion_analysis
from app.config import get_engine
from sqlalchemy import text


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def baseline_cohort():
    """基准期会话集合"""
    return build_cohort(
        start=datetime(2026, 6, 1, tzinfo=timezone.utc),
        end=datetime(2026, 6, 15, tzinfo=timezone.utc),
        period_name="baseline"
    )


@pytest.fixture(scope="module")
def current_cohort():
    """当前期会话集合"""
    return build_cohort(
        start=datetime(2026, 7, 1, tzinfo=timezone.utc),
        end=datetime(2026, 7, 15, tzinfo=timezone.utc),
        period_name="current"
    )


@pytest.fixture(scope="module")
def baseline_funnel(baseline_cohort):
    """基准期漏斗指标"""
    return calculate_funnel_from_cohort(baseline_cohort)


@pytest.fixture(scope="module")
def current_funnel(current_cohort):
    """当前期漏斗指标"""
    return calculate_funnel_from_cohort(current_cohort)


@pytest.fixture(scope="module")
def total_change(baseline_funnel, current_funnel):
    """总体转化率变化"""
    return current_funnel.order_rate - baseline_funnel.order_rate


@pytest.fixture(scope="module")
def channel_decomposition(baseline_cohort, current_cohort):
    """渠道拆解结果"""
    return decompose_channel(baseline_cohort, current_cohort)


@pytest.fixture(scope="module")
def device_decomposition(baseline_cohort, current_cohort):
    """设备拆解结果"""
    return decompose_device(baseline_cohort, current_cohort)


@pytest.fixture(scope="module")
def stage_decomposition(baseline_cohort, current_cohort):
    """漏斗阶段拆解结果"""
    return decompose_funnel_stages(baseline_cohort, current_cohort)


# ============================================================
# 测试1: 漏斗数值
# ============================================================

class TestBusinessEventMatching:
    """业务事件必须有已分析维度的匹配证据。"""

    def test_product_scoped_event_needs_product_analysis(self):
        event = {"scope_json": {"product_id": ["prod_001"]}}
        assert not match_event_to_groups(
            event,
            channel_groups=["douyin"],
            device_groups=["mobile_web"]
        )

    def test_event_matches_supported_dimension(self):
        event = {"scope_json": {"device_type": ["mobile_web"], "page_type": ["checkout"]}}
        assert match_event_to_groups(event, device_groups=["mobile_web"])

    def test_event_requires_dimension_overlap(self):
        event = {"scope_json": {"channel": ["organic"]}}
        assert not match_event_to_groups(event, channel_groups=["douyin"])


class TestAnalysisService:
    def test_service_returns_complete_structured_result(self):
        result = run_conversion_analysis(AnalysisRequest(
            problem="为什么本月整体转化率比上月下降？",
            baseline_start=datetime(2026, 6, 1, tzinfo=timezone.utc),
            baseline_end=datetime(2026, 6, 15, tzinfo=timezone.utc),
            current_start=datetime(2026, 7, 1, tzinfo=timezone.utc),
            current_end=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )).to_dict()

        assert result["baseline_funnel"]["order_rate"] == 0.037
        assert result["current_funnel"]["order_rate"] == 0.0166
        assert result["evidence"]["metrics"]
        assert result["channel_decomposition"]["contributions"]


class TestFunnelValues:
    """漏斗数值验证"""

    def test_baseline_visit_sessions(self, baseline_cohort):
        """基准期访问会话 = 3000"""
        assert baseline_cohort.visit_sessions == 3000

    def test_baseline_cart_sessions(self, baseline_cohort):
        """基准期加购会话 = 904"""
        assert baseline_cohort.cart_sessions == 904

    def test_baseline_order_sessions(self, baseline_cohort):
        """基准期下单会话 = 111"""
        assert baseline_cohort.order_sessions == 111

    def test_current_visit_sessions(self, current_cohort):
        """当前期访问会话 = 3500"""
        assert current_cohort.visit_sessions == 3500

    def test_current_cart_sessions(self, current_cohort):
        """当前期加购会话 = 839"""
        assert current_cohort.cart_sessions == 839

    def test_current_order_sessions(self, current_cohort):
        """当前期下单会话 = 58"""
        assert current_cohort.order_sessions == 58


# ============================================================
# 测试2: 漏斗递减性
# ============================================================

class TestFunnelMonotonicity:
    """漏斗递减性"""

    def test_baseline_decreasing(self, baseline_cohort):
        """基准期: visit >= cart >= order"""
        assert baseline_cohort.visit_sessions >= baseline_cohort.cart_sessions >= baseline_cohort.order_sessions

    def test_current_decreasing(self, current_cohort):
        """当前期: visit >= cart >= order"""
        assert current_cohort.visit_sessions >= current_cohort.cart_sessions >= current_cohort.order_sessions


# ============================================================
# 测试3: 效应加总一致性
# ============================================================

class TestEffectConsistency:
    """效应加总一致性"""

    def test_total_equals_stage_sum(self, total_change, stage_decomposition):
        """总体转化率变化 = 漏斗阶段贡献之和"""
        stages_sum = stage_decomposition.stages_sum
        assert abs(total_change - stages_sum) < 0.0001, f"total={total_change:.6f}, stages_sum={stages_sum:.6f}"

    def test_total_equals_channel_sum(self, total_change, channel_decomposition):
        """总体转化率变化 = 渠道贡献之和"""
        channel_sum = sum(c.total_effect for c in channel_decomposition.contributions)
        assert abs(total_change - channel_sum) < 0.0001, f"total={total_change:.6f}, channel_sum={channel_sum:.6f}"

    def test_total_equals_device_sum(self, total_change, device_decomposition):
        """总体转化率变化 = 设备贡献之和"""
        device_sum = sum(c.total_effect for c in device_decomposition.contributions)
        assert abs(total_change - device_sum) < 0.0001, f"total={total_change:.6f}, device_sum={device_sum:.6f}"


# ============================================================
# 测试4: 分组加总一致性
# ============================================================

class TestGroupSumConsistency:
    """分组加总一致性"""

    def test_baseline_channel_visit_sum(self, baseline_cohort, channel_decomposition):
        """基准期渠道访问加总 = 整体"""
        channel_sum = sum(c.baseline_visit for c in channel_decomposition.contributions)
        assert channel_sum == baseline_cohort.visit_sessions

    def test_current_channel_visit_sum(self, current_cohort, channel_decomposition):
        """当前期渠道访问加总 = 整体"""
        channel_sum = sum(c.current_visit for c in channel_decomposition.contributions)
        assert channel_sum == current_cohort.visit_sessions

    def test_baseline_device_visit_sum(self, baseline_cohort, device_decomposition):
        """基准期设备访问加总 = 整体"""
        device_sum = sum(c.baseline_visit for c in device_decomposition.contributions)
        assert device_sum == baseline_cohort.visit_sessions


# ============================================================
# 测试5: 有效订单条件
# ============================================================

class TestOrderConditions:
    """有效订单条件"""

    def test_valid_orders_have_paid_at(self):
        """有效订单都有 paid_at"""
        engine = get_engine()
        with engine.connect() as conn:
            r = conn.execute(text("""
                SELECT COUNT(*) FROM orders
                WHERE order_status IN ('paid', 'completed') AND paid_at IS NULL
            """))
            missing = r.scalar()
        engine.dispose()
        assert missing == 0, f"存在 {missing} 条有效订单缺少 paid_at"


# ============================================================
# 测试6: 维度覆盖
# ============================================================

class TestDimensionCoverage:
    """维度覆盖"""

    def test_channel_coverage(self, channel_decomposition):
        """渠道覆盖完整"""
        expected = {'organic', 'search_ads', 'douyin', 'direct', 'affiliate', 'other'}
        actual = {c.group_name for c in channel_decomposition.contributions}
        assert expected.issubset(actual), f"缺少: {expected - actual}"

    def test_device_coverage(self, device_decomposition):
        """设备覆盖完整"""
        expected = {'app', 'mobile_web', 'pc'}
        actual = {c.group_name for c in device_decomposition.contributions}
        assert expected.issubset(actual), f"缺少: {expected - actual}"


# ============================================================
# 测试7: 当前期转化率低于基准期
# ============================================================

class TestConversionDecline:
    """转化率下降"""

    def test_current_lower_than_baseline(self, baseline_funnel, current_funnel):
        """当前期转化率 < 基准期转化率"""
        assert current_funnel.order_rate < baseline_funnel.order_rate


# ============================================================
# 独立运行入口
# ============================================================

def run_tests():
    """运行所有测试（独立运行时使用）"""
    print("=" * 60)
    print("归因内核测试")
    print("=" * 60)

    # 构建数据
    baseline_cohort = build_cohort(
        start=datetime(2026, 6, 1, tzinfo=timezone.utc),
        end=datetime(2026, 6, 15, tzinfo=timezone.utc),
        period_name="baseline"
    )
    current_cohort = build_cohort(
        start=datetime(2026, 7, 1, tzinfo=timezone.utc),
        end=datetime(2026, 7, 15, tzinfo=timezone.utc),
        period_name="current"
    )

    baseline_funnel = calculate_funnel_from_cohort(baseline_cohort)
    current_funnel = calculate_funnel_from_cohort(current_cohort)
    total_change = current_funnel.order_rate - baseline_funnel.order_rate

    channel_decomposition = decompose_channel(baseline_cohort, current_cohort)
    device_decomposition = decompose_device(baseline_cohort, current_cohort)
    stage_decomposition = decompose_funnel_stages(baseline_cohort, current_cohort)

    tests_passed = 0
    tests_failed = 0

    def check(name, condition, details=""):
        nonlocal tests_passed, tests_failed
        if condition:
            print(f"  [PASS] {name}")
            tests_passed += 1
        else:
            print(f"  [FAIL] {name}: {details}")
            tests_failed += 1

    # 测试1: 漏斗数值
    print("\n[1] 漏斗数值验证")
    check("基准期访问会话 = 3000", baseline_cohort.visit_sessions == 3000, f"actual={baseline_cohort.visit_sessions}")
    check("基准期加购会话 = 904", baseline_cohort.cart_sessions == 904, f"actual={baseline_cohort.cart_sessions}")
    check("基准期下单会话 = 111", baseline_cohort.order_sessions == 111, f"actual={baseline_cohort.order_sessions}")
    check("当前期访问会话 = 3500", current_cohort.visit_sessions == 3500, f"actual={current_cohort.visit_sessions}")
    check("当前期加购会话 = 839", current_cohort.cart_sessions == 839, f"actual={current_cohort.cart_sessions}")
    check("当前期下单会话 = 58", current_cohort.order_sessions == 58, f"actual={current_cohort.order_sessions}")

    # 测试2: 漏斗递减性
    print("\n[2] 漏斗递减性")
    check("基准期: visit >= cart >= order", baseline_cohort.visit_sessions >= baseline_cohort.cart_sessions >= baseline_cohort.order_sessions)
    check("当前期: visit >= cart >= order", current_cohort.visit_sessions >= current_cohort.cart_sessions >= current_cohort.order_sessions)

    # 测试3: 效应加总一致性
    print("\n[3] 效应加总一致性")
    stages_sum = stage_decomposition.stages_sum
    check("总变化 = 阶段贡献之和", abs(total_change - stages_sum) < 0.0001, f"total={total_change:.6f}, sum={stages_sum:.6f}")

    channel_sum = sum(c.total_effect for c in channel_decomposition.contributions)
    check("总变化 = 渠道贡献之和", abs(total_change - channel_sum) < 0.0001, f"total={total_change:.6f}, sum={channel_sum:.6f}")

    device_sum = sum(c.total_effect for c in device_decomposition.contributions)
    check("总变化 = 设备贡献之和", abs(total_change - device_sum) < 0.0001, f"total={total_change:.6f}, sum={device_sum:.6f}")

    # 测试4: 分组加总一致性
    print("\n[4] 分组加总一致性")
    channel_visit_sum = sum(c.baseline_visit for c in channel_decomposition.contributions)
    check("基准期渠道访问加总 = 整体", channel_visit_sum == baseline_cohort.visit_sessions, f"sum={channel_visit_sum}, total={baseline_cohort.visit_sessions}")

    # 测试5: 有效订单条件
    print("\n[5] 有效订单条件")
    engine = get_engine()
    with engine.connect() as conn:
        r = conn.execute(text("SELECT COUNT(*) FROM orders WHERE order_status IN ('paid', 'completed') AND paid_at IS NULL"))
        missing = r.scalar()
    engine.dispose()
    check("有效订单都有 paid_at", missing == 0, f"missing={missing}")

    # 测试6: 维度覆盖
    print("\n[6] 维度覆盖")
    expected_channels = {'organic', 'search_ads', 'douyin', 'direct', 'affiliate', 'other'}
    actual_channels = {c.group_name for c in channel_decomposition.contributions}
    check("渠道覆盖完整", expected_channels.issubset(actual_channels), f"missing={expected_channels - actual_channels}")

    expected_devices = {'app', 'mobile_web', 'pc'}
    actual_devices = {c.group_name for c in device_decomposition.contributions}
    check("设备覆盖完整", expected_devices.issubset(actual_devices), f"missing={expected_devices - actual_devices}")

    # 测试7: 当前期转化率低于基准期
    print("\n[7] 当前期转化率低于基准期")
    check("当前期转化率 < 基准期转化率", current_funnel.order_rate < baseline_funnel.order_rate)

    # 汇总
    print("\n" + "=" * 60)
    print(f"测试结果: {tests_passed} 通过, {tests_failed} 失败")
    print("=" * 60)

    return tests_failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
