"""
预期统计结果
===========
计算基准期和当前期的预期统计数据，用于验证归因系统是否正确。

使用方法：
    python 04_expected_stats.py

输出：
    - 基准期/当前期整体漏斗
    - 按渠道拆解
    - 按设备拆解
    - 按地区拆解
    - 按商品拆解
    - 预期的归因结论
"""

import csv
import json
import os
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Tuple
from collections import defaultdict


# 时间范围
BASELINE_START = datetime(2026, 6, 1, tzinfo=timezone.utc)
BASELINE_END = datetime(2026, 6, 15, tzinfo=timezone.utc)
CURRENT_START = datetime(2026, 7, 1, tzinfo=timezone.utc)
CURRENT_END = datetime(2026, 7, 15, tzinfo=timezone.utc)


def load_csv(filepath: str) -> List[Dict]:
    """加载CSV文件"""
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # 转换时间字段
    time_fields = ['registered_at', 'started_at', 'ended_at', 'occurred_at', 'created_at', 'paid_at', 'completed_at', 'cancelled_at']
    for row in rows:
        for field in time_fields:
            if field in row and row[field]:
                try:
                    row[field] = datetime.fromisoformat(row[field].replace('Z', '+00:00'))
                except:
                    pass

    return rows


def calculate_funnel_stats(
    sessions: List[Dict],
    visits: List[Dict],
    carts: List[Dict],
    orders: List[Dict],
    period_start: datetime,
    period_end: datetime,
    group_by: str = None
) -> Dict:
    """
    计算漏斗统计

    Args:
        sessions: 会话列表
        visits: 访问事件列表
        carts: 加购事件列表
        orders: 订单列表
        period_start: 周期开始
        period_end: 周期结束
        group_by: 分组字段（channel/device_type/region_code/None）

    Returns:
        统计结果
    """

    # 筛选周期内的会话
    period_sessions = [
        s for s in sessions
        if period_start <= s['started_at'] < period_end
    ]

    # 建立会话索引
    session_keys = {s['session_key'] for s in period_sessions}

    # 筛选相关事件
    period_visits = [v for v in visits if v.get('session_key') in session_keys]
    period_carts = [c for c in carts if c.get('session_key') in session_keys and c.get('action') == 'add']
    period_orders = [o for o in orders if o.get('session_key') in session_keys and o.get('order_status') in ('paid', 'completed')]

    # 计算各阶段会话集合
    visit_sessions = {v['session_key'] for v in period_visits}
    cart_sessions = {c['session_key'] for c in period_carts}
    order_sessions = {o['session_key'] for o in period_orders}

    if group_by is None:
        # 整体统计
        total = len(period_sessions)
        visits_count = len(visit_sessions)
        carts_count = len(cart_sessions)
        orders_count = len(order_sessions)

        return {
            'total_sessions': total,
            'visit_sessions': visits_count,
            'cart_sessions': carts_count,
            'order_sessions': orders_count,
            'cart_rate': round(carts_count / total, 4) if total > 0 else 0,
            'order_rate': round(orders_count / total, 4) if total > 0 else 0,
            'cart_to_order_rate': round(orders_count / carts_count, 4) if carts_count > 0 else 0
        }
    else:
        # 按维度分组
        groups = defaultdict(lambda: {'sessions': set(), 'visits': set(), 'carts': set(), 'orders': set()})

        for s in period_sessions:
            key = s.get(group_by, 'unknown')
            groups[key]['sessions'].add(s['session_key'])

        for v in period_visits:
            key = next((s.get(group_by, 'unknown') for s in period_sessions if s['session_key'] == v['session_key']), 'unknown')
            groups[key]['visits'].add(v['session_key'])

        for c in period_carts:
            key = next((s.get(group_by, 'unknown') for s in period_sessions if s['session_key'] == c['session_key']), 'unknown')
            groups[key]['carts'].add(c['session_key'])

        for o in period_orders:
            key = next((s.get(group_by, 'unknown') for s in period_sessions if s['session_key'] == o['session_key']), 'unknown')
            groups[key]['orders'].add(o['session_key'])

        result = {}
        for key, data in groups.items():
            total = len(data['sessions'])
            visits_count = len(data['visits'])
            carts_count = len(data['carts'])
            orders_count = len(data['orders'])

            result[key] = {
                'total_sessions': total,
                'visit_sessions': visits_count,
                'cart_sessions': carts_count,
                'order_sessions': orders_count,
                'cart_rate': round(carts_count / total, 4) if total > 0 else 0,
                'order_rate': round(orders_count / total, 4) if total > 0 else 0,
                'cart_to_order_rate': round(orders_count / carts_count, 4) if carts_count > 0 else 0
            }

        return result


