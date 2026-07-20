"""
数据质量检查脚本
==============
检查演示数据是否符合业务规则和数据质量要求。

检查项：
1. 唯一性约束
2. 外键完整性
3. 时间合理性
4. 业务规则
5. 样本量检查
"""

import json
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Tuple
from collections import defaultdict


class DataQualityChecker:
    """数据质量检查器"""

    def __init__(self):
        self.errors: List[Dict] = []
        self.warnings: List[Dict] = []
        self.stats: Dict = {}

    def add_error(self, check_name: str, message: str, count: int = 0):
        """添加错误"""
        self.errors.append({
            'level': 'ERROR',
            'check': check_name,
            'message': message,
            'count': count
        })

    def add_warning(self, check_name: str, message: str, count: int = 0):
        """添加警告"""
        self.warnings.append({
            'level': 'WARNING',
            'check': check_name,
            'message': message,
            'count': count
        })

    def check_uniqueness(self, data: List[Dict], field: str, table_name: str):
        """检查唯一性"""
        seen = set()
        duplicates = []

        for row in data:
            val = row.get(field)
            if val in seen:
                duplicates.append(val)
            seen.add(val)

        if duplicates:
            self.add_error(
                'uniqueness',
                f"{table_name}.{field} 存在重复值: {duplicates[:5]}",
                len(duplicates)
            )
        else:
            self.stats[f'{table_name}.{field}_unique'] = True

    def check_foreign_key(
        self,
        child_data: List[Dict],
        parent_data: List[Dict],
        child_field: str,
        parent_field: str,
        child_table: str,
        parent_table: str
    ):
        """检查外键完整性"""
        parent_keys = {row.get(parent_field) for row in parent_data}
        missing = []

        for row in child_data:
            val = row.get(child_field)
            if val and val not in parent_keys:
                missing.append(val)

        if missing:
            self.add_error(
                'foreign_key',
                f"{child_table}.{child_field} 引用了不存在的 {parent_table}.{parent_field}: {missing[:5]}",
                len(missing)
            )
        else:
            self.stats[f'{child_table}.{child_field}_fk_valid'] = True

    def check_not_null(self, data: List[Dict], field: str, table_name: str):
        """检查非空"""
        null_count = sum(1 for row in data if row.get(field) is None)

        if null_count > 0:
            self.add_error(
                'not_null',
                f"{table_name}.{field} 存在空值",
                null_count
            )

    def check_positive(self, data: List[Dict], field: str, table_name: str):
        """检查正数"""
        negative_count = 0
        for row in data:
            val = row.get(field)
            if val is not None:
                try:
                    if float(val) < 0:
                        negative_count += 1
                except (ValueError, TypeError):
                    pass

        if negative_count > 0:
            self.add_error(
                'positive_check',
                f"{table_name}.{field} 存在负值",
                negative_count
            )

    def check_enum_values(self, data: List[Dict], field: str, valid_values: List[str], table_name: str):
        """检查枚举值"""
        invalid = set()
        for row in data:
            val = row.get(field)
            if val and val not in valid_values:
                invalid.add(val)

        if invalid:
            self.add_error(
                'enum_check',
                f"{table_name}.{field} 存在无效值: {invalid}",
                len(invalid)
            )

    def check_time_after(
        self,
        data: List[Dict],
        time_field: str,
        reference_field: str,
        table_name: str
    ):
        """检查时间先后顺序"""
        violations = 0
        for row in data:
            time_val = row.get(time_field)
            ref_val = row.get(reference_field)
            if time_val and ref_val and time_val < ref_val:
                violations += 1

        if violations > 0:
            self.add_error(
                'time_order',
                f"{table_name}: {time_field} 早于 {reference_field}",
                violations
            )

    def check_sample_size(self, groups: Dict[str, int], min_size: int = 100):
        """检查样本量"""
        small_groups = {k: v for k, v in groups.items() if v < min_size}

        if small_groups:
            self.add_warning(
                'sample_size',
                f"以下分组样本量不足{min_size}，归因结论可能不可靠: {dict(list(small_groups.items())[:5])}",
                len(small_groups)
            )

    def generate_report(self) -> str:
        """生成检查报告"""
        lines = [
            "=" * 60,
            "数据质量检查报告",
            "=" * 60,
            f"检查时间: {datetime.now(timezone.utc).isoformat()}",
            ""
        ]

        # 统计摘要
        lines.append("【统计摘要】")
        for key, value in self.stats.items():
            lines.append(f"  {key}: {value}")
        lines.append("")

        # 错误
        if self.errors:
            lines.append(f"[ERROR] 共 {len(self.errors)} 项")
            for err in self.errors:
                lines.append(f"  X [{err['check']}] {err['message']} (数量: {err['count']})")
        else:
            lines.append("[ERROR] 无 OK")
        lines.append("")

        # 警告
        if self.warnings:
            lines.append(f"[WARNING] 共 {len(self.warnings)} 项")
            for warn in self.warnings:
                lines.append(f"  ! [{warn['check']}] {warn['message']} (数量: {warn['count']})")
        else:
            lines.append("[WARNING] 无 OK")
        lines.append("")

        # 结论
        if self.errors:
            lines.append("[CONCLUSION] FAIL 数据质量检查未通过，请修复错误后重新生成")
        else:
            lines.append("[CONCLUSION] PASS 数据质量检查通过")

        return "\n".join(lines)


