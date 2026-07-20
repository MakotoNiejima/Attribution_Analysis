r"""
数据验收 + 确定性归因内核测试 (pytest 格式)
==========================================

使用方式：
    cd D:\dev\归因分析\datacompose
    pytest test_funnel.py -v
"""

import json
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus
from typing import Dict, Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


# 使用项目统一 .env，测试脚本不保留任何数据库凭据。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

# 时间范围
BASELINE_START = "2026-06-01 00:00:00"
BASELINE_END = "2026-06-15 00:00:00"
CURRENT_START = "2026-07-01 00:00:00"
CURRENT_END = "2026-07-15 00:00:00"


def build_sync_url() -> str:
    """构建同步数据库 URL"""
    password = quote_plus(DB_PASSWORD)
    return f"mysql+pymysql://{DB_USER}:{password}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def db_engine():
    """创建同步数据库引擎"""
    url = build_sync_url()
    engine = create_engine(url, echo=False)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def funnel_data(db_engine):
    """计算漏斗统计数据"""

    stats = {"periods": {}, "changes": {}}

    with db_engine.connect() as conn:
        for period_name, start, end in [
            ("baseline", BASELINE_START, BASELINE_END),
            ("current", CURRENT_START, CURRENT_END)
        ]:
            r = conn.execute(text(f"""
                SELECT
                    COUNT(DISTINCT s.id) as total_sessions,
                    COUNT(DISTINCT CASE WHEN v.id IS NOT NULL THEN s.id END) as visit_sessions,
                    COUNT(DISTINCT CASE WHEN c.id IS NOT NULL THEN s.id END) as cart_sessions,
                    COUNT(DISTINCT CASE WHEN o.id IS NOT NULL THEN s.id END) as order_sessions
                FROM sessions s
                LEFT JOIN visit_events v ON v.session_id = s.id
                LEFT JOIN cart_events c ON c.session_id = s.id AND c.action = 'add'
                LEFT JOIN orders o ON o.session_id = s.id AND o.order_status IN ('paid', 'completed')
                WHERE s.started_at >= '{start}' AND s.started_at < '{end}'
                AND s.is_bot = 0
            """))
            row = r.fetchone()

            visit, cart, order = row[1], row[2], row[3]

            stats["periods"][period_name] = {
                "visit_sessions": visit,
                "cart_sessions": cart,
                "order_sessions": order,
                "cart_rate": round(cart / visit, 4) if visit > 0 else 0,
                "cart_to_order_rate": round(order / cart, 4) if cart > 0 else 0,
                "order_rate": round(order / visit, 4) if visit > 0 else 0
            }

        baseline = stats["periods"]["baseline"]
        current = stats["periods"]["current"]
        stats["changes"] = {
            "order_rate": round(current["order_rate"] - baseline["order_rate"], 4)
        }

    return stats


