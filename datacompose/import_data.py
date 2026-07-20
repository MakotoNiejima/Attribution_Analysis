"""
演示数据导入脚本
=============
读取 CSV 文件并导入到 MySQL 数据库。

使用方式：
    cd D:\dev\归因分析\data_compose
    python import_data.py
"""

import csv
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text


# 以项目统一 .env 为唯一凭证来源，避免在导入脚本中保留明文密码。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME


def build_database_url() -> str:
    password = quote_plus(DB_PASSWORD)
    return f"mysql+aiomysql://{DB_USER}:{password}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"


def load_csv(filepath: str) -> list:
    """加载 CSV 文件"""
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        return list(reader)


def parse_datetime(val: str) -> datetime | None:
    """解析日期时间"""
    if not val or val == '':
        return None
    try:
        return datetime.fromisoformat(val.replace('Z', '+00:00'))
    except:
        return None


def parse_int(val: str) -> int | None:
    """解析整数"""
    if not val or val == '':
        return None
    try:
        return int(val)
    except:
        return None


def parse_float(val: str) -> float | None:
    """解析浮点数"""
    if not val or val == '':
        return None
    try:
        return float(val)
    except:
        return None


def parse_bool(val: str) -> bool:
    """解析布尔值"""
    return val.lower() in ('true', '1', 'yes')


async def import_biz_users(session: AsyncSession, csv_dir: str):
    """导入用户数据"""
    filepath = os.path.join(csv_dir, 'biz_users.csv')
    if not os.path.exists(filepath):
        print("  [SKIP] biz_users.csv 不存在")
        return

    rows = load_csv(filepath)
    print(f"  导入 biz_users: {len(rows)} 行...")

    for row in rows:
        await session.execute(
            text("""
                INSERT INTO biz_users (external_user_id, registered_at, default_region_code, status)
                VALUES (:external_user_id, :registered_at, :default_region_code, :status)
            """),
            {
                'external_user_id': row['external_user_id'],
                'registered_at': parse_datetime(row['registered_at']),
                'default_region_code': row.get('default_region_code') or None,
                'status': row.get('status', 'active')
            }
        )

    await session.commit()
    print(f"  [OK] biz_users 导入完成")


async def import_products(session: AsyncSession, csv_dir: str):
    """导入商品数据"""
    filepath = os.path.join(csv_dir, 'products.csv')
    if not os.path.exists(filepath):
        print("  [SKIP] products.csv 不存在")
        return

    rows = load_csv(filepath)
    print(f"  导入 products: {len(rows)} 行...")

    for row in rows:
        await session.execute(
            text("""
                INSERT INTO products (external_product_id, store_id, product_name, category_code, current_price, status)
                VALUES (:external_product_id, :store_id, :product_name, :category_code, :current_price, :status)
            """),
            {
                'external_product_id': row['external_product_id'],
                'store_id': row.get('store_id', 'store_001'),
                'product_name': row['product_name'],
                'category_code': row['category_code'],
                'current_price': parse_float(row['current_price']) or 0,
                'status': row.get('status', 'active')
            }
        )

    await session.commit()
    print(f"  [OK] products 导入完成")


async def import_sessions(session: AsyncSession, csv_dir: str, user_map: dict):
    """导入会话数据"""
    filepath = os.path.join(csv_dir, 'sessions.csv')
    if not os.path.exists(filepath):
        print("  [SKIP] sessions.csv 不存在")
        return

    rows = load_csv(filepath)
    print(f"  导入 sessions: {len(rows)} 行...")

    for row in rows:
        # 查找用户ID
        user_id = user_map.get(row.get('user_external_id'))

        await session.execute(
            text("""
                INSERT INTO sessions
                (session_key, store_id, user_id, channel, device_type, region_code,
                 user_type_snapshot, started_at, ended_at, is_bot, source_meta_json)
                VALUES
                (:session_key, :store_id, :user_id, :channel, :device_type, :region_code,
                 :user_type_snapshot, :started_at, :ended_at, :is_bot, :source_meta_json)
            """),
            {
                'session_key': row['session_key'],
                'store_id': row.get('store_id', 'store_001'),
                'user_id': user_id,
                'channel': row['channel'],
                'device_type': row['device_type'],
                'region_code': row.get('region_code') or None,
                'user_type_snapshot': row['user_type_snapshot'],
                'started_at': parse_datetime(row['started_at']),
                'ended_at': parse_datetime(row.get('ended_at')),
                'is_bot': parse_bool(row.get('is_bot', 'false')),
                'source_meta_json': row.get('source_meta_json', '{}')
            }
        )

    await session.commit()
    print(f"  [OK] sessions 导入完成")


