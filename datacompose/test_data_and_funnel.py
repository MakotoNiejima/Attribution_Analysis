r"""
数据验收 + 确定性归因内核测试
==========================
1. 数据质量检查
2. 漏斗标准答案计算
3. 多维度拆解
4. 自动化测试断言

使用方式：
    cd D:\dev\归因分析\data_compose
    python test_data_and_funnel.py
"""

import json
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus
from collections import defaultdict
from typing import Dict, List, Any

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text


# 使用项目统一 .env，校验脚本不保留任何数据库凭据。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

# 时间范围
BASELINE_START = "2026-06-01 00:00:00"
BASELINE_END = "2026-06-15 00:00:00"
CURRENT_START = "2026-07-01 00:00:00"
CURRENT_END = "2026-07-15 00:00:00"


def build_url() -> str:
    password = quote_plus(DB_PASSWORD)
    return f"mysql+aiomysql://{DB_USER}:{password}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"


# ============================================================
# 1. 数据质量检查
# ============================================================

async def check_data_quality(engine) -> Dict[str, Any]:
    """
    数据质量检查

    检查项：
    - 主键唯一性
    - 外键完整性
    - 时间合理性
    - 业务规则
    - 漏斗一致性
    """

    results = {
        "check_time": datetime.now(timezone.utc).isoformat(),
        "checks": [],
        "errors": [],
        "warnings": [],
        "passed": True
    }

    async with engine.connect() as conn:

        # ---- 1.1 主键/唯一键检查 ----

        # biz_users.external_user_id
        r = await conn.execute(text(
            "SELECT external_user_id, COUNT(*) as cnt FROM biz_users GROUP BY external_user_id HAVING cnt > 1"
        ))
        duplicates = r.fetchall()
        check = {
            "name": "biz_users.external_user_id 唯一性",
            "status": "PASS" if len(duplicates) == 0 else "FAIL",
            "duplicates": len(duplicates)
        }
        results["checks"].append(check)
        if duplicates:
            results["errors"].append(f"biz_users.external_user_id 存在 {len(duplicates)} 个重复")
            results["passed"] = False

        # products.external_product_id
        r = await conn.execute(text(
            "SELECT external_product_id, COUNT(*) as cnt FROM products GROUP BY external_product_id HAVING cnt > 1"
        ))
        duplicates = r.fetchall()
        check = {
            "name": "products.external_product_id 唯一性",
            "status": "PASS" if len(duplicates) == 0 else "FAIL",
            "duplicates": len(duplicates)
        }
        results["checks"].append(check)
        if duplicates:
            results["errors"].append(f"products.external_product_id 存在 {len(duplicates)} 个重复")
            results["passed"] = False

        # sessions.session_key
        r = await conn.execute(text(
            "SELECT session_key, COUNT(*) as cnt FROM sessions GROUP BY session_key HAVING cnt > 1"
        ))
        duplicates = r.fetchall()
        check = {
            "name": "sessions.session_key 唯一性",
            "status": "PASS" if len(duplicates) == 0 else "FAIL",
            "duplicates": len(duplicates)
        }
        results["checks"].append(check)
        if duplicates:
            results["errors"].append(f"sessions.session_key 存在 {len(duplicates)} 个重复")
            results["passed"] = False

        # visit_events.source_event_id
        r = await conn.execute(text(
            "SELECT source_event_id, COUNT(*) as cnt FROM visit_events GROUP BY source_event_id HAVING cnt > 1"
        ))
        duplicates = r.fetchall()
        check = {
            "name": "visit_events.source_event_id 唯一性",
            "status": "PASS" if len(duplicates) == 0 else "FAIL",
            "duplicates": len(duplicates)
        }
        results["checks"].append(check)
        if duplicates:
            results["errors"].append(f"visit_events.source_event_id 存在 {len(duplicates)} 个重复")
            results["passed"] = False

        # cart_events.source_event_id
        r = await conn.execute(text(
            "SELECT source_event_id, COUNT(*) as cnt FROM cart_events GROUP BY source_event_id HAVING cnt > 1"
        ))
        duplicates = r.fetchall()
        check = {
            "name": "cart_events.source_event_id 唯一性",
            "status": "PASS" if len(duplicates) == 0 else "FAIL",
            "duplicates": len(duplicates)
        }
        results["checks"].append(check)
        if duplicates:
            results["errors"].append(f"cart_events.source_event_id 存在 {len(duplicates)} 个重复")
            results["passed"] = False

        # orders.order_no
        r = await conn.execute(text(
            "SELECT order_no, COUNT(*) as cnt FROM orders GROUP BY order_no HAVING cnt > 1"
        ))
        duplicates = r.fetchall()
        check = {
            "name": "orders.order_no 唯一性",
            "status": "PASS" if len(duplicates) == 0 else "FAIL",
            "duplicates": len(duplicates)
        }
        results["checks"].append(check)
        if duplicates:
            results["errors"].append(f"orders.order_no 存在 {len(duplicates)} 个重复")
            results["passed"] = False

        # business_events.event_code
        r = await conn.execute(text(
            "SELECT event_code, COUNT(*) as cnt FROM business_events GROUP BY event_code HAVING cnt > 1"
        ))
        duplicates = r.fetchall()
        check = {
            "name": "business_events.event_code 唯一性",
            "status": "PASS" if len(duplicates) == 0 else "FAIL",
            "duplicates": len(duplicates)
        }
        results["checks"].append(check)
        if duplicates:
            results["errors"].append(f"business_events.event_code 存在 {len(duplicates)} 个重复")
            results["passed"] = False

        # ---- 1.2 外键完整性 ----

        # cart_events 引用的 session 是否存在
        r = await conn.execute(text("""
            SELECT COUNT(*) FROM cart_events c
            LEFT JOIN sessions s ON c.session_id = s.id
            WHERE s.id IS NULL
        """))
        orphan_count = r.scalar()
        check = {
            "name": "cart_events.session_id 外键完整性",
            "status": "PASS" if orphan_count == 0 else "FAIL",
            "orphan_count": orphan_count
        }
        results["checks"].append(check)
        if orphan_count > 0:
            results["errors"].append(f"cart_events 存在 {orphan_count} 条引用不存在的 session")
            results["passed"] = False

        # orders 引用的 session 是否存在
        r = await conn.execute(text("""
            SELECT COUNT(*) FROM orders o
            LEFT JOIN sessions s ON o.session_id = s.id
            WHERE s.id IS NULL
        """))
        orphan_count = r.scalar()
        check = {
            "name": "orders.session_id 外键完整性",
            "status": "PASS" if orphan_count == 0 else "FAIL",
            "orphan_count": orphan_count
        }
        results["checks"].append(check)
        if orphan_count > 0:
            results["errors"].append(f"orders 存在 {orphan_count} 条引用不存在的 session")
            results["passed"] = False

        # ---- 1.3 时间合理性 ----

        # 事件时间是否晚于会话开始时间
        r = await conn.execute(text("""
            SELECT COUNT(*) FROM visit_events v
            JOIN sessions s ON v.session_id = s.id
            WHERE v.occurred_at < s.started_at
        """))
        time_violations = r.scalar()
        check = {
            "name": "visit_events.occurred_at >= sessions.started_at",
            "status": "PASS" if time_violations == 0 else "FAIL",
            "violations": time_violations
        }
        results["checks"].append(check)
        if time_violations > 0:
            results["errors"].append(f"visit_events 存在 {time_violations} 条事件早于会话开始时间")
            results["passed"] = False

        # ---- 1.4 业务规则 ----

        # 有效订单必须有 paid_at
        r = await conn.execute(text("""
            SELECT COUNT(*) FROM orders
            WHERE order_status IN ('paid', 'completed') AND paid_at IS NULL
        """))
        missing_paid = r.scalar()
        check = {
            "name": "有效订单 paid_at 非空",
            "status": "PASS" if missing_paid == 0 else "FAIL",
            "missing_count": missing_paid
        }
        results["checks"].append(check)
        if missing_paid > 0:
            results["errors"].append(f"存在 {missing_paid} 条有效订单缺少 paid_at")
            results["passed"] = False

        # 金额和数量不能为负
        r = await conn.execute(text("""
            SELECT COUNT(*) FROM orders
            WHERE order_amount < 0 OR unit_price < 0 OR quantity <= 0
        """))
        invalid_amount = r.scalar()
        check = {
            "name": "订单金额和数量合理性",
            "status": "PASS" if invalid_amount == 0 else "FAIL",
            "invalid_count": invalid_amount
        }
        results["checks"].append(check)
        if invalid_amount > 0:
            results["errors"].append(f"存在 {invalid_amount} 条订单金额或数量异常")
            results["passed"] = False

        # ---- 1.5 漏斗一致性 ----

        # 访问会话数 >= 加购会话数 >= 下单会话数
        for period_name, start, end in [("基准期", BASELINE_START, BASELINE_END), ("当前期", CURRENT_START, CURRENT_END)]:
            r = await conn.execute(text(f"""
                SELECT
                    COUNT(DISTINCT s.id) as visit_sessions,
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
            visit, cart, order = row[0], row[1], row[2]

            funnel_valid = visit >= cart >= order
            check = {
                "name": f"{period_name} 漏斗递减性",
                "status": "PASS" if funnel_valid else "FAIL",
                "visit": visit,
                "cart": cart,
                "order": order
            }
            results["checks"].append(check)
            if not funnel_valid:
                results["errors"].append(f"{period_name} 漏斗不满足递减: {visit} -> {cart} -> {order}")
                results["passed"] = False

        # ---- 1.6 机器人流量可排除 ----

        r = await conn.execute(text("SELECT COUNT(*) FROM sessions WHERE is_bot = 1"))
        bot_count = r.scalar()
        check = {
            "name": "机器人流量标记",
            "status": "PASS",
            "bot_count": bot_count,
            "note": f"共有 {bot_count} 条机器人流量，分析时应排除"
        }
        results["checks"].append(check)

        # ---- 1.7 样本量检查 ----

        for period_name, start, end in [("基准期", BASELINE_START, BASELINE_END), ("当前期", CURRENT_START, CURRENT_END)]:
            r = await conn.execute(text(f"""
                SELECT COUNT(*) FROM sessions
                WHERE started_at >= '{start}' AND started_at < '{end}' AND is_bot = 0
            """))
            count = r.scalar()
            sufficient = count >= 100
            check = {
                "name": f"{period_name} 样本量",
                "status": "PASS" if sufficient else "WARNING",
                "count": count,
                "threshold": 100
            }
            results["checks"].append(check)
            if not sufficient:
                results["warnings"].append(f"{period_name} 样本量不足 100，归因结论可能不可靠")

        # ---- 1.8 维度空值检查 ----

        dimension_checks = [
            ("sessions.channel", "channel"),
            ("sessions.device_type", "device_type"),
            ("sessions.region_code", "region_code"),
            ("sessions.user_type_snapshot", "user_type_snapshot"),
        ]

        for table_col, field in dimension_checks:
            table = table_col.split('.')[0]
            r = await conn.execute(text(f"""
                SELECT COUNT(*) FROM {table} WHERE {field} IS NULL OR {field} = ''
            """))
            null_count = r.scalar()
            check = {
                "name": f"{table_col} 空值检查",
                "status": "PASS" if null_count == 0 else "WARNING",
                "null_count": null_count
            }
            results["checks"].append(check)
            if null_count > 0:
                results["warnings"].append(f"{table_col} 存在 {null_count} 个空值")

    return results


# ============================================================
# 2. 漏斗标准答案计算
# ============================================================

async def calculate_funnel_stats(engine) -> Dict[str, Any]:
    """
    计算漏斗标准答案

    返回：
    - 基准期/当前期整体漏斗
    - 各指标计算结果
    - 可作为自动化测试的断言标准
    """

    stats = {
        "calculation_time": datetime.now(timezone.utc).isoformat(),
        "periods": {},
        "changes": {}
    }

    async with engine.connect() as conn:

        for period_name, start, end in [("baseline", BASELINE_START, BASELINE_END), ("current", CURRENT_START, CURRENT_END)]:

            # 整体漏斗
            r = await conn.execute(text(f"""
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

            total = row[0]
            visit = row[1]
            cart = row[2]
            order = row[3]

            # 计算指标
            cart_rate = round(cart / visit, 4) if visit > 0 else 0
            cart_to_order_rate = round(order / cart, 4) if cart > 0 else 0
            order_rate = round(order / visit, 4) if visit > 0 else 0

            stats["periods"][period_name] = {
                "time_range": {"start": start, "end": end},
                "total_sessions": total,
                "visit_sessions": visit,
                "cart_sessions": cart,
                "order_sessions": order,
                "cart_rate": cart_rate,
                "cart_to_order_rate": cart_to_order_rate,
                "order_rate": order_rate
            }

        # 计算变化量
        baseline = stats["periods"]["baseline"]
        current = stats["periods"]["current"]

        stats["changes"] = {
            "visit_sessions": current["visit_sessions"] - baseline["visit_sessions"],
            "cart_sessions": current["cart_sessions"] - baseline["cart_sessions"],
            "order_sessions": current["order_sessions"] - baseline["order_sessions"],
            "cart_rate": round(current["cart_rate"] - baseline["cart_rate"], 4),
            "cart_to_order_rate": round(current["cart_to_order_rate"] - baseline["cart_to_order_rate"], 4),
            "order_rate": round(current["order_rate"] - baseline["order_rate"], 4)
        }

    return stats


# ============================================================
# 3. 多维度拆解
# ============================================================

async def calculate_dimension_breakdown(engine) -> Dict[str, Any]:
    """
    按维度拆解漏斗

    维度：渠道、设备、地区、用户类型
    """

    dimensions = {
        "calculation_time": datetime.now(timezone.utc).isoformat(),
        "by_channel": {},
        "by_device": {},
        "by_region": {},
        "by_user_type": {}
    }

    async with engine.connect() as conn:

        # ---- 按渠道 ----
        for period_name, start, end in [("baseline", BASELINE_START, BASELINE_END), ("current", CURRENT_START, CURRENT_END)]:
            r = await conn.execute(text(f"""
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
                channel = row[0]
                visit, cart, order = row[1], row[2], row[3]
                channel_data[channel] = {
                    "visit_sessions": visit,
                    "cart_sessions": cart,
                    "order_sessions": order,
                    "cart_rate": round(cart / visit, 4) if visit > 0 else 0,
                    "order_rate": round(order / visit, 4) if visit > 0 else 0
                }

            dimensions["by_channel"][period_name] = channel_data

        # ---- 按设备 ----
        for period_name, start, end in [("baseline", BASELINE_START, BASELINE_END), ("current", CURRENT_START, CURRENT_END)]:
            r = await conn.execute(text(f"""
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
                device = row[0]
                visit, cart, order = row[1], row[2], row[3]
                device_data[device] = {
                    "visit_sessions": visit,
                    "cart_sessions": cart,
                    "order_sessions": order,
                    "cart_rate": round(cart / visit, 4) if visit > 0 else 0,
                    "order_rate": round(order / visit, 4) if visit > 0 else 0
                }

            dimensions["by_device"][period_name] = device_data

        # ---- 按地区 ----
        for period_name, start, end in [("baseline", BASELINE_START, BASELINE_END), ("current", CURRENT_START, CURRENT_END)]:
            r = await conn.execute(text(f"""
                SELECT
                    s.region_code,
                    COUNT(DISTINCT s.id) as visit_sessions,
                    COUNT(DISTINCT CASE WHEN c.id IS NOT NULL THEN s.id END) as cart_sessions,
                    COUNT(DISTINCT CASE WHEN o.id IS NOT NULL THEN s.id END) as order_sessions
                FROM sessions s
                LEFT JOIN visit_events v ON v.session_id = s.id
                LEFT JOIN cart_events c ON c.session_id = s.id AND c.action = 'add'
                LEFT JOIN orders o ON o.session_id = s.id AND o.order_status IN ('paid', 'completed')
                WHERE s.started_at >= '{start}' AND s.started_at < '{end}'
                AND s.is_bot = 0
                GROUP BY s.region_code
            """))

            region_data = {}
            for row in r.fetchall():
                region = row[0] or "unknown"
                visit, cart, order = row[1], row[2], row[3]
                region_data[region] = {
                    "visit_sessions": visit,
                    "cart_sessions": cart,
                    "order_sessions": order,
                    "cart_rate": round(cart / visit, 4) if visit > 0 else 0,
                    "order_rate": round(order / visit, 4) if visit > 0 else 0
                }

            dimensions["by_region"][period_name] = region_data

        # ---- 按用户类型 ----
        for period_name, start, end in [("baseline", BASELINE_START, BASELINE_END), ("current", CURRENT_START, CURRENT_END)]:
            r = await conn.execute(text(f"""
                SELECT
                    s.user_type_snapshot,
                    COUNT(DISTINCT s.id) as visit_sessions,
                    COUNT(DISTINCT CASE WHEN c.id IS NOT NULL THEN s.id END) as cart_sessions,
                    COUNT(DISTINCT CASE WHEN o.id IS NOT NULL THEN s.id END) as order_sessions
                FROM sessions s
                LEFT JOIN visit_events v ON v.session_id = s.id
                LEFT JOIN cart_events c ON c.session_id = s.id AND c.action = 'add'
                LEFT JOIN orders o ON o.session_id = s.id AND o.order_status IN ('paid', 'completed')
                WHERE s.started_at >= '{start}' AND s.started_at < '{end}'
                AND s.is_bot = 0
                GROUP BY s.user_type_snapshot
            """))

            user_type_data = {}
            for row in r.fetchall():
                user_type = row[0]
                visit, cart, order = row[1], row[2], row[3]
                user_type_data[user_type] = {
                    "visit_sessions": visit,
                    "cart_sessions": cart,
                    "order_sessions": order,
                    "cart_rate": round(cart / visit, 4) if visit > 0 else 0,
                    "order_rate": round(order / visit, 4) if visit > 0 else 0
                }

            dimensions["by_user_type"][period_name] = user_type_data

    return dimensions


# ============================================================
# 4. 自动化测试断言
# ============================================================

def run_assertions(funnel_stats: Dict, dimension_stats: Dict) -> Dict[str, Any]:
    """
    运行自动化测试断言

    基于计算结果验证归因逻辑的正确性
    """

    test_results = {
        "test_time": datetime.now(timezone.utc).isoformat(),
        "tests": [],
        "passed": 0,
        "failed": 0,
        "total": 0
    }

    baseline = funnel_stats["periods"]["baseline"]
    current = funnel_stats["periods"]["current"]
    changes = funnel_stats["changes"]

    # ---- 测试1: 漏斗递减性 ----

    def add_test(name, condition, details=""):
        test_results["total"] += 1
        if condition:
            test_results["tests"].append({"name": name, "status": "PASS"})
            test_results["passed"] += 1
        else:
            test_results["tests"].append({"name": name, "status": "FAIL", "details": details})
            test_results["failed"] += 1

    add_test(
        "基准期漏斗递减: visit >= cart >= order",
        baseline["visit_sessions"] >= baseline["cart_sessions"] >= baseline["order_sessions"],
        f"visit={baseline['visit_sessions']}, cart={baseline['cart_sessions']}, order={baseline['order_sessions']}"
    )

    add_test(
        "当前期漏斗递减: visit >= cart >= order",
        current["visit_sessions"] >= current["cart_sessions"] >= current["order_sessions"],
        f"visit={current['visit_sessions']}, cart={current['cart_sessions']}, order={current['order_sessions']}"
    )

    # ---- 测试2: 指标计算正确性 ----

    # 加购率 = 加购会话 / 访问会话
    expected_cart_rate = round(baseline["cart_sessions"] / baseline["visit_sessions"], 4) if baseline["visit_sessions"] > 0 else 0
    add_test(
        "基准期加购率计算正确",
        abs(baseline["cart_rate"] - expected_cart_rate) < 0.0001,
        f"expected={expected_cart_rate}, actual={baseline['cart_rate']}"
    )

    # 加购后下单率 = 下单会话 / 加购会话
    expected_cart_to_order = round(baseline["order_sessions"] / baseline["cart_sessions"], 4) if baseline["cart_sessions"] > 0 else 0
    add_test(
        "基准期加购后下单率计算正确",
        abs(baseline["cart_to_order_rate"] - expected_cart_to_order) < 0.0001,
        f"expected={expected_cart_to_order}, actual={baseline['cart_to_order_rate']}"
    )

    # 下单转化率 = 下单会话 / 访问会话
    expected_order_rate = round(baseline["order_sessions"] / baseline["visit_sessions"], 4) if baseline["visit_sessions"] > 0 else 0
    add_test(
        "基准期下单转化率计算正确",
        abs(baseline["order_rate"] - expected_order_rate) < 0.0001,
        f"expected={expected_order_rate}, actual={baseline['order_rate']}"
    )

    # ---- 测试3: 漏斗公式一致性 ----
    # 加购率 × 加购后下单率 = 下单转化率

    expected_product = round(baseline["cart_rate"] * baseline["cart_to_order_rate"], 4)
    add_test(
        "基准期漏斗公式: cart_rate * cart_to_order_rate = order_rate",
        abs(baseline["order_rate"] - expected_product) < 0.01,  # 允许小误差
        f"cart_rate={baseline['cart_rate']} * cart_to_order_rate={baseline['cart_to_order_rate']} = {expected_product}, order_rate={baseline['order_rate']}"
    )

    # ---- 测试4: 当前期漏斗公式一致性 ----

    expected_product_current = round(current["cart_rate"] * current["cart_to_order_rate"], 4)
    add_test(
        "当前期漏斗公式: cart_rate * cart_to_order_rate = order_rate",
        abs(current["order_rate"] - expected_product_current) < 0.01,
        f"cart_rate={current['cart_rate']} * cart_to_order_rate={current['cart_to_order_rate']} = {expected_product_current}, order_rate={current['order_rate']}"
    )

    # ---- 测试5: 维度数据完整性 ----

    # 渠道维度应该覆盖所有渠道
    expected_channels = {'organic', 'search_ads', 'douyin', 'direct', 'affiliate', 'other'}
    actual_channels = set(dimension_stats["by_channel"]["baseline"].keys())
    add_test(
        "渠道维度覆盖完整",
        expected_channels.issubset(actual_channels),
        f"missing={expected_channels - actual_channels}"
    )

    # 设备维度应该覆盖所有设备
    expected_devices = {'app', 'mobile_web', 'pc'}
    actual_devices = set(dimension_stats["by_device"]["baseline"].keys())
    add_test(
        "设备维度覆盖完整",
        expected_devices.issubset(actual_devices),
        f"missing={expected_devices - actual_devices}"
    )

    # ---- 测试6: 维度拆解求和等于整体 ----

    # 基准期渠道访问会话求和应该等于整体
    channel_visit_sum = sum(v["visit_sessions"] for v in dimension_stats["by_channel"]["baseline"].values())
    add_test(
        "基准期渠道访问会话求和等于整体",
        channel_visit_sum == baseline["visit_sessions"],
        f"sum={channel_visit_sum}, total={baseline['visit_sessions']}"
    )

    # ---- 测试7: 当前期转化率下降 ----

    add_test(
        "当前期下单转化率低于基准期",
        current["order_rate"] < baseline["order_rate"],
        f"baseline={baseline['order_rate']}, current={current['order_rate']}"
    )

    # ---- 测试8: 样本量充足 ----

    add_test(
        "基准期样本量 >= 100",
        baseline["visit_sessions"] >= 100,
        f"visit_sessions={baseline['visit_sessions']}"
    )

    add_test(
        "当前期样本量 >= 100",
        current["visit_sessions"] >= 100,
        f"visit_sessions={current['visit_sessions']}"
    )

    return test_results


# ============================================================
# 5. 主函数
# ============================================================

async def main():
    """主函数"""

    print("=" * 60)
    print("数据验收 + 确定性归因内核测试")
    print("=" * 60)

    url = build_url()
    engine = create_async_engine(url, echo=False)

    # ---- 1. 数据质量检查 ----
    print("\n[1/4] 数据质量检查...")
    quality_report = await check_data_quality(engine)

    print(f"  检查项: {len(quality_report['checks'])}")
    print(f"  错误: {len(quality_report['errors'])}")
    print(f"  警告: {len(quality_report['warnings'])}")

    if quality_report["passed"]:
        print("  结果: PASS")
    else:
        print("  结果: FAIL")
        for err in quality_report["errors"]:
            print(f"    - {err}")

    # ---- 2. 漏斗标准答案 ----
    print("\n[2/4] 计算漏斗标准答案...")
    funnel_stats = await calculate_funnel_stats(engine)

    print("\n  基准期:")
    p = funnel_stats["periods"]["baseline"]
    print(f"    访问会话: {p['visit_sessions']}")
    print(f"    加购会话: {p['cart_sessions']}")
    print(f"    下单会话: {p['order_sessions']}")
    print(f"    加购率: {p['cart_rate']*100:.2f}%")
    print(f"    加购后下单率: {p['cart_to_order_rate']*100:.2f}%")
    print(f"    下单转化率: {p['order_rate']*100:.2f}%")

    print("\n  当前期:")
    p = funnel_stats["periods"]["current"]
    print(f"    访问会话: {p['visit_sessions']}")
    print(f"    加购会话: {p['cart_sessions']}")
    print(f"    下单会话: {p['order_sessions']}")
    print(f"    加购率: {p['cart_rate']*100:.2f}%")
    print(f"    加购后下单率: {p['cart_to_order_rate']*100:.2f}%")
    print(f"    下单转化率: {p['order_rate']*100:.2f}%")

    print("\n  变化:")
    c = funnel_stats["changes"]
    print(f"    下单转化率变化: {c['order_rate']*100:+.2f}%")

    # ---- 3. 多维度拆解 ----
    print("\n[3/4] 多维度拆解...")
    dimension_stats = await calculate_dimension_breakdown(engine)

    print("\n  渠道转化率对比:")
    print(f"  {'渠道':<15} {'基准期':>10} {'当前期':>10} {'变化':>10}")
    print("  " + "-" * 48)
    for ch in ['organic', 'search_ads', 'douyin', 'direct', 'affiliate', 'other']:
        b = dimension_stats["by_channel"]["baseline"].get(ch, {}).get("order_rate", 0)
        c = dimension_stats["by_channel"]["current"].get(ch, {}).get("order_rate", 0)
        print(f"  {ch:<15} {b*100:>9.2f}% {c*100:>9.2f}% {(c-b)*100:>+9.2f}%")

    print("\n  设备转化率对比:")
    print(f"  {'设备':<15} {'基准期':>10} {'当前期':>10} {'变化':>10}")
    print("  " + "-" * 48)
    for dev in ['app', 'mobile_web', 'pc']:
        b = dimension_stats["by_device"]["baseline"].get(dev, {}).get("order_rate", 0)
        c = dimension_stats["by_device"]["current"].get(dev, {}).get("order_rate", 0)
        print(f"  {dev:<15} {b*100:>9.2f}% {c*100:>9.2f}% {(c-b)*100:>+9.2f}%")

    # ---- 4. 自动化测试 ----
    print("\n[4/4] 运行自动化测试...")
    test_results = run_assertions(funnel_stats, dimension_stats)

    print(f"\n  测试总数: {test_results['total']}")
    print(f"  通过: {test_results['passed']}")
    print(f"  失败: {test_results['failed']}")

    if test_results["failed"] > 0:
        print("\n  失败的测试:")
        for t in test_results["tests"]:
            if t["status"] == "FAIL":
                print(f"    - {t['name']}: {t.get('details', '')}")

    # ---- 保存报告 ----
    report = {
        "quality_check": quality_report,
        "funnel_stats": funnel_stats,
        "dimension_breakdown": dimension_stats,
        "test_results": test_results
    }

    report_path = "test_report.json"
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, default=str, ensure_ascii=False)
    print(f"\n  完整报告已保存到: {report_path}")

    # ---- 保存标准答案（用于后续断言）----
    standard_answer = {
        "baseline": funnel_stats["periods"]["baseline"],
        "current": funnel_stats["periods"]["current"],
        "changes": funnel_stats["changes"],
        "by_channel": dimension_stats["by_channel"],
        "by_device": dimension_stats["by_device"]
    }

    answer_path = "standard_answer.json"
    with open(answer_path, 'w', encoding='utf-8') as f:
        json.dump(standard_answer, f, indent=2, default=str, ensure_ascii=False)
    print(f"  标准答案已保存到: {answer_path}")

    await engine.dispose()

    # 返回是否全部通过
    return quality_report["passed"] and test_results["failed"] == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
