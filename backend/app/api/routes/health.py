"""健康检查路由。"""

from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="服务健康检查")
async def health() -> HealthResponse:
    """返回服务运行状态与版本信息。"""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        version="0.1.0",
        environment=settings.environment,
    )
