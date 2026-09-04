"""FastAPI 应用入口。

- 创建应用实例
- 配置 CORS
- 注册路由
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import chat, health, rag
from app.core.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """应用生命周期钩子（启动/关闭）。

    后续 Milestone 将在此连接 PostgreSQL / Redis 并做优雅关闭。
    """
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="AI Software Engineering Agent — Backend API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(rag.router, prefix="/rag")
