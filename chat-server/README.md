# Chat Server

基于 FastAPI 和 LangGraph 的最小后端服务，当前不与前端进行逻辑交互。

## 启动

需要先安装 [uv](https://docs.astral.sh/uv/)。项目使用 uv 管理 Python、虚拟环境和依赖。

```bash
uv sync
uv run uvicorn app.main:app --reload
```

新增依赖时使用 `uv add <package>`，移除依赖时使用 `uv remove <package>`。

运行测试：

```bash
uv run pytest
```

启动后可访问：

- `GET /`：服务基本信息
- `GET /health`：健康检查
- `POST /agent/chat`：提交 `thread_id` 和用户消息，并写入 SQLite checkpoint
- `GET /agent/history?thread_id=...`：从 SQLite checkpoint 查询对应会话历史
- `GET /docs`：FastAPI 自动生成的接口文档

checkpoint 默认保存在 `data/checkpoints.sqlite`，可通过 `SQLITE_PATH` 环境变量修改。
