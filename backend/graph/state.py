"""Workflow State 定义（供 LangGraph Workflow 使用）。

早期为纯 TypedDict 占位设计；现 WorkflowState 字段类型直接使用
各 Agent 的真实 Pydantic 模型，保证节点间产出数据可实际流转。

本模块只定义类型，Workflow 编排见 graph/workflow.py。
"""

from typing import NotRequired, TypedDict

from agents.architect_agent import ArchitectureAnalysis
from agents.coder_agent import PatchPlan
from agents.retriever_agent import RetrievedChunk
from agents.reviewer_agent import ReviewResult
from app.schemas.workflow import TaskPlan


class WorkflowState(TypedDict):
    """跨 Agent 的共享工作流状态。

    除 user_request 外均由对应节点逐步写入：
    - PM 写入 task_plan
    - Architect 写入 architecture_analysis
    - Retriever 写入 retrieved_chunks
    - Coder 写入 patch_plan
    - Reviewer 写入 review_result
    - 各节点追加 timeline
    """

    user_request: str
    task_plan: NotRequired[TaskPlan | None]
    architecture_analysis: NotRequired[ArchitectureAnalysis | None]
    retrieved_chunks: NotRequired[list[RetrievedChunk]]
    patch_plan: NotRequired[PatchPlan | None]
    review_result: NotRequired[ReviewResult | None]
    timeline: NotRequired[list[str]]

