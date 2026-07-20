# 经营归因分析系统 - 数据基础设施

本目录包含客户行为分析场景的数据库设计和演示数据。

## 目录结构

```
data_compose/
├── 01_schema.sql           # PostgreSQL 建表脚本
├── 02_seed_data.py         # 演示数据生成器
├── 03_quality_check.py     # 数据质量检查脚本
├── 04_expected_stats.py    # 预期统计结果
├── README.md               # 本文件
├── sql_inserts/            # 生成的 SQL INSERT 语句
├── csv_export/             # 导出的 CSV 文件
├── metadata.json           # 数据生成元数据
├── quality_report.txt      # 数据质量报告
└── expected_stats_report.txt  # 预期统计报告
```

## 快速开始

### 1. 生成演示数据

```bash
cd D:\dev\归因分析\data_compose
python 02_seed_data.py
```

这将生成：
- `sql_inserts/` 目录：包含 7 张表的 SQL INSERT 语句
- `csv_export/` 目录：包含 7 张表的 CSV 文件
- `metadata.json`：数据生成元数据

### 2. 检查数据质量

```bash
python 03_quality_check.py
```

检查项包括：
- 唯一性约束
- 外键完整性
- 时间合理性
- 业务规则
- 漏斗一致性

### 3. 查看预期统计结果

```bash
python 04_expected_stats.py
```

输出：
- 基准期/当前期整体漏斗
- 按渠道、设备、地区、商品拆解
- 预期的归因结论

## 数据库表设计

### 业务数据表（7张）

| 表名 | 用途 |
|------|------|
| `biz_users` | 业务用户表（被分析的电商用户） |
| `products` | 商品表 |
| `sessions` | 访问会话表（漏斗核心） |
| `visit_events` | 访问事件表 |
| `cart_events` | 加购事件表 |
| `orders` | 订单表 |
| `business_events` | 业务事件表（关联可能原因） |

### 漏斗定义

```
访问会话 → 加购会话 → 下单会话
```

- **访问会话**：存在至少一条访问事件的会话
- **加购会话**：存在至少一条 `action='add'` 的加购事件
- **下单会话**：存在至少一条 `order_status IN ('paid', 'completed')` 的订单

### 漏斗指标

- **加购率** = 加购会话数 / 访问会话数
- **下单转化率** = 下单会话数 / 访问会话数
- **加购后下单率** = 下单会话数 / 加购会话数

满足：加购率 × 加购后下单率 = 下单转化率

## 时间范围

- **基准期**：2026-06-01 ~ 2026-06-15
- **当前期**：2026-07-01 ~ 2026-07-15

时间归属以 `sessions.started_at` 为准，左闭右开。

## 植入的异常

演示数据故意植入以下异常，用于验证归因系统：

### 1. 抖音渠道低质量流量
- 现象：流量上涨 40%，但转化率下降 50%
- 原因：大规模投放活动带来低质量流量
- 关联事件：`evt_douyin_campaign`

### 2. 商品库存问题
- 现象：prod_001（无线蓝牙耳机）加购后下单率极低
- 原因：库存紧张，部分 SKU 无货
- 关联事件：`evt_prod001_stockout`

### 3. 移动端支付异常
- 现象：mobile_web 设备支付成功率下降
- 原因：结算页加载超时
- 关联事件：`evt_mobile_checkout_bug`

### 4. 华东地区配送延迟
- 现象：华东地区整体转化率下降
- 原因：物流配送延迟
- 关联事件：`evt_east_delivery_delay`

## 用户类型定义

- **新用户 (new)**：会话开始时间 - 注册时间 ≤ 7 天
- **老用户 (returning)**：会话开始时间 - 注册时间 > 7 天

用户类型在会话创建时确定，保存到 `sessions.user_type_snapshot`。

## 渠道和设备

### 渠道（channel）
- `organic`：自然搜索
- `search_ads`：搜索广告
- `douyin`：抖音渠道
- `direct`：直接访问
- `affiliate`：联盟推广
- `other`：其他

### 设备类型（device_type）
- `app`：移动 App
- `mobile_web`：移动网页
- `pc`：桌面端

## 业务事件说明

`business_events` 表记录可能影响业务的事件，用于关联归因分析。

事件只能作为关联证据，不能单独证明因果关系。

### scope_json 格式

```json
{
  "channel": ["douyin"],
  "device_type": ["mobile_web"],
  "page_type": ["checkout"],
  "region_code": ["east_china"],
  "product_id": ["prod_001"]
}
```

## 数据导入

### PostgreSQL

```bash
# 1. 创建数据库
createdb attribution_db

# 2. 执行建表脚本
psql -d attribution_db -f 01_schema.sql

# 3. 导入数据（按顺序）
psql -d attribution_db -f sql_inserts/01_biz_users.sql
psql -d attribution_db -f sql_inserts/02_products.sql
psql -d attribution_db -f sql_inserts/03_sessions.sql
psql -d attribution_db -f sql_inserts/04_visit_events.sql
psql -d attribution_db -f sql_inserts/05_cart_events.sql
psql -d attribution_db -f sql_inserts/06_orders.sql
psql -d attribution_db -f sql_inserts/07_business_events.sql
```

### SQLite（开发环境）

可以使用 Python 脚本将 CSV 导入 SQLite。

## 注意事项

1. **价格历史**：商品当前价格保存在 `products.current_price`，订单发生时的价格保存在 `orders.unit_price`
2. **用户类型**：同一用户在不同时期可能是新用户或老用户，以会话时间判断
3. **机器人流量**：分析时应排除 `sessions.is_bot = true` 的会话
4. **样本量**：分组样本量低于 100 的分组只展示，不作为主要归因结论
