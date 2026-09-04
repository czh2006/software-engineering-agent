"""Reviewer Agent：审查 Coder 的实现计划（PatchPlan）。

输入：PatchPlan（Coder Agent 产出的代码实现计划）。
输出：ReviewResult（approved / comments / missing_modules /
      test_suggestions / risk_score）。

职责：从完整性、风险、可测试性、缺失模块等角度审查实现计划，
并给出是否批准通过的结论。
"""

import json
import sys

from openai import OpenAI
from pydantic import BaseModel, Field

from agents.coder_agent import PatchPlan
from app.core.config import get_settings


class ReviewResult(BaseModel):
    """Reviewer 产出的审查结果。"""

    approved: bool = Field(description="是否批准通过该实现计划")
    comments: list[str] = Field(description="审查意见列表")
    missing_modules: list[str] = Field(
        description="计划中缺失/遗漏的模块或能力"
    )
    test_suggestions: list[str] = Field(
        description="建议补充的测试用例或测试场景"
    )
    risk_score: int = Field(
        description="综合风险评分（0~100，越大风险越高）",
        ge=0,
        le=100,
    )


_SYSTEM_PROMPT: str = """你是软件工程团队的 Reviewer（代码审查员）。
你的职责：审查 Coder 提交的实现计划（PatchPlan），从完整性、风险、
可测试性、缺失模块等角度给出结论与建议。

要求：
- 不修改计划，只做审查；
- approved 为布尔值：通过为 true，不通过为 false；
- comments 给出具体的审查意见；
- missing_modules 指出实现计划里可能遗漏的模块、功能点或边界场景；
- test_suggestions 给出应补充的测试建议；
- risk_score 为 0~100 的整数，越高代表实现风险越大。

输出约束（必须遵守）：
- 只输出一个 JSON 对象，不要 Markdown、不要 ```json 围栏、不要解释文字；
- JSON 结构必须为：
{
  "approved": true 或 false,
  "comments": ["意见1", "意见2"],
  "missing_modules": ["缺失项1", "缺失项2"],
  "test_suggestions": ["测试建议1", "测试建议2"],
  "risk_score": 0 到 100 的整数
}"""


def generate_review(patch_plan: PatchPlan) -> ReviewResult:
    """调用 Reviewer Agent，审查实现计划。

    Args:
        patch_plan: Coder 产出的实现计划。

    Returns:
        符合 ReviewResult Schema 的 Pydantic 对象。

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

    user_prompt = (
        "请审查以下代码实现计划：\n\n"
        + patch_plan.model_dump_json(indent=2)
    )

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
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
    return ReviewResult.model_validate(data)


if __name__ == "__main__":
    from agents.coder_agent import PatchPlan

    # 允许通过 argv 传入 PatchPlan JSON，或使用内置示例
    if len(sys.argv) > 1:
        patch = PatchPlan.model_validate(json.loads(sys.argv[1]))
    else:
        patch = PatchPlan(
            files_to_modify=["backend/app/api/routes/auth.py", "backend/app/main.py"],
            implementation_steps=[
                "新增 auth.py 路由，仿照现有 chat 路由声明 router",
                "实现 /auth/login 生成 state 并跳转 Google",
                "实现 /auth/callback 校验并建立会话",
            ],
            risk=["state 需持久化防 CSRF", "redirect_uri 需精确匹配"],
            reasoning="新增独立 auth 模块，注册到 main.py",
        )

    result = generate_review(patch)
    print(result.model_dump_json(indent=2))