@pytest.fixture(scope="module")
def dimension_data(db_engine):
    """计算维度拆解数据"""

    dimensions = {"by_channel": {}, "by_device": {}}

    with db_engine.connect() as conn:
        # 按渠道
        for period_name, start, end in [
            ("baseline", BASELINE_START, BASELINE_END),
            ("current", CURRENT_START, CURRENT_END)
        ]:
            r = conn.execute(text(f"""
                SELECT
                    s.channel,
                    COUNT(DISTINCT s.id) as visit_sessions,
                    COUNT(DISTINCT CASE WHEN c.id IS NOT NULL THEN s.id END) as cart_sessions,
                    COUNT(DISTINCT CASE WHEN o.id IS NOT NULL THEN s.id END) as order_sessions
                FROM sessions s
                LEFT JOIN visit_events v ON v.session_id = s.id
                LEFT JOIN cart_events c ON c.session_id = s.id AND c.action = 'add'
                LEFT JOIN orders o ON o.session_id = s.id AND o.order_status IN ('paid', 'completed')
                WHERE s.started_at >= '{start}' AND s.started_at < '{end}'
                AND s.is_bot = 0
                GROUP BY s.channel
            """))

            channel_data = {}
            for row in r.fetchall():
                channel, visit, cart, order = row[0], row[1], row[2], row[3]
                channel_data[channel] = {
                    "visit_sessions": visit,
                    "cart_sessions": cart,
                    "order_sessions": order,
                    "order_rate": round(order / visit, 4) if visit > 0 else 0
                }

            dimensions["by_channel"][period_name] = channel_data

        # 按设备
        for period_name, start, end in [
            ("baseline", BASELINE_START, BASELINE_END),
            ("current", CURRENT_START, CURRENT_END)
        ]:
            r = conn.execute(text(f"""
                SELECT
                    s.device_type,
                    COUNT(DISTINCT s.id) as visit_sessions,
                    COUNT(DISTINCT CASE WHEN c.id IS NOT NULL THEN s.id END) as cart_sessions,
                    COUNT(DISTINCT CASE WHEN o.id IS NOT NULL THEN s.id END) as order_sessions
                FROM sessions s
                LEFT JOIN visit_events v ON v.session_id = s.id
                LEFT JOIN cart_events c ON c.session_id = s.id AND c.action = 'add'
                LEFT JOIN orders o ON o.session_id = s.id AND o.order_status IN ('paid', 'completed')
                WHERE s.started_at >= '{start}' AND s.started_at < '{end}'
                AND s.is_bot = 0
                GROUP BY s.device_type
            """))

            device_data = {}
            for row in r.fetchall():
                device, visit, cart, order = row[0], row[1], row[2], row[3]
                device_data[device] = {
                    "visit_sessions": visit,
                    "cart_sessions": cart,
                    "order_sessions": order,
                    "order_rate": round(order / visit, 4) if visit > 0 else 0
                }

            dimensions["by_device"][period_name] = device_data

    return dimensions


# ============================================================
# 数据质量测试
# ============================================================

