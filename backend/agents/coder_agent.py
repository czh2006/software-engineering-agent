"""Coder Agent：生成代码实现的计划（PatchPlan）。

输入：
- task_plan：PM 任务计划（TaskPlan）。
- architecture_analysis：Architect 架构分析。
- retrieved_chunks：RAG 检索到的相关代码片段。

输出：PatchPlan（files_to_modify / implementation_steps / risk / reasoning）。

约束：
- 只做实现规划，禁止生成实际代码、禁止生成 Diff/Patch 内容。
- OpenAI 兼容 Chat Completions（DeepSeek）+ JSON 输出 + Pydantic 强校验。
"""

import json
import sys

from openai import OpenAI
from pydantic import BaseModel, Field

from agents.architect_agent import ArchitectureAnalysis
from agents.retriever_agent import RetrievedChunk
from app.core.config import get_settings
from app.schemas.workflow import TaskPlan


class PatchPlan(BaseModel):
    """Coder 产出的代码实现计划。"""

    files_to_modify: list[str] = Field(
        description="需要创建或修改的文件路径列表（仅路径，不含代码）"
    )
    implementation_steps: list[str] = Field(
        description="按顺序的实现步骤（文字描述，不包含代码）"
    )
    risk: list[str] = Field(description="实现风险点列表")
    reasoning: str = Field(description="实现方案推理摘要")


_SYSTEM_PROMPT: str = """你是软件工程团队的 Coder（实现工程师）。
你的职责：结合 PM 的任务计划、Architect 的架构分析和检索到的相关代码，
产出一份清晰、可执行的"代码实现计划"（PatchPlan），供后续真正写代码时遵循。

要求：
- 只做计划，禁止生成任何实际代码，禁止生成 Diff / Patch 内容；
- files_to_modify 只列文件路径，不写代码；
- implementation_steps 用文字描述先后步骤；
- 结合检索到的现有代码风格与结构，尽量贴合实际代码库。

输出约束（必须遵守）：
- 只输出一个 JSON 对象，不要 Markdown、不要 ```json 围栏、不要解释文字；
- JSON 结构必须为：
{
  "files_to_modify": ["文件路径1", "文件路径2"],
  "implementation_steps": ["步骤1", "步骤2"],
  "risk": ["风险1", "风险2"],
  "reasoning": "整体实现方案推理（字符串）"
}"""


def _build_user_prompt(
    task_plan: TaskPlan,
    architecture_analysis: ArchitectureAnalysis,
    retrieved_chunks: list[RetrievedChunk],
) -> str:
    """构造用户消息：任务计划 + 架构分析 + 检索片段。"""
    sections: list[str] = [
        f"【任务计划 TaskPlan】\n{task_plan.model_dump_json(indent=2)}",
        f"【架构分析 ArchitectureAnalysis】\n{architecture_analysis.model_dump_json(indent=2)}",
    ]

    if retrieved_chunks:
        chunk_lines = [
            f"- {c.file_path} [{c.symbol_name}] (score={c.score:.3f})\n  {c.code[:600]}"
            for c in retrieved_chunks[:8]
        ]
        sections.append("【检索到的相关代码】\n" + "\n".join(chunk_lines))
    else:
        sections.append("【检索到的相关代码】(无)")

    return "\n\n".join(sections)


def generate_patch_plan(
    task_plan: TaskPlan,
    architecture_analysis: ArchitectureAnalysis,
    retrieved_chunks: list[RetrievedChunk],
) -> PatchPlan:
    """调用 Coder Agent，产出代码实现计划（不生成代码/Diff）。

    Args:
        task_plan: PM 的任务计划。
        architecture_analysis: Architect 的架构分析。
        retrieved_chunks: RAG 检索到的代码片段（可为空列表）。

    Returns:
        符合 PatchPlan Schema 的 Pydantic 对象。

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

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _build_user_prompt(
                    task_plan, architecture_analysis, retrieved_chunks
                ),
            },
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
    return PatchPlan.model_validate(data)


if __name__ == "__main__":
    from agents.architect_agent import generate_architecture_analysis
    from agents.pm_agent import generate_task_plan
    from agents.retriever_agent import retrieve_for_task_plan

    request = sys.argv[1] if len(sys.argv) > 1 else "Add Google OAuth login."
    print(f"用户需求: {request}\n")

    plan = generate_task_plan(request)
    print("1. PM TaskPlan 已生成\n")

    chunks = retrieve_for_task_plan(plan)
    print(f"2. Retriever 检索到 {len(chunks)} 个片段\n")

    analysis = generate_architecture_analysis(plan, chunks)
    print("3. Architect 架构分析已生成\n")

    patch_plan = generate_patch_plan(plan, analysis, chunks)
    print(analysis.model_dump_json(indent=2))
    print(patch_plan.model_dump_json(indent=2))
