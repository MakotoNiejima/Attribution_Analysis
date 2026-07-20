"""
演示数据生成器
============
生成基准期和当前期的数据，并植入已知异常用于验证归因系统。

植入的异常：
1. 抖音渠道：流量上涨40%，但转化率下降50%（低质量流量）
2. 商品A：库存不足，加购后下单率极低
3. 移动端(mobile_web)：结算页访问正常但支付成功率下降
4. 华东地区：配送问题导致转化下降
"""

import json
import random
import hashlib
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Tuple
import csv
import os

# ============================================================
# 配置
# ============================================================

# 时间范围（左闭右开）
BASELINE_START = datetime(2026, 6, 1, tzinfo=timezone.utc)
BASELINE_END = datetime(2026, 6, 15, tzinfo=timezone.utc)
CURRENT_START = datetime(2026, 7, 1, tzinfo=timezone.utc)
CURRENT_END = datetime(2026, 7, 15, tzinfo=timezone.utc)

STORE_ID = "store_001"

# 渠道配置
CHANNELS = ['organic', 'search_ads', 'douyin', 'direct', 'affiliate', 'other']

# 设备配置
DEVICES = ['app', 'mobile_web', 'pc']

# 地区配置
REGIONS = ['east_china', 'north_china', 'south_china', 'central_china', 'west_china']

# 用户类型
USER_TYPES = ['new', 'returning']

# ============================================================
# 商品配置（5个商品）
# ============================================================
PRODUCTS = [
    {
        'external_product_id': 'prod_001',
        'product_name': '无线蓝牙耳机 Pro',
        'category_code': 'electronics',
        'current_price': 299.00,
        'status': 'active'
    },
    {
        'external_product_id': 'prod_002',
        'product_name': '智能手表 运动版',
        'category_code': 'electronics',
        'current_price': 599.00,
        'status': 'active'
    },
    {
        'external_product_id': 'prod_003',
        'product_name': '便携充电宝 20000mAh',
        'category_code': 'electronics',
        'current_price': 129.00,
        'status': 'active'
    },
    {
        'external_product_id': 'prod_004',
        'product_name': '运动水壶 保温款',
        'category_code': 'lifestyle',
        'current_price': 89.00,
        'status': 'active'
    },
    {
        'external_product_id': 'prod_005',
        'product_name': '手机支架 桌面版',
        'category_code': 'accessories',
        'current_price': 39.00,
        'status': 'active'
    },
]