class TestDataQuality:
    """数据质量检查"""

    def test_biz_users_external_id_unique(self, db_engine):
        """biz_users.external_user_id 唯一性"""
        with db_engine.connect() as conn:
            r = conn.execute(text(
                "SELECT external_user_id, COUNT(*) as cnt FROM biz_users GROUP BY external_user_id HAVING cnt > 1"
            ))
            duplicates = r.fetchall()
            assert len(duplicates) == 0, f"存在 {len(duplicates)} 个重复的 external_user_id"

    def test_sessions_session_key_unique(self, db_engine):
        """sessions.session_key 唯一性"""
        with db_engine.connect() as conn:
            r = conn.execute(text(
                "SELECT session_key, COUNT(*) as cnt FROM sessions GROUP BY session_key HAVING cnt > 1"
            ))
            duplicates = r.fetchall()
            assert len(duplicates) == 0, f"存在 {len(duplicates)} 个重复的 session_key"

    def test_orders_order_no_unique(self, db_engine):
        """orders.order_no 唯一性"""
        with db_engine.connect() as conn:
            r = conn.execute(text(
                "SELECT order_no, COUNT(*) as cnt FROM orders GROUP BY order_no HAVING cnt > 1"
            ))
            duplicates = r.fetchall()
            assert len(duplicates) == 0, f"存在 {len(duplicates)} 个重复的 order_no"

    def test_cart_events_session_fk(self, db_engine):
        """cart_events 引用的 session 必须存在"""
        with db_engine.connect() as conn:
            r = conn.execute(text("""
                SELECT COUNT(*) FROM cart_events c
                LEFT JOIN sessions s ON c.session_id = s.id
                WHERE s.id IS NULL
            """))
            orphan_count = r.scalar()
            assert orphan_count == 0, f"存在 {orphan_count} 条孤立的 cart_events"

    def test_orders_session_fk(self, db_engine):
        """orders 引用的 session 必须存在"""
        with db_engine.connect() as conn:
            r = conn.execute(text("""
                SELECT COUNT(*) FROM orders o
                LEFT JOIN sessions s ON o.session_id = s.id
                WHERE s.id IS NULL
            """))
            orphan_count = r.scalar()
            assert orphan_count == 0, f"存在 {orphan_count} 条孤立的 orders"

    def test_valid_orders_have_paid_at(self, db_engine):
        """有效订单必须有 paid_at"""
        with db_engine.connect() as conn:
            r = conn.execute(text("""
                SELECT COUNT(*) FROM orders
                WHERE order_status IN ('paid', 'completed') AND paid_at IS NULL
            """))
            missing = r.scalar()
            assert missing == 0, f"存在 {missing} 条有效订单缺少 paid_at"

    def test_order_amount_valid(self, db_engine):
        """订单金额不能为负"""
        with db_engine.connect() as conn:
            r = conn.execute(text("""
                SELECT COUNT(*) FROM orders
                WHERE order_amount < 0 OR unit_price < 0 OR quantity <= 0
            """))
            invalid = r.scalar()
            assert invalid == 0, f"存在 {invalid} 条订单金额或数量异常"

    def test_baseline_sample_size(self, db_engine):
        """基准期样本量充足"""
        with db_engine.connect() as conn:
            r = conn.execute(text(f"""
                SELECT COUNT(*) FROM sessions
                WHERE started_at >= '{BASELINE_START}' AND started_at < '{BASELINE_END}'
                AND is_bot = 0
            """))
            count = r.scalar()
            assert count >= 100, f"基准期样本量不足: {count}"

    def test_current_sample_size(self, db_engine):
        """当前期样本量充足"""
        with db_engine.connect() as conn:
            r = conn.execute(text(f"""
                SELECT COUNT(*) FROM sessions
                WHERE started_at >= '{CURRENT_START}' AND started_at < '{CURRENT_END}'
                AND is_bot = 0
            """))
            count = r.scalar()
            assert count >= 100, f"当前期样本量不足: {count}"

    def test_no_null_channels(self, db_engine):
        """渠道字段无空值"""
        with db_engine.connect() as conn:
            r = conn.execute(text("SELECT COUNT(*) FROM sessions WHERE channel IS NULL OR channel = ''"))
            null_count = r.scalar()
            assert null_count == 0, f"存在 {null_count} 个空渠道"

    def test_no_null_device_types(self, db_engine):
        """设备类型字段无空值"""
        with db_engine.connect() as conn:
            r = conn.execute(text("SELECT COUNT(*) FROM sessions WHERE device_type IS NULL OR device_type = ''"))
            null_count = r.scalar()
            assert null_count == 0, f"存在 {null_count} 个空设备类型"


# ============================================================
# 漏斗计算测试
# ============================================================

class TestFunnelLogic:
    """漏斗逻辑测试"""

    def test_baseline_funnel_decreasing(self, funnel_data):
        """基准期漏斗递减: visit >= cart >= order"""
        p = funnel_data["periods"]["baseline"]
        assert p["visit_sessions"] >= p["cart_sessions"] >= p["order_sessions"], \
            f"漏斗不递减: {p['visit_sessions']} -> {p['cart_sessions']} -> {p['order_sessions']}"

    def test_current_funnel_decreasing(self, funnel_data):
        """当前期漏斗递减: visit >= cart >= order"""
        p = funnel_data["periods"]["current"]
        assert p["visit_sessions"] >= p["cart_sessions"] >= p["order_sessions"], \
            f"漏斗不递减: {p['visit_sessions']} -> {p['cart_sessions']} -> {p['order_sessions']}"

    def test_baseline_cart_rate_correct(self, funnel_data):
        """基准期加购率计算正确"""
        p = funnel_data["periods"]["baseline"]
        expected = round(p["cart_sessions"] / p["visit_sessions"], 4) if p["visit_sessions"] > 0 else 0
        assert abs(p["cart_rate"] - expected) < 0.0001, \
            f"加购率计算错误: expected={expected}, actual={p['cart_rate']}"

    def test_baseline_cart_to_order_rate_correct(self, funnel_data):
        """基准期加购后下单率计算正确"""
        p = funnel_data["periods"]["baseline"]
        expected = round(p["order_sessions"] / p["cart_sessions"], 4) if p["cart_sessions"] > 0 else 0
        assert abs(p["cart_to_order_rate"] - expected) < 0.0001, \
            f"加购后下单率计算错误: expected={expected}, actual={p['cart_to_order_rate']}"

    def test_baseline_order_rate_correct(self, funnel_data):
        """基准期下单转化率计算正确"""
        p = funnel_data["periods"]["baseline"]
        expected = round(p["order_sessions"] / p["visit_sessions"], 4) if p["visit_sessions"] > 0 else 0
        assert abs(p["order_rate"] - expected) < 0.0001, \
            f"下单转化率计算错误: expected={expected}, actual={p['order_rate']}"

    def test_baseline_funnel_formula(self, funnel_data):
        """基准期漏斗公式: cart_rate * cart_to_order_rate ≈ order_rate"""
        p = funnel_data["periods"]["baseline"]
        expected = round(p["cart_rate"] * p["cart_to_order_rate"], 4)
        assert abs(p["order_rate"] - expected) < 0.01, \
            f"漏斗公式不成立: {p['cart_rate']} * {p['cart_to_order_rate']} = {expected} != {p['order_rate']}"

    def test_current_order_rate_lower(self, funnel_data):
        """当前期转化率低于基准期"""
        baseline = funnel_data["periods"]["baseline"]
        current = funnel_data["periods"]["current"]
        assert current["order_rate"] < baseline["order_rate"], \
            f"当前期转化率应低于基准期: {current['order_rate']} >= {baseline['order_rate']}"


