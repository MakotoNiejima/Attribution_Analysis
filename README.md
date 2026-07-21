# 经营归因分析系统

一个以真实客户行为数据为事实来源的 LangGraph 分析工作台。系统把“自然语言提问 → 漏斗/维度拆解 → 证据校验 → 可追溯报告”串成完整流程，并支持多轮会话、附件证据、实时任务进度和结果导出。

## 已完成的业务场景

1. 整体转化异常归因：比较基准期与当前期，拆解访问→加购→下单漏斗，并关联经营事件。
2. 渠道与设备深挖：按渠道、设备、地区和新老用户分组，区分流量结构效应与转化表现效应，定位贡献最大的异常分组。

这两个场景共用同一套真实行为表，但回答的是不同业务问题；第二个场景不是把第一份报告换一个标题。

## 系统结构

```text
React 工作台
  ├─ 会话 / 历史消息 / 附件 / 结果导出
  └─ WebSocket 实时步骤
          │
FastAPI
  ├─ 本地登录与会话权限
  ├─ 任务、结果、日志、配置、附件 API
  └─ LangGraph 编排
          │
分析内核（SQLAlchemy + MySQL）
  ├─ cohort / 漏斗 / 维度分解 / 经营事件
  └─ 证据集合与报告校验
          │
可选 RAG（文档解析、分块、向量或 NumPy 检索）
```

RAG 是补充背景资料的可选能力，数据结论仍以分析内核生成的结构化证据为准。
文档检索默认使用 NumPy 精确内积检索；只有在已验证 FAISS 与当前平台兼容时，
才在 `.env` 中设置 `RAG_VECTOR_BACKEND=faiss`。

## 本地启动

1. 复制 `.env.example` 为 `.env`，填写数据库与模型配置。
2. 安装依赖：`uv sync`
3. 如果还没有业务数据，初始化并导入演示数据：

```bash
uv run python datacompose/init_db.py
uv run python datacompose/02_seed_data.py
uv run python datacompose/import_data.py
```

已有 `sessions`、`visit_events`、`cart_events`、`orders` 和
`business_events` 等业务表时跳过此步。后端首次启动会自动创建用户、
会话、任务、消息、附件和日志等工作台表。

4. 启动后端：`uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
5. 另开终端启动前端：

```bash
cd frontend
npm install
npm run dev
```

打开 `http://localhost:5174`。开发模式下未配置 `AUTH_REQUIRED=true` 时会自动创建一个本地分析用户；也可通过登录页切换账号。生产环境必须修改 `AUTH_SECRET` 并启用真实身份提供方。

## 验证

```bash
uv run python -m pytest -q
cd frontend
npm run build
```

主要接口、WebSocket 消息约定和运行顺序见 [docs/API.md](docs/API.md)，两个演示场景的操作与验收点见 [docs/DEMO_SCENARIOS.md](docs/DEMO_SCENARIOS.md)。

## 容器化运行

确认 `.env` 中已设置安全的 `DB_PASSWORD`、`OPENAI_API_KEY` 和 `AUTH_SECRET` 后：

```powershell
docker compose up --build
```

首次启动后，在另一个终端执行初始化和演示数据导入：

```powershell
docker compose exec backend python datacompose/init_db.py
docker compose exec backend python datacompose/02_seed_data.py
docker compose exec backend python datacompose/import_data.py
```

浏览器访问 `http://localhost:8080`。Docker 环境中的前端会通过 Nginx 代理 `/api` 与 `/auth` 到后端。
