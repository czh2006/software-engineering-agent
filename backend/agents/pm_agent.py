"""PM Agent：把用户需求拆解为可执行的任务计划（TaskPlan）。

输入：user_request（用户需求文本）。
输出：TaskPlan（goal / priority / tasks[] / expected_files）。

实现：
- OpenAI 兼容 Chat Completions API（默认 DeepSeek 端点）
- 强制 JSON 输出（response_format=json_object）+ Pydantic 强校验
- 不使用 Markdown（模型按 System 约束只输出 JSON）
"""

import json
import sys

from openai import OpenAI
from pydantic import BaseModel, Field

from app.core.config import get_settings


class TaskItem(BaseModel):
    """拆解出的单个任务。"""

    title: str = Field(description="任务标题")
    description: str = Field(description="任务描述")
    owner: str = Field(
        description="负责角色：architect / coder / qa / reviewer 之一"
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="依赖的其他任务标题",
    )


class TaskPlan(BaseModel):
    """PM 产出：需求拆解计划。"""

    goal: str = Field(description="总体目标")
    priority: str = Field(description="优先级：high / medium / low")
    tasks: list[TaskItem] = Field(description="任务清单")
    expected_files: list[str] = Field(description="预期会创建/修改的文件路径")


_SYSTEM_PROMPT: str = """你是软件工程团队的 PM（项目经理）。
你的职责：把用户需求拆解为清晰、可执行、可测试的任务计划。

要求：
- 按依赖关系拆分任务，明确每个任务的负责角色（architect/coder/qa/reviewer）；
- 任务粒度适中（每个任务可独立完成与验证）。

输出约束（必须遵守）：
- 只输出一个 JSON 对象，不要输出 Markdown、不要 ```json 围栏、不要任何解释文字；
- JSON 结构必须为：
{
  "goal": "总体目标（字符串）",
  "priority": "high 或 medium 或 low",
  "tasks": [
    {
      "title": "任务标题",
      "description": "任务描述",
      "owner": "architect 或 coder 或 qa 或 reviewer",
      "depends_on": ["依赖任务标题列表，可空"]
    }
  ],
  "expected_files": ["预期创建/修改的文件路径列表"]
}"""


def _build_user_prompt(user_request: str) -> str:
    """构造用户消息。"""
    return f"用户需求：\n{user_request}"


def generate_task_plan(user_request: str) -> TaskPlan:
    """调用 PM Agent，把用户需求拆解为 TaskPlan。

    Args:
        user_request: 用户原始需求。

    Returns:
        符合 TaskPlan Schema 的 Pydantic 对象。

    Raises:
        ValueError: 未配置 OPENAI_API_KEY 或模型返回无法解析时。
    """
    settings = get_settings()
    if not settings.openai_api_key:
        raise ValueError(
            "未配置 OPENAI_API_KEY。请在 backend/.env 或环境变量中设置后重试。"
        )

    client = OpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )

    # Chat Completions + 强制 JSON 输出（DeepSeek / OpenAI 兼容端点）
    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(user_request)},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )

    content: str = (response.choices[0].message.content or "").strip()

    # 防御性清理：若偶发包含 Markdown 围栏则剥离
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    data = json.loads(content)  # 非 JSON 时抛错
    return TaskPlan.model_validate(data)


if __name__ == "__main__":
    request = sys.argv[1] if len(sys.argv) > 1 else "为项目添加用户登录与 JWT 鉴权功能"
    plan = generate_task_plan(request)
    print(plan.model_dump_json(indent=2))