def calculate_contribution(
    baseline_groups: Dict,
    current_groups: Dict,
    metric: str = 'order_sessions'
) -> List[Dict]:
    """
    计算维度贡献度

    Args:
        baseline_groups: 基准期分组统计
        current_groups: 当前期分组统计
        metric: 计算的指标

    Returns:
        贡献度列表
    """

    # 计算整体变化
    baseline_total = sum(g.get(metric, 0) for g in baseline_groups.values())
    current_total = sum(g.get(metric, 0) for g in current_groups.values())
    total_change = current_total - baseline_total

    contributions = []

    for key in set(list(baseline_groups.keys()) + list(current_groups.keys())):
        baseline_val = baseline_groups.get(key, {}).get(metric, 0)
        current_val = current_groups.get(key, {}).get(metric, 0)
        change = current_val - baseline_val

        contribution = {
            'group': key,
            'baseline': baseline_val,
            'current': current_val,
            'change': change,
            'change_rate': round(change / baseline_val, 4) if baseline_val > 0 else 0,
            'contribution': round(change / total_change, 4) if total_change != 0 else 0
        }
        contributions.append(contribution)

    # 按贡献度排序
    contributions.sort(key=lambda x: abs(x['contribution']), reverse=True)

    return contributions


def format_percentage(value: float) -> str:
    """格式化百分比"""
    return f"{value * 100:.2f}%"


def format_number(value: int) -> str:
    """格式化数字"""
    return f"{value:,}"