def check_users(users: List[Dict], checker: DataQualityChecker):
    """检查用户表"""
    print("检查 biz_users...")

    checker.check_uniqueness(users, 'external_user_id', 'biz_users')
    checker.check_not_null(users, 'external_user_id', 'biz_users')
    checker.check_not_null(users, 'registered_at', 'biz_users')
    checker.check_not_null(users, 'status', 'biz_users')
    checker.check_enum_values(users, 'status', ['active', 'disabled'], 'biz_users')

    checker.stats['biz_users_count'] = len(users)


def check_products(products: List[Dict], checker: DataQualityChecker):
    """检查商品表"""
    print("检查 products...")

    checker.check_uniqueness(products, 'external_product_id', 'products')
    checker.check_not_null(products, 'external_product_id', 'products')
    checker.check_not_null(products, 'product_name', 'products')
    checker.check_not_null(products, 'category_code', 'products')
    checker.check_positive(products, 'current_price', 'products')
    checker.check_enum_values(products, 'status', ['active', 'inactive'], 'products')

    checker.stats['products_count'] = len(products)


def check_sessions(sessions: List[Dict], users: List[Dict], checker: DataQualityChecker):
    """检查会话表"""
    print("检查 sessions...")

    checker.check_uniqueness(sessions, 'session_key', 'sessions')
    checker.check_not_null(sessions, 'session_key', 'sessions')
    checker.check_not_null(sessions, 'channel', 'sessions')
    checker.check_not_null(sessions, 'device_type', 'sessions')
    checker.check_not_null(sessions, 'user_type_snapshot', 'sessions')
    checker.check_not_null(sessions, 'started_at', 'sessions')

    checker.check_enum_values(
        sessions, 'channel',
        ['organic', 'search_ads', 'douyin', 'direct', 'affiliate', 'other'],
        'sessions'
    )
    checker.check_enum_values(
        sessions, 'device_type',
        ['app', 'mobile_web', 'pc'],
        'sessions'
    )
    checker.check_enum_values(
        sessions, 'user_type_snapshot',
        ['new', 'returning'],
        'sessions'
    )

    # 检查用户类型逻辑
    wrong_user_type = 0
    for s in sessions:
        if s.get('user_external_id') and s.get('started_at'):
            user = next((u for u in users if u['external_user_id'] == s['user_external_id']), None)
            if user and user.get('registered_at') and s.get('started_at'):
                days = (s['started_at'] - user['registered_at']).days
                expected_type = 'new' if days <= 7 else 'returning'
                if s['user_type_snapshot'] != expected_type:
                    wrong_user_type += 1

    if wrong_user_type > 0:
        checker.add_error('user_type_logic', '用户类型快照与注册时间不匹配', wrong_user_type)

    checker.stats['sessions_count'] = len(sessions)

    # 按渠道统计
    channel_counts = defaultdict(int)
    for s in sessions:
        channel_counts[s.get('channel', 'unknown')] += 1
    checker.stats['sessions_by_channel'] = dict(channel_counts)

    # 按设备统计
    device_counts = defaultdict(int)
    for s in sessions:
        device_counts[s.get('device_type', 'unknown')] += 1
    checker.stats['sessions_by_device'] = dict(device_counts)


