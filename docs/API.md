# 工作台 API 说明

## 认证

- `POST /auth/login`：本地课程账号登录，写入 HttpOnly Cookie。
- `GET /auth/callback`：保留 OAuth 风格回调入口。
- `GET /auth/me`：当前用户。
- `POST /auth/logout`：清除登录 Cookie。

`AUTH_REQUIRED=false` 时，未携带凭证的本地请求会使用开发分析用户；线上应设为 `true`，并替换 callback 的身份校验。

## 会话与任务

- `POST /api/chat/create`：创建会话。
- `GET /api/chat/ls`：当前用户会话列表。
- `GET /api/chat/ls/{conversation_id}`：消息、任务和附件回放。
- `PATCH /api/chat/{conversation_id}`：重命名。
- `DELETE /api/chat/{conversation_id}`：级联删除会话记录及运行目录内文件。
- `POST /api/chat/{conversation_id}/messages`：创建一个后台分析任务。
- `GET /api/tasks/{task_id}`：读取任务及结构化结果。
- `POST /api/tasks/{task_id}/cancel`：请求协作式取消。
- `GET /api/tasks/{task_id}/logs`：任务节点与异常日志。
- `GET /api/results/{task_id}/export`：下载六段式 Markdown 报告。

任务状态：`running`、`clarify`、`completed`、`failed`、`cancelled`。同一会话只允许一个 `running` 任务。

## 实时连接

1. 调用 `POST /api/chat/ws-token`，请求体为 `{"task_id": "..."}`。
2. 连接 `WS /api/chat/ws/chat?task_id=...&token=...`。

服务端发送：`message_start`、`task_status`、`tool_start`、`tool_finish`、`result_ready`、`error`、`done`。短期令牌绑定一个用户和一个任务；服务进程重启后仍可通过任务详情回放最终状态。

## 附件与文档

- `POST /api/v1/attachments/upload`：上传 CSV/XLSX/XLS/TXT 表格附件；需提供 multipart 字段 `conversation_id`。
- `GET /api/v1/attachments?conversation_id=...`：当前会话附件。
- `GET /api/v1/attachments/{id}`：表头和预览。
- `POST /api/v1/attachments/{id}/query`、`/aggregate`：受控查询/聚合。
- `GET /api/v1/attachments/{id}/download`、`DELETE /api/v1/attachments/{id}`：下载/删除。
- `/api/v1/documents/*`：可选 RAG 文档库接口（PDF、DOCX、XLSX、TXT、MD、CSV）。

附件原件仅保存到 `runtime_data/uploads/{user}/{conversation}/`；运行期目录和 `.env` 都不应提交。

## 管理

- `POST /api/admin/reload`：管理员重新读取 `.env` 的非敏感运行配置。
- `GET` / `PUT /api/admin/config`：读取/写入工作台配置覆盖记录。

所有响应均不会返回数据库密码或模型密钥。
