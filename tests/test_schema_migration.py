"""旧持久化库升级到当前工作台结构的回归测试。"""

from sqlalchemy import create_engine, inspect, text

from app.persistence.service import AnalysisPersistenceService


def test_legacy_websocket_token_table_is_upgraded_before_issuing_new_tokens(tmp_path):
    """旧表缺少绑定字段时，启动迁移不能让 /chat/ws-token 变成 500。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.sqlite'}")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE websocket_tokens (
                id VARCHAR(64) PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                task_id VARCHAR(64) NOT NULL,
                expires_at DATETIME NOT NULL,
                created_at DATETIME NOT NULL
            )
        """))
        connection.execute(text("""
            INSERT INTO websocket_tokens (id, user_id, task_id, expires_at, created_at)
            VALUES ('legacy-token', 'legacy-user', 'legacy-task', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """))

    service = AnalysisPersistenceService(engine)
    service.initialize_schema()

    columns = {column["name"] for column in inspect(engine).get_columns("websocket_tokens")}
    assert {"conversation_id", "task_id", "token", "consumed_at"}.issubset(columns)

    user = service.get_or_create_user("migration-user")
    conversation = service.create_conversation(user["user_id"], "迁移验证")
    task = service.create_task(
        conversation["conversation_id"], "验证 WebSocket 令牌", owner_id=user["user_id"]
    )

    token = service.create_websocket_token(user["user_id"], task["task_id"])
    assert service.verify_websocket_token(token, user["user_id"], task["task_id"])
