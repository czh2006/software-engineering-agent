"""Workflow State 类型设计。

为 AI Software Engineering Team 的未来 Workflow（LangGraph 编排
PM → Architect → Coder → QA → Reviewer）定义**共享状态 State**。

本模块只做类型设计（TypedDict），不实现任何 Workflow / Agent 逻辑。
"""

from typing import Literal, NotRequired, TypedDict

# ---------- 通用类型 ----------

# 团队成员角色（对应 PROJECT_SPEC 中的 Agent 角色）
AgentRole = Literal["pm", "architect", "coder", "qa", "reviewer"]

# 任务/阶段状态
TaskStatus = Literal["pending", "running", "done", "failed"]


class Message(TypedDict):
    """聊天消息（messages 列表的元素）。"""

    role: Literal["user", "assistant", "agent"]
    content: str
    agent: NotRequired[AgentRole]  # 当消息来自某个 Agent 时记录角色


# ---------- 各阶段产出结构 ----------

class Task(TypedDict):
    """任务拆解项（task_plan 的元素）。"""

    id: str
    title: str
    description: str
    owner: AgentRole  # 负责该任务的 Agent
    status: TaskStatus
    dependencies: NotRequired[list[str]]  # 依赖的其他任务 id


class RetrievedChunk(TypedDict):
    """RAG 检索到的代码片段（retrieved_chunks 的元素）。"""

    file_path: str
    symbol_name: str
    score: float
    code: str
    line_range: str


class ArchitectureAnalysis(TypedDict):
    """架构分析产出（architecture_analysis 的内容）。"""

    summary: str
    components: list[str]
    risks: NotRequired[list[str]]


class PatchPlan(TypedDict):
    """代码修改计划（patch_plan 的内容）。"""

    summary: str
    files: list[str]
    changes: list[str]


class ReviewResult(TypedDict):
    """审查结果（review_result 的内容）。"""

    approved: bool
    comments: list[str]
    score: NotRequired[int]


class TimelineEvent(TypedDict):
    """时间线事件（timeline 的元素）。"""

    step: str
    agent: AgentRole
    status: TaskStatus
    message: NotRequired[str]


# ---------- 主 State ----------

class State(TypedDict):
    """整个 Software Engineering Workflow 的共享状态。

    字段随工作流推进逐步填充：
    - user_request：初始注入的用户需求；
    - 后续由各阶段节点写入 task_plan / architecture_analysis / …
    """

    # 用户原始需求
    user_request: str
    # PM 产出的任务拆解清单
    task_plan: list[Task]
    # Architect 产出的架构分析
    architecture_analysis: ArchitectureAnalysis
    # RAG 检索到的相关代码片段（供 Coder 参考）
    retrieved_chunks: list[RetrievedChunk]
    # Coder 产出的代码修改计划（Git Patch 前置）
    patch_plan: PatchPlan
    # Reviewer 产出的审查结论
    review_result: ReviewResult
    # 各阶段执行时间线
    timeline: list[TimelineEvent]
    # 会话消息流（用户 ↔ Agent）
    messages: list[Message]
