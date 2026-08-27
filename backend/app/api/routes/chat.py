"""聊天路由。

Day1：仅提供 Mock 返回，不调用真实 Agent（后续 Milestone 接入）。
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter

from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse, summary="发送聊天消息（Mock）")
async def chat(payload: ChatRequest) -> ChatResponse:
    """Day1 Mock：返回固定的模拟回复。"""
    return ChatResponse(
        message=(
            f"已收到需求：「{payload.message}」。"
            "软件工程团队已开始分析，Day1 为 Mock 响应，"
            "Agent 拆解与代码生成将在后续 Milestone 提供。"
        ),
        session_id=payload.session_id or str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc),
    )
