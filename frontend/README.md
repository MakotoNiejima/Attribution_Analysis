# 经营归因分析前端

## 本地启动

先在项目根目录启动后端：

```powershell
uv run uvicorn app.main:app --reload --port 8000
```

另开一个 PowerShell 窗口启动前端：

```powershell
cd D:\dev\归因分析\frontend
npm install
npm run dev
```

浏览器访问 `http://localhost:5173`。

开发模式下，Vite 会将 `/api` 请求代理到 `http://127.0.0.1:8000`。如要连接其他后端，在 `frontend/.env.local` 设置：

```ini
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
```

## 已实现的工作流

1. 点击“新建会话”，输入问题并提交。
2. 后端创建 `running` 任务，LangGraph 完成后将其持久化为 `clarify`、`completed` 或 `failed`。
3. 前端通过 WebSocket 订阅 LangGraph 节点和归因计算细节；浏览器晚于任务连接时会补发已缓存事件。
4. 左侧“会话历史”展示持久化会话；打开任意任务可回放已保存的报告和结构化结果。

首次启动后端时会自动创建 `conversations`、`analysis_tasks`、`analysis_results` 三张表，业务数据表不会被修改。

如果前端和 API 不在同一域名，除了 `VITE_API_BASE_URL` 外，还可以在 `frontend/.env.local` 配置 WebSocket 基地址：

```ini
VITE_WS_BASE_URL=ws://127.0.0.1:8000/api/v1
```