def check_visit_events(visits: List[Dict], sessions: List[Dict], checker: DataQualityChecker):
    """检查访问事件表"""
    print("检查 visit_events...")

    checker.check_uniqueness(visits, 'source_event_id', 'visit_events')
    checker.check_not_null(visits, 'source_event_id', 'visit_events')
    checker.check_not_null(visits, 'session_key', 'visit_events')
    checker.check_not_null(visits, 'occurred_at', 'visit_events')

    # 检查会话存在
    session_keys = {s['session_key'] for s in sessions}
    missing_sessions = sum(1 for v in visits if v.get('session_key') not in session_keys)
    if missing_sessions > 0:
        checker.add_error('foreign_key', 'visit_events 引用了不存在的 session_key', missing_sessions)

    checker.stats['visit_events_count'] = len(visits)


def check_cart_events(carts: List[Dict], sessions: List[Dict], checker: DataQualityChecker):
    """检查加购事件表"""
    print("检查 cart_events...")

    checker.check_uniqueness(carts, 'source_event_id', 'cart_events')
    checker.check_not_null(carts, 'source_event_id', 'cart_events')
    checker.check_not_null(carts, 'session_key', 'cart_events')
    checker.check_not_null(carts, 'product_external_id', 'cart_events')
    checker.check_not_null(carts, 'occurred_at', 'cart_events')

    checker.check_enum_values(carts, 'action', ['add', 'remove', 'update'], 'cart_events')
    checker.check_positive(carts, 'quantity', 'cart_events')

    # 检查会话存在
    session_keys = {s['session_key'] for s in sessions}
    missing_sessions = sum(1 for c in carts if c.get('session_key') not in session_keys)
    if missing_sessions > 0:
        checker.add_error('foreign_key', 'cart_events 引用了不存在的 session_key', missing_sessions)

    checker.stats['cart_events_count'] = len(carts)

    # 按动作统计
    action_counts = defaultdict(int)
    for c in carts:
        action_counts[c.get('action', 'unknown')] += 1
    checker.stats['cart_events_by_action'] = dict(action_counts)


def check_orders(orders: List[Dict], sessions: List[Dict], checker: DataQualityChecker):
    """检查订单表"""
    print("检查 orders...")

    checker.check_uniqueness(orders, 'order_no', 'orders')
    checker.check_not_null(orders, 'order_no', 'orders')
    checker.check_not_null(orders, 'session_key', 'orders')
    checker.check_not_null(orders, 'user_external_id', 'orders')
    checker.check_not_null(orders, 'product_external_id', 'orders')
    checker.check_not_null(orders, 'order_status', 'orders')
    checker.check_not_null(orders, 'created_at', 'orders')

    checker.check_enum_values(
        orders, 'order_status',
        ['created', 'paid', 'completed', 'cancelled', 'refunded'],
        'orders'
    )
    checker.check_positive(orders, 'quantity', 'orders')
    checker.check_positive(orders, 'unit_price', 'orders')
    checker.check_positive(orders, 'order_amount', 'orders')

    # 有效订单必须有 paid_at
    valid_orders = [o for o in orders if o['order_status'] in ('paid', 'completed')]
    missing_paid_at = sum(1 for o in valid_orders if o.get('paid_at') is None)
    if missing_paid_at > 0:
        checker.add_error('business_rule', '有效订单(paid/completed)缺少 paid_at', missing_paid_at)

    # 检查会话存在
    session_keys = {s['session_key'] for s in sessions}
    missing_sessions = sum(1 for o in orders if o.get('session_key') not in session_keys)
    if missing_sessions > 0:
        checker.add_error('foreign_key', 'orders 引用了不存在的 session_key', missing_sessions)

    checker.stats['orders_count'] = len(orders)

    # 按状态统计
    status_counts = defaultdict(int)
    for o in orders:
        status_counts[o.get('order_status', 'unknown')] += 1
    checker.stats['orders_by_status'] = dict(status_counts)