class DataGenerator:
    """演示数据生成器"""

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self.user_counter = 0
        self.session_counter = 0
        self.event_counter = 0
        self.order_counter = 0

        # 存储生成的数据
        self.users: List[Dict] = []
        self.products: List[Dict] = []
        self.sessions: List[Dict] = []
        self.visit_events: List[Dict] = []
        self.cart_events: List[Dict] = []
        self.orders: List[Dict] = []
        self.business_events: List[Dict] = []

    def _gen_id(self, prefix: str) -> str:
        """生成唯一ID"""
        self.event_counter += 1
        return f"{prefix}_{self.event_counter:06d}"

    def _random_time(self, start: datetime, end: datetime) -> datetime:
        """在时间范围内随机生成时间"""
        delta = end - start
        random_seconds = self.rng.randint(0, int(delta.total_seconds()) - 1)
        return start + timedelta(seconds=random_seconds)

    def generate_users(self, count: int) -> List[Dict]:
        """生成用户"""
        users = []
        for i in range(count):
            # 注册时间：从6个月前到当前期开始
            reg_days_ago = self.rng.randint(1, 180)
            registered_at = CURRENT_START - timedelta(days=reg_days_ago)

            user = {
                'external_user_id': f"user_{i+1:04d}",
                'registered_at': registered_at,
                'default_region_code': self.rng.choice(REGIONS),
                'status': 'active'
            }
            users.append(user)

        self.users = users
        return users

    def generate_sessions(
        self,
        start: datetime,
        end: datetime,
        base_count: int,
        channel_weights: Dict[str, float],
        device_weights: Dict[str, float],
        is_current: bool = False
    ) -> List[Dict]:
        """
        生成会话

        Args:
            start: 开始时间
            end: 结束时间
            base_count: 基础会话数
            channel_weights: 渠道权重
            device_weights: 设备权重
            is_current: 是否当前期（用于植入异常）
        """
        sessions = []

        for i in range(base_count):
            user = self.rng.choice(self.users)

            # 确定渠道
            channel = self.rng.choices(
                list(channel_weights.keys()),
                weights=list(channel_weights.values())
            )[0]

            # 确定设备
            device = self.rng.choices(
                list(device_weights.keys()),
                weights=list(device_weights.values())
            )[0]

            # 确定地区
            region = user['default_region_code']

            # 确定用户类型
            session_start = self._random_time(start, end)
            days_since_reg = (session_start - user['registered_at']).days
            user_type = 'new' if days_since_reg <= 7 else 'returning'

            session = {
                'session_key': self._gen_id('sess'),
                'store_id': STORE_ID,
                'user_external_id': user['external_user_id'],
                'channel': channel,
                'device_type': device,
                'region_code': region,
                'user_type_snapshot': user_type,
                'started_at': session_start,
                'ended_at': session_start + timedelta(minutes=self.rng.randint(1, 60)),
                'is_bot': False,
                'source_meta_json': {}
            }
            sessions.append(session)

        self.sessions.extend(sessions)
        return sessions

    def generate_funnel_events(
        self,
        sessions: List[Dict],
        products: List[Dict],
        visit_rate: float = 1.0,
        cart_rate: float = 0.3,
        order_rate: float = 0.15,
        is_current: bool = False,
        channel_exceptions: Dict = None,
        device_exceptions: Dict = None,
        region_exceptions: Dict = None,
        product_exceptions: Dict = None
    ) -> Tuple[List[Dict], List[Dict], List[Dict]]:
        """
        生成漏斗事件（访问→加购→下单）

        Args:
            sessions: 会话列表
            products: 商品列表
            visit_rate: 访问率（通常1.0）
            cart_rate: 加购率
            order_rate: 下单率（相对于访问）
            is_current: 是否当前期
            channel_exceptions: 渠道级异常 {channel: {cart_rate, order_rate}}
            device_exceptions: 设备级异常
            region_exceptions: 地区级异常
            product_exceptions: 商品级异常
        """
        visits = []
        carts = []
        orders = []

        channel_exceptions = channel_exceptions or {}
        device_exceptions = device_exceptions or {}
        region_exceptions = region_exceptions or {}
        product_exceptions = product_exceptions or {}

        for session in sessions:
            # 1. 访问事件（几乎每个会话都有）
            if self.rng.random() < visit_rate:
                product = self.rng.choice(products)

                visit = {
                    'source_event_id': self._gen_id('visit'),
                    'session_key': session['session_key'],
                    'product_external_id': product['external_product_id'],
                    'page_type': self.rng.choice(['home', 'product', 'search', 'category']),
                    'occurred_at': session['started_at'] + timedelta(seconds=self.rng.randint(0, 300)),
                    'metadata_json': {}
                }
                visits.append(visit)

                # 2. 加购事件
                # 计算实际加购率（考虑异常）
                actual_cart_rate = cart_rate
                channel = session['channel']
                device = session['device_type']
                region = session['region_code']
                prod_id = product['external_product_id']

                if channel in channel_exceptions:
                    actual_cart_rate = channel_exceptions[channel].get('cart_rate', actual_cart_rate)
                if device in device_exceptions:
                    actual_cart_rate = device_exceptions[device].get('cart_rate', actual_cart_rate)
                if region in region_exceptions:
                    actual_cart_rate = region_exceptions[region].get('cart_rate', actual_cart_rate)
                if prod_id in product_exceptions:
                    actual_cart_rate = product_exceptions[prod_id].get('cart_rate', actual_cart_rate)

                if self.rng.random() < actual_cart_rate:
                    cart = {
                        'source_event_id': self._gen_id('cart'),
                        'session_key': session['session_key'],
                        'product_external_id': product['external_product_id'],
                        'action': 'add',
                        'quantity': self.rng.randint(1, 3),
                        'occurred_at': visit['occurred_at'] + timedelta(seconds=self.rng.randint(30, 600)),
                        'metadata_json': {}
                    }
                    carts.append(cart)

                    # 3. 下单事件
                    actual_order_rate = order_rate
                    if channel in channel_exceptions:
                        actual_order_rate = channel_exceptions[channel].get('order_rate', actual_order_rate)
                    if device in device_exceptions:
                        actual_order_rate = device_exceptions[device].get('order_rate', actual_order_rate)
                    if region in region_exceptions:
                        actual_order_rate = region_exceptions[region].get('order_rate', actual_order_rate)
                    if prod_id in product_exceptions:
                        actual_order_rate = product_exceptions[prod_id].get('order_rate', actual_order_rate)

                    if self.rng.random() < actual_order_rate:
                        self.order_counter += 1
                        quantity = self.rng.randint(1, 2)
                        unit_price = product['current_price']

                        # 确定支付状态
                        pay_success_rate = 0.95  # 默认95%支付成功
                        if device in device_exceptions:
                            pay_success_rate = device_exceptions[device].get('pay_success_rate', pay_success_rate)

                        is_paid = self.rng.random() < pay_success_rate
                        order_status = 'paid' if is_paid else 'created'
                        paid_at = cart['occurred_at'] + timedelta(seconds=self.rng.randint(60, 1800)) if is_paid else None

                        order = {
                            'order_no': f"ORD_{self.order_counter:08d}",
                            'session_key': session['session_key'],
                            'user_external_id': session['user_external_id'],
                            'product_external_id': product['external_product_id'],
                            'order_status': order_status,
                            'quantity': quantity,
                            'unit_price': unit_price,
                            'order_amount': quantity * unit_price,
                            'created_at': cart['occurred_at'] + timedelta(seconds=self.rng.randint(60, 600)),
                            'paid_at': paid_at,
                            'completed_at': paid_at + timedelta(days=self.rng.randint(1, 7)) if paid_at else None,
                            'cancelled_at': None
                        }
                        orders.append(order)

        self.visit_events.extend(visits)
        self.cart_events.extend(carts)
        self.orders.extend(orders)

        return visits, carts, orders

    def generate_business_events(self) -> List[Dict]:
        """生成业务事件（用于关联归因）"""
        events = [
            {
                'event_code': 'evt_douyin_campaign',
                'store_id': STORE_ID,
                'event_type': 'campaign',
                'title': '抖音渠道大规模投放活动',
                'description': '7月1日-15日期间在抖音渠道进行大规模流量投放，预计流量增长40%',
                'started_at': CURRENT_START,
                'ended_at': CURRENT_END,
                'scope_json': {'channel': ['douyin']},
                'severity': 'medium',
                'source_type': 'campaign_config'
            },
            {
                'event_code': 'evt_prod001_stockout',
                'store_id': STORE_ID,
                'event_type': 'inventory',
                'title': '无线蓝牙耳机 Pro 库存紧张',
                'description': 'prod_001 库存降至安全库存以下，部分SKU显示无货',
                'started_at': datetime(2026, 7, 5, tzinfo=timezone.utc),
                'ended_at': CURRENT_END,
                'scope_json': {'product_id': ['prod_001']},
                'severity': 'high',
                'source_type': 'inventory_system'
            },
            {
                'event_code': 'evt_mobile_checkout_bug',
                'store_id': STORE_ID,
                'event_type': 'technical',
                'title': '移动端结算页加载异常',
                'description': '7月3日-12日期间，mobile_web设备结算页加载超时率上升，影响支付转化',
                'started_at': datetime(2026, 7, 3, tzinfo=timezone.utc),
                'ended_at': datetime(2026, 7, 12, tzinfo=timezone.utc),
                'scope_json': {'device_type': ['mobile_web'], 'page_type': ['checkout']},
                'severity': 'high',
                'source_type': 'monitoring_alert'
            },
            {
                'event_code': 'evt_east_delivery_delay',
                'store_id': STORE_ID,
                'event_type': 'logistics',
                'title': '华东地区配送延迟',
                'description': '7月上旬华东地区物流配送延迟，平均配送时长增加2天',
                'started_at': datetime(2026, 7, 1, tzinfo=timezone.utc),
                'ended_at': datetime(2026, 7, 10, tzinfo=timezone.utc),
                'scope_json': {'region_code': ['east_china']},
                'severity': 'medium',
                'source_type': 'logistics_report'
            },
            {
                'event_code': 'evt_price_increase',
                'store_id': STORE_ID,
                'event_type': 'pricing',
                'title': '智能手表调价',
                'description': '7月8日起智能手表运动版价格从499调整至599',
                'started_at': datetime(2026, 7, 8, tzinfo=timezone.utc),
                'ended_at': None,
                'scope_json': {'product_id': ['prod_002']},
                'severity': 'low',
                'source_type': 'price_change_log'
            }
        ]

        self.business_events.extend(events)
        return events