async def import_visit_events(session: AsyncSession, csv_dir: str, session_map: dict, product_map: dict):
    """导入访问事件"""
    filepath = os.path.join(csv_dir, 'visit_events.csv')
    if not os.path.exists(filepath):
        print("  [SKIP] visit_events.csv 不存在")
        return

    rows = load_csv(filepath)
    print(f"  导入 visit_events: {len(rows)} 行...")

    batch_size = 1000
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i+batch_size]
        for row in batch:
            session_id = session_map.get(row.get('session_key'))
            product_id = product_map.get(row.get('product_external_id'))

            await session.execute(
                text("""
                    INSERT INTO visit_events
                    (source_event_id, session_id, product_id, page_type, occurred_at, metadata_json)
                    VALUES
                    (:source_event_id, :session_id, :product_id, :page_type, :occurred_at, :metadata_json)
                """),
                {
                    'source_event_id': row['source_event_id'],
                    'session_id': session_id,
                    'product_id': product_id,
                    'page_type': row['page_type'],
                    'occurred_at': parse_datetime(row['occurred_at']),
                    'metadata_json': row.get('metadata_json', '{}')
                }
            )

        await session.commit()
        print(f"    已导入 {min(i+batch_size, len(rows))}/{len(rows)}")

    print(f"  [OK] visit_events 导入完成")


async def import_cart_events(session: AsyncSession, csv_dir: str, session_map: dict, product_map: dict):
    """导入加购事件"""
    filepath = os.path.join(csv_dir, 'cart_events.csv')
    if not os.path.exists(filepath):
        print("  [SKIP] cart_events.csv 不存在")
        return

    rows = load_csv(filepath)
    print(f"  导入 cart_events: {len(rows)} 行...")

    for row in rows:
        session_id = session_map.get(row.get('session_key'))
        product_id = product_map.get(row.get('product_external_id'))

        await session.execute(
            text("""
                INSERT INTO cart_events
                (source_event_id, session_id, product_id, action, quantity, occurred_at, metadata_json)
                VALUES
                (:source_event_id, :session_id, :product_id, :action, :quantity, :occurred_at, :metadata_json)
            """),
            {
                'source_event_id': row['source_event_id'],
                'session_id': session_id,
                'product_id': product_id,
                'action': row['action'],
                'quantity': parse_int(row['quantity']) or 1,
                'occurred_at': parse_datetime(row['occurred_at']),
                'metadata_json': row.get('metadata_json', '{}')
            }
        )

    await session.commit()
    print(f"  [OK] cart_events 导入完成")


async def import_orders(session: AsyncSession, csv_dir: str, session_map: dict, user_map: dict, product_map: dict):
    """导入订单数据"""
    filepath = os.path.join(csv_dir, 'orders.csv')
    if not os.path.exists(filepath):
        print("  [SKIP] orders.csv 不存在")
        return

    rows = load_csv(filepath)
    print(f"  导入 orders: {len(rows)} 行...")

    for row in rows:
        session_id = session_map.get(row.get('session_key'))
        user_id = user_map.get(row.get('user_external_id'))
        product_id = product_map.get(row.get('product_external_id'))

        await session.execute(
            text("""
                INSERT INTO orders
                (order_no, session_id, user_id, product_id, order_status, quantity,
                 unit_price, order_amount, created_at, paid_at, completed_at, cancelled_at)
                VALUES
                (:order_no, :session_id, :user_id, :product_id, :order_status, :quantity,
                 :unit_price, :order_amount, :created_at, :paid_at, :completed_at, :cancelled_at)
            """),
            {
                'order_no': row['order_no'],
                'session_id': session_id,
                'user_id': user_id,
                'product_id': product_id,
                'order_status': row['order_status'],
                'quantity': parse_int(row['quantity']) or 1,
                'unit_price': parse_float(row['unit_price']) or 0,
                'order_amount': parse_float(row['order_amount']) or 0,
                'created_at': parse_datetime(row['created_at']),
                'paid_at': parse_datetime(row.get('paid_at')),
                'completed_at': parse_datetime(row.get('completed_at')),
                'cancelled_at': parse_datetime(row.get('cancelled_at'))
            }
        )

    await session.commit()
    print(f"  [OK] orders 导入完成")


