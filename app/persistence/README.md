# 分析记录持久化

数据库中的三层关系如下：

```text
conversations (一个连续提问的会话)
  └── analysis_tasks (一次分析请求及其终态)
        └── analysis_results (仅保存证据校验通过的最终结果)
```

服务启动时会自动创建缺失表，不会删除或重建已有的业务数据表。任务状态依次为 `running`，再收束为 `clarify`、`completed` 或 `failed`。

主要读取接口：

- `GET /api/v1/conversations`
- `GET /api/v1/conversations/{conversation_id}/tasks`
- `GET /api/v1/tasks/{task_id}`