def generate_baseline_data(gen: DataGenerator, products: List[Dict]) -> Dict:
    """生成基准期数据（6月，相对正常）"""

    # 生成用户
    gen.generate_users(500)

    # 基准期渠道权重（正常分布）
    channel_weights = {
        'organic': 0.30,
        'search_ads': 0.25,
        'douyin': 0.15,
        'direct': 0.15,
        'affiliate': 0.10,
        'other': 0.05
    }

    # 基准期设备权重
    device_weights = {
        'app': 0.40,
        'mobile_web': 0.35,
        'pc': 0.25
    }

    # 生成会话（基准期约3000个会话）
    sessions = gen.generate_sessions(
        start=BASELINE_START,
        end=BASELINE_END,
        base_count=3000,
        channel_weights=channel_weights,
        device_weights=device_weights,
        is_current=False
    )

    # 生成漏斗事件（正常转化率）
    gen.generate_funnel_events(
        sessions=sessions,
        products=products,
        visit_rate=1.0,
        cart_rate=0.30,   # 30%加购率
        order_rate=0.12,  # 12%下单转化率
        is_current=False
    )

    return {
        'sessions': len(sessions),
        'visits': len(gen.visit_events),
        'carts': len(gen.cart_events),
        'orders': len(gen.orders)
    }