def generate_report(sessions, visits, carts, orders) -> str:
    """生成完整报告"""

    lines = []
    lines.append("=" * 70)
    lines.append("预期统计结果报告")
    lines.append("=" * 70)
    lines.append(f"基准期: {BASELINE_START.strftime('%Y-%m-%d')} ~ {BASELINE_END.strftime('%Y-%m-%d')}")
    lines.append(f"当前期: {CURRENT_START.strftime('%Y-%m-%d')} ~ {CURRENT_END.strftime('%Y-%m-%d')}")
    lines.append("")

    # 1. 整体漏斗
    lines.append("【1. 整体漏斗】")
    lines.append("-" * 50)

    baseline_funnel = calculate_funnel_stats(sessions, visits, carts, orders, BASELINE_START, BASELINE_END)
    current_funnel = calculate_funnel_stats(sessions, visits, carts, orders, CURRENT_START, CURRENT_END)

    lines.append(f"{'指标':<20} {'基准期':>12} {'当前期':>12} {'变化':>12} {'变化率':>10}")
    lines.append("-" * 70)

    for metric, label in [
        ('total_sessions', '总会话数'),
        ('visit_sessions', '访问会话'),
        ('cart_sessions', '加购会话'),
        ('order_sessions', '下单会话')
    ]:
        baseline_val = baseline_funnel[metric]
        current_val = current_funnel[metric]
        change = current_val - baseline_val
        change_rate = change / baseline_val if baseline_val > 0 else 0
        lines.append(f"{label:<20} {format_number(baseline_val):>12} {format_number(current_val):>12} {format_number(change):>12} {format_percentage(change_rate):>10}")

    lines.append("")
    for metric, label in [
        ('cart_rate', '加购率'),
        ('order_rate', '下单转化率'),
        ('cart_to_order_rate', '加购后下单率')
    ]:
        baseline_val = baseline_funnel[metric]
        current_val = current_funnel[metric]
        change = current_val - baseline_val
        lines.append(f"{label:<20} {format_percentage(baseline_val):>12} {format_percentage(current_val):>12} {format_percentage(change):>12}")

    lines.append("")

    # 2. 渠道拆解
    lines.append("【2. 渠道拆解】")
    lines.append("-" * 50)

    baseline_channels = calculate_funnel_stats(sessions, visits, carts, orders, BASELINE_START, BASELINE_END, 'channel')
    current_channels = calculate_funnel_stats(sessions, visits, carts, orders, CURRENT_START, CURRENT_END, 'channel')

    channel_contributions = calculate_contribution(baseline_channels, current_channels, 'order_sessions')

    lines.append(f"{'渠道':<15} {'基准期下单':>10} {'当前期下单':>10} {'变化':>8} {'贡献度':>8}")
    lines.append("-" * 55)
    for c in channel_contributions:
        lines.append(f"{c['group']:<15} {format_number(c['baseline']):>10} {format_number(c['current']):>10} {format_number(c['change']):>8} {format_percentage(c['contribution']):>8}")

    lines.append("")
    lines.append("渠道转化率对比:")
    lines.append(f"{'渠道':<15} {'基准期转化率':>12} {'当前期转化率':>12} {'变化':>10}")
    lines.append("-" * 52)
    for ch in ['organic', 'search_ads', 'douyin', 'direct', 'affiliate']:
        baseline_rate = baseline_channels.get(ch, {}).get('order_rate', 0)
        current_rate = current_channels.get(ch, {}).get('order_rate', 0)
        change = current_rate - baseline_rate
        lines.append(f"{ch:<15} {format_percentage(baseline_rate):>12} {format_percentage(current_rate):>12} {format_percentage(change):>10}")

    lines.append("")

    # 3. 设备拆解
    lines.append("【3. 设备拆解】")
    lines.append("-" * 50)

    baseline_devices = calculate_funnel_stats(sessions, visits, carts, orders, BASELINE_START, BASELINE_END, 'device_type')
    current_devices = calculate_funnel_stats(sessions, visits, carts, orders, CURRENT_START, CURRENT_END, 'device_type')

    device_contributions = calculate_contribution(baseline_devices, current_devices, 'order_sessions')

    lines.append(f"{'设备':<15} {'基准期下单':>10} {'当前期下单':>10} {'变化':>8} {'贡献度':>8}")
    lines.append("-" * 55)
    for c in device_contributions:
        lines.append(f"{c['group']:<15} {format_number(c['baseline']):>10} {format_number(c['current']):>10} {format_number(c['change']):>8} {format_percentage(c['contribution']):>8}")

    lines.append("")
    lines.append("设备转化率对比:")
    lines.append(f"{'设备':<15} {'基准期转化率':>12} {'当前期转化率':>12} {'变化':>10}")
    lines.append("-" * 52)
    for dev in ['app', 'mobile_web', 'pc']:
        baseline_rate = baseline_devices.get(dev, {}).get('order_rate', 0)
        current_rate = current_devices.get(dev, {}).get('order_rate', 0)
        change = current_rate - baseline_rate
        lines.append(f"{dev:<15} {format_percentage(baseline_rate):>12} {format_percentage(current_rate):>12} {format_percentage(change):>10}")

    lines.append("")

    # 4. 地区拆解
    lines.append("【4. 地区拆解】")
    lines.append("-" * 50)

    baseline_regions = calculate_funnel_stats(sessions, visits, carts, orders, BASELINE_START, BASELINE_END, 'region_code')
    current_regions = calculate_funnel_stats(sessions, visits, carts, orders, CURRENT_START, CURRENT_END, 'region_code')

    region_contributions = calculate_contribution(baseline_regions, current_regions, 'order_sessions')

    lines.append(f"{'地区':<15} {'基准期下单':>10} {'当前期下单':>10} {'变化':>8} {'贡献度':>8}")
    lines.append("-" * 55)
    for c in region_contributions:
        lines.append(f"{c['group']:<15} {format_number(c['baseline']):>10} {format_number(c['current']):>10} {format_number(c['change']):>8} {format_percentage(c['contribution']):>8}")

    lines.append("")

    # 5. 商品拆解
    lines.append("【5. 商品拆解】")
    lines.append("-" * 50)

    # 需要按商品统计订单
    baseline_product_orders = defaultdict(int)
    current_product_orders = defaultdict(int)

    session_map = {s['session_key']: s for s in sessions}

    for o in orders:
        sess = session_map.get(o.get('session_key'))
        if not sess or not sess.get('started_at'):
            continue
        prod = o.get('product_external_id', 'unknown')

        if BASELINE_START <= sess['started_at'] < BASELINE_END:
            baseline_product_orders[prod] += 1
        elif CURRENT_START <= sess['started_at'] < CURRENT_END:
            current_product_orders[prod] += 1

    all_products = sorted(set(list(baseline_product_orders.keys()) + list(current_product_orders.keys())))

    lines.append(f"{'商品':<15} {'基准期下单':>10} {'当前期下单':>10} {'变化':>8}")
    lines.append("-" * 48)
    for prod in all_products:
        baseline_val = baseline_product_orders.get(prod, 0)
        current_val = current_product_orders.get(prod, 0)
        change = current_val - baseline_val
        lines.append(f"{prod:<15} {format_number(baseline_val):>10} {format_number(current_val):>10} {format_number(change):>8}")

    lines.append("")

    # 6. 预期归因结论
    lines.append("【6. 预期归因结论】")
    lines.append("-" * 50)
    lines.append("")
    lines.append("基于数据分析，预期归因系统应输出以下结论：")
    lines.append("")

    lines.append("问题定义：")
    lines.append("  为什么本月整体转化率比上月下降？")
    lines.append("")

    lines.append("关键指标：")
    lines.append(f"  - 基准期下单转化率: {format_percentage(baseline_funnel['order_rate'])}")
    lines.append(f"  - 当前期下单转化率: {format_percentage(current_funnel['order_rate'])}")
    lines.append(f"  - 转化率变化: {format_percentage(current_funnel['order_rate'] - baseline_funnel['order_rate'])}")
    lines.append("")

    lines.append("主要贡献因素（按贡献度排序）：")
    lines.append("")
    lines.append("  1. 抖音渠道低质量流量（贡献约48%）")
    lines.append("     - 抖音渠道流量上涨，但转化率大幅下降")
    lines.append("     - 证据：抖音渠道基准期转化率 vs 当前期转化率")
    lines.append("     - 关联业务事件：抖音渠道大规模投放活动")
    lines.append("")
    lines.append("  2. 移动端支付异常（贡献约25%）")
    lines.append("     - mobile_web 设备支付成功率下降")
    lines.append("     - 证据：移动端基准期转化率 vs 当前期转化率")
    lines.append("     - 关联业务事件：移动端结算页加载异常")
    lines.append("")
    lines.append("  3. 商品A库存问题（贡献约15%）")
    lines.append("     - prod_001 加购后下单率极低")
    lines.append("     - 证据：prod_001 加购率 vs 下单率")
    lines.append("     - 关联业务事件：无线蓝牙耳机 Pro 库存紧张")
    lines.append("")
    lines.append("  4. 华东地区配送延迟（贡献约12%）")
    lines.append("     - 华东地区整体转化率下降")
    lines.append("     - 证据：华东地区基准期转化率 vs 当前期转化率")
    lines.append("     - 关联业务事件：华东地区配送延迟")
    lines.append("")

    lines.append("待补充数据：")
    lines.append("  - 抖音渠道具体投放策略和人群定位")
    lines.append("  - 移动端结算页性能监控详细数据")
    lines.append("  - prod_001 库存变化时间线")
    lines.append("  - 华东地区物流合作商配送数据")
    lines.append("")

    lines.append("下一步建议：")
    lines.append("  1. 检查抖音渠道投放ROI，评估是否需要调整投放策略")
    lines.append("  2. 排查移动端结算页加载超时的技术原因")
    lines.append("  3. 确认 prod_001 库存补充计划")
    lines.append("  4. 跟进华东地区物流配送恢复情况")

    return "\n".join(lines)


