"""健康检查相关 Pydantic 模型。"""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """健康检查响应模型。"""

    status: str = Field(description="服务状态", examples=["ok"])
    version: str = Field(description="服务版本", examples=["0.1.0"])
    environment: str = Field(description="运行环境", examples=["development"])
