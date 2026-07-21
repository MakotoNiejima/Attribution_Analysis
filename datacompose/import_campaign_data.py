"""
单独导入营销活动数据
用于补充市场表现分析场景的数据
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.ext.asyncio.session import async_sessionmaker
from sqlalchemy import text

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import build_sync_url


def build_async_url() -> str:
    """构建异步数据库 URL"""
    sync_url = build_sync_url()
    return sync_url.replace("mysql+pymysql://", "mysql+aiomysql://")


def load_csv(filepath: str) -> list[dict]:
    """加载 CSV 文件"""
    import csv
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def parse_float(value: str) -> float | None:
    """解析浮点数"""
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_int(value: str) -> int | None:
    """解析整数"""
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


async def import_campaigns(session: AsyncSession, csv_dir: str):
    """导入营销活动"""
    filepath = Path(csv_dir) / "campaigns.csv"
    if not filepath.exists():
        print(f"  [SKIP] campaigns.csv 不存在")
        return

    rows = load_csv(str(filepath))
    print(f"  导入 campaigns: {len(rows)} 行...")

    for row in rows:
        await session.execute(
            text("""
                INSERT INTO campaigns
                (campaign_code, campaign_name, channel, budget, start_date, end_date, status)
                VALUES
                (:campaign_code, :campaign_name, :channel, :budget, :start_date, :end_date, :status)
            """),
            {
                "campaign_code": row["campaign_code"],
                "campaign_name": row["campaign_name"],
                "channel": row["channel"],
                "budget": parse_float(row["budget"]) or 0,
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "status": row.get("status", "active"),
            },
        )

    await session.commit()
    print(f"  [OK] campaigns 导入完成")


async def import_campaign_daily_metrics(session: AsyncSession, csv_dir: str, campaign_map: dict):
    """导入营销活动日指标"""
    filepath = Path(csv_dir) / "campaign_daily_metrics.csv"
    if not filepath.exists():
        print(f"  [SKIP] campaign_daily_metrics.csv 不存在")
        return

    rows = load_csv(str(filepath))
    print(f"  导入 campaign_daily_metrics: {len(rows)} 行...")

    for row in rows:
        campaign_id = campaign_map.get(row.get("campaign_code"))
        if not campaign_id:
            continue

        await session.execute(
            text("""
                INSERT INTO campaign_daily_metrics
                (campaign_id, metric_date, impressions, clicks, conversions, revenue, ad_spend)
                VALUES
                (:campaign_id, :metric_date, :impressions, :clicks, :conversions, :revenue, :ad_spend)
            """),
            {
                "campaign_id": campaign_id,
                "metric_date": row["metric_date"],
                "impressions": parse_int(row["impressions"]) or 0,
                "clicks": parse_int(row["clicks"]) or 0,
                "conversions": parse_int(row["conversions"]) or 0,
                "revenue": parse_float(row["revenue"]) or 0,
                "ad_spend": parse_float(row["ad_spend"]) or 0,
            },
        )

    await session.commit()
    print(f"  [OK] campaign_daily_metrics 导入完成")


async def main():
    """主函数"""
    print("=" * 50)
    print("单独导入营销活动数据")
    print("=" * 50)

    csv_dir = Path(__file__).parent / "csv_export"
    if not csv_dir.exists():
        print(f"错误: 找不到 CSV 目录 {csv_dir}")
        print("请先运行 02_seed_data.py 生成数据")
        return

    url = build_async_url()
    engine = create_async_engine(url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # 1. 导入 campaigns
        print("\n[1/2] 导入营销活动...")
        await import_campaigns(session, str(csv_dir))

        # 2. 加载 campaign 映射
        result = await session.execute(text("SELECT id, campaign_code FROM campaigns"))
        campaign_map = {row[1]: row[0] for row in result.fetchall()}
        print(f"  已加载 {len(campaign_map)} 个活动映射")

        # 3. 导入 campaign_daily_metrics
        print("\n[2/2] 导入营销活动日指标...")
        await import_campaign_daily_metrics(session, str(csv_dir), campaign_map)

    await engine.dispose()

    print("\n" + "=" * 50)
    print("营销活动数据导入完成！")
    print("=" * 50)

    # 统计
    engine2 = create_async_engine(url, echo=False)
    async with engine2.connect() as conn:
        for table in ["campaigns", "campaign_daily_metrics"]:
            result = await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
            count = result.scalar()
            print(f"  {table}: {count} 行")
    await engine2.dispose()


if __name__ == "__main__":
    asyncio.run(main())
