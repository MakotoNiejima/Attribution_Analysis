"""
数据库初始化脚本
=============
使用 SQLAlchemy 自动创建业务数据表。

使用方式：
    cd D:\dev\归因分析\data_compose
    python init_db.py
"""

import asyncio
import sys
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import BigInteger, String, Integer, Numeric, Boolean, Text, DateTime, Date, JSON, ForeignKey, func
from datetime import datetime, date


# 以项目统一 .env 为唯一凭证来源，避免在初始化脚本中保留明文密码。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME


def build_database_url(database: str = None) -> str:
    """构建数据库连接 URL"""
    password = quote_plus(DB_PASSWORD)
    db = database or DB_NAME
    return f"mysql+aiomysql://{DB_USER}:{password}@{DB_HOST}:{DB_PORT}/{db}?charset=utf8mb4"


# ============================================================
# SQLAlchemy 模型定义
# ============================================================

class Base(DeclarativeBase):
    pass


class BizUser(Base):
    """业务用户表（被分析的电商用户）"""
    __tablename__ = "biz_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    external_user_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="业务用户编号")
    registered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="注册时间")
    default_region_code: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="默认地区编码")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", comment="状态")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")


class Product(Base):
    """商品表"""
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    external_product_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="商品业务编号")
    store_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="所属店铺")
    product_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="商品名称")
    category_code: Mapped[str] = mapped_column(String(64), nullable=False, comment="商品类目")
    current_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0, comment="当前价格")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", comment="状态")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class Session(Base):
    """访问会话表（漏斗核心）"""
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="会话编号")
    store_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="所属店铺")
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("biz_users.id"), nullable=True, comment="用户ID")
    channel: Mapped[str] = mapped_column(String(32), nullable=False, comment="流量渠道")
    device_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="设备类型")
    region_code: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="地区编码")
    user_type_snapshot: Mapped[str] = mapped_column(String(16), nullable=False, comment="用户类型快照")
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="会话开始时间")
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="会话结束时间")
    is_bot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="是否机器人")
    source_meta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict, comment="扩展信息")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class VisitEvent(Base):
    """访问事件表"""
    __tablename__ = "visit_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_event_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="事件ID")
    session_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sessions.id"), nullable=False, comment="会话ID")
    product_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=True, comment="商品ID")
    page_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="页面类型")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="事件时间")
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class CartEvent(Base):
    """加购事件表"""
    __tablename__ = "cart_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_event_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="事件ID")
    session_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sessions.id"), nullable=False, comment="会话ID")
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=False, comment="商品ID")
    action: Mapped[str] = mapped_column(String(16), nullable=False, comment="操作类型")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1, comment="数量")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="事件时间")
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class Order(Base):
    """订单表"""
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="订单编号")
    session_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sessions.id"), nullable=False, comment="会话ID")
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("biz_users.id"), nullable=False, comment="用户ID")
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=False, comment="商品ID")
    order_status: Mapped[str] = mapped_column(String(20), nullable=False, comment="订单状态")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1, comment="数量")
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0, comment="单价")
    order_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0, comment="订单金额")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="创建时间")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="支付时间")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="完成时间")
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="取消时间")


class BusinessEvent(Base):
    """业务事件表"""
    __tablename__ = "business_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="事件编号")
    store_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="所属店铺")
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="事件类型")
    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="事件名称")
    description: Mapped[str] = mapped_column(Text, nullable=False, comment="事件描述")
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="开始时间")
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="结束时间")
    scope_json: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict, comment="影响范围")
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium", comment="严重程度")
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="来源类型")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class Campaign(Base):
    """营销活动表"""
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    campaign_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="活动编号")
    campaign_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="活动名称")
    channel: Mapped[str] = mapped_column(String(32), nullable=False, comment="渠道")
    budget: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0, comment="预算")
    start_date: Mapped[date] = mapped_column(Date, nullable=False, comment="开始日期")
    end_date: Mapped[date] = mapped_column(Date, nullable=False, comment="结束日期")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", comment="状态")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class CampaignDailyMetric(Base):
    """营销活动日指标表"""
    __tablename__ = "campaign_daily_metrics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("campaigns.id"), nullable=False, comment="活动ID")
    metric_date: Mapped[date] = mapped_column(Date, nullable=False, comment="日期")
    impressions: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="曝光量")
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="点击量")
    conversions: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="转化数")
    revenue: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0, comment="收入")
    ad_spend: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0, comment="广告花费")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


# ============================================================
# 初始化函数
# ============================================================

async def create_database():
    """创建数据库（如果不存在）"""
    password = quote_plus(DB_PASSWORD)
    url = f"mysql+aiomysql://{DB_USER}:{password}@{DB_HOST}:{DB_PORT}?charset=utf8mb4"

    engine = create_async_engine(url)

    async with engine.connect() as conn:
        await conn.execute(
            __import__('sqlalchemy').text(
                f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
                f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )
        await conn.commit()

    await engine.dispose()
    print(f"[OK] 数据库 '{DB_NAME}' 已就绪")


async def create_tables():
    """创建所有表"""
    password = quote_plus(DB_PASSWORD)
    url = f"mysql+aiomysql://{DB_USER}:{password}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"

    engine = create_async_engine(url, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await engine.dispose()

    tables = [
        "biz_users", "products", "sessions",
        "visit_events", "cart_events", "orders", "business_events",
        "campaigns", "campaign_daily_metrics"
    ]
    print(f"[OK] 已创建 {len(tables)} 张表: {', '.join(tables)}")


async def main():
    """主函数"""
    print("=" * 50)
    print("经营归因分析系统 - 数据库初始化")
    print("=" * 50)
    print(f"目标数据库: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    print()

    # 1. 创建数据库
    await create_database()

    # 2. 创建表
    await create_tables()

    print()
    print("=" * 50)
    print("初始化完成！")
    print("=" * 50)
    print()
    print("下一步:")
    print("  python import_data.py  # 导入演示数据")


if __name__ == "__main__":
    asyncio.run(main())