async def import_business_events(session: AsyncSession, csv_dir: str):
    """导入业务事件"""
    filepath = os.path.join(csv_dir, 'business_events.csv')
    if not os.path.exists(filepath):
        print("  [SKIP] business_events.csv 不存在")
        return

    rows = load_csv(filepath)
    print(f"  导入 business_events: {len(rows)} 行...")

    for row in rows:
        await session.execute(
            text("""
                INSERT INTO business_events
                (event_code, store_id, event_type, title, description,
                 started_at, ended_at, scope_json, severity, source_type)
                VALUES
                (:event_code, :store_id, :event_type, :title, :description,
                 :started_at, :ended_at, :scope_json, :severity, :source_type)
            """),
            {
                'event_code': row['event_code'],
                'store_id': row.get('store_id', 'store_001'),
                'event_type': row['event_type'],
                'title': row['title'],
                'description': row['description'],
                'started_at': parse_datetime(row['started_at']),
                'ended_at': parse_datetime(row.get('ended_at')),
                'scope_json': row.get('scope_json', '{}'),
                'severity': row.get('severity', 'medium'),
                'source_type': row['source_type']
            }
        )

    await session.commit()
    print(f"  [OK] business_events 导入完成")


async def load_id_maps(session: AsyncSession) -> tuple:
    """加载 ID 映射（CSV中的外部ID -> 数据库内部ID）"""

    # 用户映射
    result = await session.execute(text("SELECT id, external_user_id FROM biz_users"))
    user_map = {row[1]: row[0] for row in result}

    # 商品映射
    result = await session.execute(text("SELECT id, external_product_id FROM products"))
    product_map = {row[1]: row[0] for row in result}

    # 会话映射
    result = await session.execute(text("SELECT id, session_key FROM sessions"))
    session_map = {row[1]: row[0] for row in result}

    return user_map, product_map, session_map


async def main():
    """主函数"""
    print("=" * 50)
    print("经营归因分析系统 - 演示数据导入")
    print("=" * 50)

    # CSV 目录
    base_dir = os.path.dirname(os.path.abspath(__file__))
    csv_dir = os.path.join(base_dir, 'csv_export')

    if not os.path.exists(csv_dir):
        print(f"错误: 找不到 CSV 目录 {csv_dir}")
        print("请先运行 02_seed_data.py 生成数据")
        return

    # 连接数据库
    url = build_database_url()
    engine = create_async_engine(url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        print("\n[1/3] 导入基础数据...")
        await import_biz_users(session, csv_dir)
        await import_products(session, csv_dir)

        print("\n[2/3] 导入会话数据...")
        user_map, product_map, session_map = await load_id_maps(session)
        await import_sessions(session, csv_dir, user_map)

        # 重新加载会话映射
        _, _, session_map = await load_id_maps(session)

        print("\n[3/3] 导入事件数据...")
        await import_visit_events(session, csv_dir, session_map, product_map)
        await import_cart_events(session, csv_dir, session_map, product_map)
        await import_orders(session, csv_dir, session_map, user_map, product_map)
        await import_business_events(session, csv_dir)

    await engine.dispose()

    print("\n" + "=" * 50)
    print("数据导入完成！")
    print("=" * 50)

    # 统计
    engine2 = create_async_engine(url, echo=False)
    async with engine2.connect() as conn:
        for table in ['biz_users', 'products', 'sessions', 'visit_events', 'cart_events', 'orders', 'business_events']:
            result = await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
            count = result.scalar()
            print(f"  {table}: {count} 行")
    await engine2.dispose()


if __name__ == "__main__":
    asyncio.run(main())