def check_funnel_consistency(
    sessions: List[Dict],
    visits: List[Dict],
    carts: List[Dict],
    orders: List[Dict],
    checker: DataQualityChecker
):
    """检查漏斗一致性"""
    print("检查漏斗一致性...")

    # 计算各阶段会话
    visit_sessions = {v['session_key'] for v in visits}
    cart_sessions = {c['session_key'] for c in carts if c.get('action') == 'add'}
    order_sessions = {o['session_key'] for o in orders if o.get('order_status') in ('paid', 'completed')}

    # 下单会话应该有访问事件
    orders_without_visit = order_sessions - visit_sessions
    if orders_without_visit:
        checker.add_warning(
            'funnel_consistency',
            f"存在下单会话没有访问事件: {len(orders_without_visit)} 个",
            len(orders_without_visit)
        )

    # 加购会话应该有访问事件
    carts_without_visit = cart_sessions - visit_sessions
    if carts_without_visit:
        checker.add_warning(
            'funnel_consistency',
            f"存在加购会话没有访问事件: {len(carts_without_visit)} 个",
            len(carts_without_visit)
        )

    # 记录漏斗统计
    checker.stats['funnel'] = {
        'total_sessions': len(sessions),
        'visit_sessions': len(visit_sessions),
        'cart_sessions': len(cart_sessions),
        'order_sessions': len(order_sessions)
    }


def main():
    """主函数"""
    import csv
    import os

    # 查找数据目录
    base_dir = os.path.dirname(os.path.abspath(__file__))
    csv_dir = os.path.join(base_dir, 'csv_export')

    if not os.path.exists(csv_dir):
        print(f"错误: 找不到数据目录 {csv_dir}")
        print("请先运行 02_seed_data.py 生成数据")
        return

    # 加载数据
    def load_csv(filename: str) -> List[Dict]:
        filepath = os.path.join(csv_dir, filename)
        if not os.path.exists(filepath):
            print(f"警告: 找不到文件 {filepath}")
            return []
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            return list(reader)

    print("加载数据...")
    users = load_csv('biz_users.csv')
    products = load_csv('products.csv')
    sessions = load_csv('sessions.csv')
    visits = load_csv('visit_events.csv')
    carts = load_csv('cart_events.csv')
    orders = load_csv('orders.csv')

    # 初始化检查器
    checker = DataQualityChecker()

    # 执行检查
    print("\n开始数据质量检查...\n")

    check_users(users, checker)
    check_products(products, checker)
    check_sessions(sessions, users, checker)
    check_visit_events(visits, sessions, checker)
    check_cart_events(carts, sessions, checker)
    check_orders(orders, sessions, checker)
    check_funnel_consistency(sessions, visits, carts, orders, checker)

    # 生成报告
    report = checker.generate_report()
    print("\n" + report)

    # 保存报告
    report_path = os.path.join(base_dir, 'quality_report.txt')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"\n报告已保存到: {report_path}")

    return len(checker.errors) == 0


if __name__ == '__main__':
    success = main()
    exit(0 if success else 1)