def generate_current_data(gen: DataGenerator, products: List[Dict]) -> Dict:
    """生成当前期数据（7月，植入异常）"""

    # 当前期渠道权重（抖音流量上涨）
    channel_weights = {
        'organic': 0.25,
        'search_ads': 0.20,
        'douyin': 0.30,   # 抖音流量大幅上涨
        'direct': 0.12,
        'affiliate': 0.08,
        'other': 0.05
    }

    # 当前期设备权重
    device_weights = {
        'app': 0.38,
        'mobile_web': 0.37,
        'pc': 0.25
    }

    # 生成会话（当前期约3500个会话，总体流量上涨）
    sessions = gen.generate_sessions(
        start=CURRENT_START,
        end=CURRENT_END,
        base_count=3500,
        channel_weights=channel_weights,
        device_weights=device_weights,
        is_current=True
    )

    # 植入异常的漏斗事件
    gen.generate_funnel_events(
        sessions=sessions,
        products=products,
        visit_rate=1.0,
        cart_rate=0.28,   # 整体加购率略降
        order_rate=0.10,  # 整体下单率下降
        is_current=True,
        channel_exceptions={
            'douyin': {
                'cart_rate': 0.15,   # 抖音加购率大幅下降
                'order_rate': 0.04   # 抖音下单率极低
            }
        },
        device_exceptions={
            'mobile_web': {
                'order_rate': 0.06,        # 移动端下单率下降
                'pay_success_rate': 0.70   # 移动端支付成功率下降
            }
        },
        region_exceptions={
            'east_china': {
                'cart_rate': 0.22,   # 华东加购率下降
                'order_rate': 0.07   # 华东下单率下降
            }
        },
        product_exceptions={
            'prod_001': {
                'cart_rate': 0.25,   # 耳机加购还行
                'order_rate': 0.03   # 但下单极低（库存问题）
            }
        }
    )

    return {
        'sessions': len(sessions),
        'visits': len(gen.visit_events),
        'carts': len(gen.cart_events),
        'orders': len(gen.orders)
    }


def export_to_csv(data: List[Dict], filepath: str):
    """导出为CSV"""
    if not data:
        return

    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)

    print(f"  Exported {len(data)} rows to {filepath}")


