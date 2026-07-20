-- ============================================================
-- 经营归因分析系统 - 业务数据表（客户行为分析场景）
-- 数据库：PostgreSQL 14+
-- 时间范围：左闭右开 [start, end)
-- 统一时区：UTC
-- ============================================================

-- 清理已有表（开发环境用）
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS cart_events CASCADE;
DROP TABLE IF EXISTS visit_events CASCADE;
DROP TABLE IF EXISTS sessions CASCADE;
DROP TABLE IF EXISTS business_events CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS biz_users CASCADE;

-- ============================================================
-- 1. biz_users：业务用户表（被分析的电商用户）
-- ============================================================
CREATE TABLE biz_users (
    id              BIGSERIAL PRIMARY KEY,
    external_user_id VARCHAR(64) NOT NULL UNIQUE,
    registered_at   TIMESTAMPTZ NOT NULL,
    default_region_code VARCHAR(32),
    status          VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_biz_users_status CHECK (status IN ('active', 'disabled'))
);

COMMENT ON TABLE biz_users IS '业务用户表（被分析的电商用户）';
COMMENT ON COLUMN biz_users.external_user_id IS '业务用户编号';
COMMENT ON COLUMN biz_users.registered_at IS '注册时间（用于判断新老用户）';
COMMENT ON COLUMN biz_users.default_region_code IS '默认地区编码';
COMMENT ON COLUMN biz_users.status IS '状态：active/disabled';

-- ============================================================
-- 2. products：商品表
-- ============================================================
CREATE TABLE products (
    id              BIGSERIAL PRIMARY KEY,
    external_product_id VARCHAR(64) NOT NULL UNIQUE,
    store_id        VARCHAR(64) NOT NULL,
    product_name    VARCHAR(200) NOT NULL,
    category_code   VARCHAR(64) NOT NULL,
    current_price   NUMERIC(12,2) NOT NULL DEFAULT 0,
    status          VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_products_price CHECK (current_price >= 0),
    CONSTRAINT chk_products_status CHECK (status IN ('active', 'inactive'))
);

COMMENT ON TABLE products IS '商品表';
COMMENT ON COLUMN products.current_price IS '当前展示价格（历史价格保存在orders中）';
COMMENT ON COLUMN products.category_code IS '商品类目编码';

-- ============================================================
-- 3. sessions：访问会话表（漏斗核心）
-- ============================================================
CREATE TABLE sessions (
    id              BIGSERIAL PRIMARY KEY,
    session_key     VARCHAR(64) NOT NULL UNIQUE,
    store_id        VARCHAR(64) NOT NULL,
    user_id         BIGINT REFERENCES biz_users(id),
    channel         VARCHAR(32) NOT NULL,
    device_type     VARCHAR(20) NOT NULL,
    region_code     VARCHAR(32),
    user_type_snapshot VARCHAR(16) NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ,
    is_bot          BOOLEAN NOT NULL DEFAULT FALSE,
    source_meta_json JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_sessions_channel CHECK (channel IN (
        'organic', 'search_ads', 'douyin', 'direct', 'affiliate', 'other'
    )),
    CONSTRAINT chk_sessions_device CHECK (device_type IN (
        'app', 'mobile_web', 'pc'
    )),
    CONSTRAINT chk_sessions_user_type CHECK (user_type_snapshot IN ('new', 'returning'))
);

COMMENT ON TABLE sessions IS '访问会话表（漏斗核心）';
COMMENT ON COLUMN sessions.session_key IS '前端或业务系统生成的会话编号';
COMMENT ON COLUMN sessions.channel IS '流量渠道：organic/search_ads/douyin/direct/affiliate/other';
COMMENT ON COLUMN sessions.device_type IS '设备类型：app/mobile_web/pc';
COMMENT ON COLUMN sessions.user_type_snapshot IS '用户类型快照：new/returning';
COMMENT ON COLUMN sessions.is_bot IS '是否机器人流量（分析时排除）';
COMMENT ON COLUMN sessions.source_meta_json IS '活动、UTM、广告计划等扩展信息';

