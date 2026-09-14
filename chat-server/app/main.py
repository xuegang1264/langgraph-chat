from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.agent.mainGraph.chat import build_chat_graph
from app.api.routes import router
from app.core.config import settings


def create_app(sqlite_path: str | None = None) -> FastAPI:
    checkpoint_path = Path(sqlite_path or settings.sqlite_path)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as checkpointer:
            application.state.chat_graph = build_chat_graph(checkpointer)
            yield

    application = FastAPI(
        title=settings.app_name,
        description="基于 FastAPI 和 LangGraph 的聊天后端服务。",
        version=settings.app_version,
        lifespan=lifespan,
    )
    application.include_router(router)
    return application


app = create_app()