def export_sql_inserts(data: List[Dict], table_name: str, filepath: str, columns: List[str] = None):
    """导出为SQL INSERT语句"""
    if not data:
        return

    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    if columns is None:
        columns = list(data[0].keys())

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(f"-- {table_name} INSERT statements\n")
        f.write(f"-- Generated at {datetime.now(timezone.utc).isoformat()}\n\n")

        for row in data:
            values = []
            for col in columns:
                val = row.get(col)
                if val is None:
                    values.append('NULL')
                elif isinstance(val, bool):
                    values.append('TRUE' if val else 'FALSE')
                elif isinstance(val, (int, float)):
                    values.append(str(val))
                elif isinstance(val, dict):
                    values.append(f"'{json.dumps(val)}'::jsonb")
                elif isinstance(val, datetime):
                    values.append(f"'{val.isoformat()}'")
                else:
                    # 转义单引号
                    escaped = str(val).replace("'", "''")
                    values.append(f"'{escaped}'")

            f.write(f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({', '.join(values)});\n")

    print(f"  Exported {len(data)} INSERT statements to {filepath}")


def main():
    """主函数"""
    print("=" * 60)
    print("经营归因分析系统 - 演示数据生成器")
    print("=" * 60)

    # 输出目录
    output_dir = os.path.dirname(os.path.abspath(__file__))
    sql_dir = os.path.join(output_dir, 'sql_inserts')
    csv_dir = os.path.join(output_dir, 'csv_export')

    # 初始化生成器
    gen = DataGenerator(seed=42)

    # 1. 生成基准期数据
    print("\n[1/4] 生成基准期数据 (2026-06-01 ~ 2026-06-15)...")
    baseline_stats = generate_baseline_data(gen, PRODUCTS)

    # 保存基准期数据快照
    baseline_sessions = gen.sessions.copy()
    baseline_visits = gen.visit_events.copy()
    baseline_carts = gen.cart_events.copy()
    baseline_orders = gen.orders.copy()

    # 2. 生成当前期数据
    print("\n[2/4] 生成当前期数据 (2026-07-01 ~ 2026-07-15)...")
    current_sessions_start = len(gen.sessions)
    current_visits_start = len(gen.visit_events)
    current_carts_start = len(gen.cart_events)
    current_orders_start = len(gen.orders)

    current_stats = generate_current_data(gen, PRODUCTS)

    # 3. 生成业务事件
    print("\n[3/4] 生成业务事件...")
    biz_events = gen.generate_business_events()

    # 4. 导出数据
    print("\n[4/4] 导出数据...")

    # 导出 biz_users
    users_data = [
        {
            'external_user_id': u['external_user_id'],
            'registered_at': u['registered_at'],
            'default_region_code': u['default_region_code'],
            'status': u['status']
        }
        for u in gen.users
    ]
    export_sql_inserts(users_data, 'biz_users', os.path.join(sql_dir, '01_biz_users.sql'))
    export_to_csv(users_data, os.path.join(csv_dir, 'biz_users.csv'))

    # 导出 products
    products_data = [
        {
            'external_product_id': p['external_product_id'],
            'store_id': STORE_ID,
            'product_name': p['product_name'],
            'category_code': p['category_code'],
            'current_price': p['current_price'],
            'status': p['status']
        }
        for p in PRODUCTS
    ]
    export_sql_inserts(products_data, 'products', os.path.join(sql_dir, '02_products.sql'))
    export_to_csv(products_data, os.path.join(csv_dir, 'products.csv'))

    # 导出 sessions
    sessions_data = [
        {
            'session_key': s['session_key'],
            'store_id': s['store_id'],
            'channel': s['channel'],
            'device_type': s['device_type'],
            'region_code': s['region_code'],
            'user_type_snapshot': s['user_type_snapshot'],
            'started_at': s['started_at'],
            'ended_at': s['ended_at'],
            'is_bot': s['is_bot'],
            'source_meta_json': json.dumps(s['source_meta_json'])
        }
        for s in gen.sessions
    ]
    export_sql_inserts(sessions_data, 'sessions', os.path.join(sql_dir, '03_sessions.sql'))
    export_to_csv(sessions_data, os.path.join(csv_dir, 'sessions.csv'))

    # 导出 visit_events
    visits_data = [
        {
            'source_event_id': v['source_event_id'],
            'session_key': v['session_key'],
            'product_external_id': v.get('product_external_id'),
            'page_type': v['page_type'],
            'occurred_at': v['occurred_at'],
            'metadata_json': json.dumps(v.get('metadata_json', {}))
        }
        for v in gen.visit_events
    ]
    export_sql_inserts(visits_data, 'visit_events', os.path.join(sql_dir, '04_visit_events.sql'))
    export_to_csv(visits_data, os.path.join(csv_dir, 'visit_events.csv'))

    # 导出 cart_events
    carts_data = [
        {
            'source_event_id': c['source_event_id'],
            'session_key': c['session_key'],
            'product_external_id': c['product_external_id'],
            'action': c['action'],
            'quantity': c['quantity'],
            'occurred_at': c['occurred_at'],
            'metadata_json': json.dumps(c.get('metadata_json', {}))
        }
        for c in gen.cart_events
    ]
    export_sql_inserts(carts_data, 'cart_events', os.path.join(sql_dir, '05_cart_events.sql'))
    export_to_csv(carts_data, os.path.join(csv_dir, 'cart_events.csv'))

    # 导出 orders
    orders_data = [
        {
            'order_no': o['order_no'],
            'session_key': o['session_key'],
            'user_external_id': o['user_external_id'],
            'product_external_id': o['product_external_id'],
            'order_status': o['order_status'],
            'quantity': o['quantity'],
            'unit_price': o['unit_price'],
            'order_amount': o['order_amount'],
            'created_at': o['created_at'],
            'paid_at': o.get('paid_at'),
            'completed_at': o.get('completed_at'),
            'cancelled_at': o.get('cancelled_at')
        }
        for o in gen.orders
    ]
    export_sql_inserts(orders_data, 'orders', os.path.join(sql_dir, '06_orders.sql'))
    export_to_csv(orders_data, os.path.join(csv_dir, 'orders.csv'))

    # 导出 business_events
    biz_events_data = [
        {
            'event_code': e['event_code'],
            'store_id': e['store_id'],
            'event_type': e['event_type'],
            'title': e['title'],
            'description': e['description'],
            'started_at': e['started_at'],
            'ended_at': e.get('ended_at'),
            'scope_json': json.dumps(e['scope_json']),
            'severity': e['severity'],
            'source_type': e['source_type']
        }
        for e in biz_events
    ]
    export_sql_inserts(biz_events_data, 'business_events', os.path.join(sql_dir, '07_business_events.sql'))
    export_to_csv(biz_events_data, os.path.join(csv_dir, 'business_events.csv'))

    # 统计摘要
    print("\n" + "=" * 60)
    print("数据生成完成")
    print("=" * 60)

    print("\n基准期统计:")
    print(f"  会话数: {baseline_stats['sessions']}")
    print(f"  访问事件: {baseline_stats['visits']}")
    print(f"  加购事件: {baseline_stats['carts']}")
    print(f"  订单数: {baseline_stats['orders']}")

    print("\n当前期统计:")
    print(f"  会话数: {current_stats['sessions'] - baseline_stats['sessions']}")
    print(f"  访问事件: {current_stats['visits'] - baseline_stats['visits']}")
    print(f"  加购事件: {current_stats['carts'] - baseline_stats['carts']}")
    print(f"  订单数: {current_stats['orders'] - baseline_stats['orders']}")

    print("\n植入的异常:")
    print("  1. 抖音渠道: 流量上涨，但转化率大幅下降")
    print("  2. 商品prod_001: 加购后下单率极低（库存问题）")
    print("  3. 移动端(mobile_web): 支付成功率下降")
    print("  4. 华东地区: 转化率整体下降")

    print("\n输出目录:")
    print(f"  SQL: {sql_dir}")
    print(f"  CSV: {csv_dir}")

    # 保存元数据
    metadata = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'baseline_period': {
            'start': BASELINE_START.isoformat(),
            'end': BASELINE_END.isoformat()
        },
        'current_period': {
            'start': CURRENT_START.isoformat(),
            'end': CURRENT_END.isoformat()
        },
        'baseline_stats': baseline_stats,
        'current_stats': {
            'sessions': current_stats['sessions'] - baseline_stats['sessions'],
            'visits': current_stats['visits'] - baseline_stats['visits'],
            'carts': current_stats['carts'] - baseline_stats['carts'],
            'orders': current_stats['orders'] - baseline_stats['orders']
        },
        'planted_anomalies': [
            'douyin_low_quality_traffic',
            'prod_001_stockout',
            'mobile_web_checkout_bug',
            'east_china_delivery_delay'
        ]
    }

    metadata_path = os.path.join(output_dir, 'metadata.json')
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, default=str)
    print(f"\n  元数据: {metadata_path}")


if __name__ == '__main__':
    main()
