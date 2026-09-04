"""Workflow 相关的 Pydantic Schema（Pydantic v2）。

TaskItem / TaskPlan 在此统一收敛定义，供 PM Agent 及各下游 Agent 复用，
避免每个 Agent 各自重复声明。
"""

from pydantic import BaseModel, Field


class TaskItem(BaseModel):
    """任务拆解清单中的单个任务项。"""

    title: str = Field(description="任务标题")
    description: str = Field(description="任务描述，说明要做什么与验收要点")
    owner: str = Field(
        description="负责角色：architect / coder / qa / reviewer 之一"
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="依赖的其他任务标题列表；无依赖时为空列表",
    )


class TaskPlan(BaseModel):
    """PM Agent 产出的需求拆解计划。"""

    goal: str = Field(description="总体目标，一句话概括要解决的问题")
    priority: str = Field(description="优先级：high / medium / low")
    tasks: list[TaskItem] = Field(description="任务清单，按依赖拓扑排序")
    expected_files: list[str] = Field(
        description="预期会创建或修改的文件路径列表"
    )