# ============================================================
# 维度拆解测试
# ============================================================

class TestDimensionBreakdown:
    """维度拆解测试"""

    def test_channel_coverage(self, dimension_data):
        """渠道维度覆盖完整"""
        expected = {'organic', 'search_ads', 'douyin', 'direct', 'affiliate', 'other'}
        actual = set(dimension_data["by_channel"]["baseline"].keys())
        assert expected.issubset(actual), f"缺少渠道: {expected - actual}"

    def test_device_coverage(self, dimension_data):
        """设备维度覆盖完整"""
        expected = {'app', 'mobile_web', 'pc'}
        actual = set(dimension_data["by_device"]["baseline"].keys())
        assert expected.issubset(actual), f"缺少设备: {expected - actual}"

    def test_channel_sum_equals_total(self, dimension_data, funnel_data):
        """渠道访问会话求和等于整体"""
        channel_sum = sum(
            v["visit_sessions"]
            for v in dimension_data["by_channel"]["baseline"].values()
        )
        total = funnel_data["periods"]["baseline"]["visit_sessions"]
        assert channel_sum == total, f"渠道求和 {channel_sum} != 整体 {total}"

    def test_douyin_conversion_dropped(self, dimension_data):
        """抖音渠道转化率下降"""
        baseline = dimension_data["by_channel"]["baseline"].get("douyin", {}).get("order_rate", 0)
        current = dimension_data["by_channel"]["current"].get("douyin", {}).get("order_rate", 0)
        print(baseline, current)
        assert current < baseline, f"抖音转化率应下降: baseline={baseline}, current={current}"

    def test_mobile_web_conversion_dropped(self, dimension_data):
        """移动端转化率下降"""
        baseline = dimension_data["by_device"]["baseline"].get("mobile_web", {}).get("order_rate", 0)
        current = dimension_data["by_device"]["current"].get("mobile_web", {}).get("order_rate", 0)
        assert current < baseline, f"移动端转化率应下降: baseline={baseline}, current={current}"


# ============================================================
# 标准答案输出
# ============================================================

class TestStandardAnswer:
    """输出标准答案"""

    def test_save_standard_answer(self, funnel_data, dimension_data):
        """保存标准答案到文件"""
        answer = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "baseline": funnel_data["periods"]["baseline"],
            "current": funnel_data["periods"]["current"],
            "changes": funnel_data["changes"],
            "by_channel": dimension_data["by_channel"],
            "by_device": dimension_data["by_device"]
        }

        with open("standard_answer.json", "w", encoding="utf-8") as f:
            json.dump(answer, f, indent=2, ensure_ascii=False)

        assert True  # 总是通过，主要是为了生成文件
