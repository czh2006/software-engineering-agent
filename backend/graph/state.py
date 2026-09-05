"""Workflow State 定义（供 LangGraph Workflow 使用）。

早期为纯 TypedDict 占位设计；现 WorkflowState 字段类型直接使用
各 Agent 的真实 Pydantic 模型，保证节点间产出数据可实际流转。

本模块只定义类型，Workflow 编排见 graph/workflow.py。
"""

from typing import Literal, NotRequired, TypedDict

from agents.architect_agent import (
    ArchitectAction,
    ArchitectureAnalysis,
    PlannedToolCall,
    ToolCallRecord,
)
from agents.coder_agent import PatchPlan
from agents.retriever_agent import RetrievedChunk
from agents.reviewer_agent import ReviewResult
from app.schemas.workflow import TaskPlan


class TimelineEntry(TypedDict):
    """时间线条目：记录一次 Node 执行。"""

    agent_name: str  # 节点/Agent 名称（如 "PM"）
    status: Literal["running", "done", "failed"]  # 执行状态
    duration: float  # 执行耗时（秒）
    timestamp: str  # ISO8601 时间戳（UTC）


class WorkflowState(TypedDict):
    """跨 Agent 的共享工作流状态。

    除 user_request 外均由对应节点逐步写入：
    - PM 写入 task_plan
    - Architect 写入 architecture_analysis
    - Retriever 写入 retrieved_chunks
    - Coder 写入 patch_plan
    - Reviewer 写入 review_result
    - 各节点向 timeline 追加 TimelineEntry
    """

    user_request: str
    task_plan: NotRequired[TaskPlan | None]
    architecture_analysis: NotRequired[ArchitectureAnalysis | None]
    retrieved_chunks: NotRequired[list[RetrievedChunk]]
    patch_plan: NotRequired[PatchPlan | None]
    review_result: NotRequired[ReviewResult | None]

    # Architect Tool Loop 字段（graph/architect_loop.py 读写）
    tool_calls_made: NotRequired[int]  # 已执行工具次数（上限 8）
    tool_call: NotRequired[PlannedToolCall | None]  # 最近一次工具调用
    tool_result: NotRequired[str | None]  # 最近一次工具结果文本（回喂 Architect）
    tool_log: NotRequired[list[ToolCallRecord]]  # 全部工具调用记录
    architect_action: NotRequired[ArchitectAction | None]  # 最近一轮 Architect 决策

    timeline: NotRequired[list[TimelineEntry]]