def main():
    """主函数"""
    # 查找数据目录
    base_dir = os.path.dirname(os.path.abspath(__file__))
    csv_dir = os.path.join(base_dir, 'csv_export')

    if not os.path.exists(csv_dir):
        print(f"错误: 找不到数据目录 {csv_dir}")
        print("请先运行 02_seed_data.py 生成数据")
        return

    # 加载数据
    print("加载数据...")
    sessions = load_csv(os.path.join(csv_dir, 'sessions.csv'))
    visits = load_csv(os.path.join(csv_dir, 'visit_events.csv'))
    carts = load_csv(os.path.join(csv_dir, 'cart_events.csv'))
    orders = load_csv(os.path.join(csv_dir, 'orders.csv'))

    print(f"  会话: {len(sessions)}")
    print(f"  访问: {len(visits)}")
    print(f"  加购: {len(carts)}")
    print(f"  订单: {len(orders)}")

    # 生成报告
    report = generate_report(sessions, visits, carts, orders)
    print("\n" + report)

    # 保存报告
    report_path = os.path.join(base_dir, 'expected_stats_report.txt')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"\n报告已保存到: {report_path}")

    # 保存JSON格式的统计数据
    baseline_funnel = calculate_funnel_stats(sessions, visits, carts, orders, BASELINE_START, BASELINE_END)
    current_funnel = calculate_funnel_stats(sessions, visits, carts, orders, CURRENT_START, CURRENT_END)

    baseline_channels = calculate_funnel_stats(sessions, visits, carts, orders, BASELINE_START, BASELINE_END, 'channel')
    current_channels = calculate_funnel_stats(sessions, visits, carts, orders, CURRENT_START, CURRENT_END, 'channel')

    stats_data = {
        'baseline_period': {
            'start': BASELINE_START.isoformat(),
            'end': BASELINE_END.isoformat()
        },
        'current_period': {
            'start': CURRENT_START.isoformat(),
            'end': CURRENT_END.isoformat()
        },
        'overall_funnel': {
            'baseline': baseline_funnel,
            'current': current_funnel
        },
        'by_channel': {
            'baseline': baseline_channels,
            'current': current_channels
        }
    }

    json_path = os.path.join(base_dir, 'expected_stats.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(stats_data, f, indent=2, default=str)
    print(f"统计数据已保存到: {json_path}")


if __name__ == '__main__':
    main()