-- ============================================================
-- 4. visit_events：访问事件表
-- ============================================================
CREATE TABLE visit_events (
    id              BIGSERIAL PRIMARY KEY,
    source_event_id VARCHAR(64) NOT NULL UNIQUE,
    session_id      BIGINT NOT NULL REFERENCES sessions(id),
    product_id      BIGINT REFERENCES products(id),
    page_type       VARCHAR(32) NOT NULL,
    occurred_at     TIMESTAMPTZ NOT NULL,
    metadata_json   JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE visit_events IS '访问事件表';
COMMENT ON COLUMN visit_events.page_type IS '页面类型：home/product/checkout/search等';
COMMENT ON COLUMN visit_events.occurred_at IS '事件发生时间';

-- ============================================================
-- 5. cart_events：加购事件表
-- ============================================================
CREATE TABLE cart_events (
    id              BIGSERIAL PRIMARY KEY,
    source_event_id VARCHAR(64) NOT NULL UNIQUE,
    session_id      BIGINT NOT NULL REFERENCES sessions(id),
    product_id      BIGINT NOT NULL REFERENCES products(id),
    action          VARCHAR(16) NOT NULL,
    quantity        INTEGER NOT NULL DEFAULT 1,
    occurred_at     TIMESTAMPTZ NOT NULL,
    metadata_json   JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_cart_action CHECK (action IN ('add', 'remove', 'update')),
    CONSTRAINT chk_cart_quantity CHECK (quantity > 0)
);

COMMENT ON TABLE cart_events IS '加购事件表';
COMMENT ON COLUMN cart_events.action IS '操作类型：add/remove/update';

-- ============================================================
-- 6. orders：订单表（第一版一单一商品）
-- ============================================================
CREATE TABLE orders (
    id              BIGSERIAL PRIMARY KEY,
    order_no        VARCHAR(64) NOT NULL UNIQUE,
    session_id      BIGINT NOT NULL REFERENCES sessions(id),
    user_id         BIGINT NOT NULL REFERENCES biz_users(id),
    product_id      BIGINT NOT NULL REFERENCES products(id),
    order_status    VARCHAR(20) NOT NULL,
    quantity        INTEGER NOT NULL DEFAULT 1,
    unit_price      NUMERIC(12,2) NOT NULL DEFAULT 0,
    order_amount    NUMERIC(12,2) NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL,
    paid_at         TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    cancelled_at    TIMESTAMPTZ,

    CONSTRAINT chk_orders_status CHECK (order_status IN (
        'created', 'paid', 'completed', 'cancelled', 'refunded'
    )),
    CONSTRAINT chk_orders_quantity CHECK (quantity > 0),
    CONSTRAINT chk_orders_unit_price CHECK (unit_price >= 0),
    CONSTRAINT chk_orders_amount CHECK (order_amount >= 0)
);

COMMENT ON TABLE orders IS '订单表（第一版一单一商品）';
COMMENT ON COLUMN orders.order_status IS '订单状态：created/paid/completed/cancelled/refunded';
COMMENT ON COLUMN orders.unit_price IS '下单时单价（不随商品改价变化）';
COMMENT ON COLUMN orders.order_amount IS '实际订单金额';

-- ============================================================
-- 7. business_events：业务事件表（关联可能原因）
-- ============================================================
CREATE TABLE business_events (
    id              BIGSERIAL PRIMARY KEY,
    event_code      VARCHAR(64) NOT NULL UNIQUE,
    store_id        VARCHAR(64) NOT NULL,
    event_type      VARCHAR(32) NOT NULL,
    title           VARCHAR(200) NOT NULL,
    description     TEXT NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ,
    scope_json      JSONB NOT NULL DEFAULT '{}',
    severity        VARCHAR(16) NOT NULL DEFAULT 'medium',
    source_type     VARCHAR(32) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_biz_events_severity CHECK (severity IN ('low', 'medium', 'high'))
);

COMMENT ON TABLE business_events IS '业务事件表（关联可能原因）';
COMMENT ON COLUMN business_events.scope_json IS '影响范围：渠道、设备、商品等';
COMMENT ON COLUMN business_events.severity IS '严重程度：low/medium/high';

-- ============================================================
-- 索引
-- ============================================================

-- sessions 索引（漏斗查询核心）
CREATE INDEX idx_sessions_store_time ON sessions(store_id, started_at);
CREATE INDEX idx_sessions_channel_time ON sessions(channel, started_at);
CREATE INDEX idx_sessions_device_time ON sessions(device_type, started_at);
CREATE INDEX idx_sessions_region_time ON sessions(region_code, started_at);
CREATE INDEX idx_sessions_user_type_time ON sessions(user_type_snapshot, started_at);

-- visit_events 索引
CREATE INDEX idx_visit_session_time ON visit_events(session_id, occurred_at);
CREATE INDEX idx_visit_product_time ON visit_events(product_id, occurred_at);

-- cart_events 索引
CREATE INDEX idx_cart_session_time ON cart_events(session_id, occurred_at);
CREATE INDEX idx_cart_product_time ON cart_events(product_id, occurred_at);

-- orders 索引
CREATE INDEX idx_orders_session_status ON orders(session_id, order_status);
CREATE INDEX idx_orders_product_time ON orders(product_id, paid_at);
CREATE INDEX idx_orders_created ON orders(created_at);

-- business_events 索引
CREATE INDEX idx_biz_events_store_time ON business_events(store_id, started_at, ended_at);
CREATE INDEX idx_biz_events_scope ON business_events USING GIN (scope_json);
