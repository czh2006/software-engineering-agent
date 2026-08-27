"""聊天接口的 Pydantic 请求/响应模型。"""

from datetime import datetime

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """聊天请求模型（用户输入需求）。"""

    message: str = Field(
        description="用户需求/消息",
        min_length=1,
        examples=["请实现用户登录功能"],
    )
    session_id: str | None = Field(
        default=None,
        description="会话 ID（不传则由后端生成）",
    )


class ChatResponse(BaseModel):
    """聊天响应模型（Day1 为 Mock 返回）。"""

    message: str = Field(description="回复内容")
    session_id: str = Field(description="会话 ID")
    created_at: datetime = Field(description="响应时间（UTC）")
