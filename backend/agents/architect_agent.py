"""Architect Agent：根据 TaskPlan + RetrievedChunks 分析代码架构。

输入：
- task_plan：PM 拆解的任务计划（TaskPlan）。
- retrieved_chunks：RAG 检索到的相关代码片段（list[SearchResult]）。

输出：
- ArchitectureAnalysis（modules / dependencies / risk / reasoning）。

约束：
- 只做架构分析，不生成代码、不生成 Patch。
- OpenAI 兼容 Chat Completions（DeepSeek）+ JSON 输出 + Pydantic 强校验。
"""

import json
import sys

from openai import OpenAI
from pydantic import BaseModel, Field

from app.core.config import get_settings
from rag.retriever import SearchResult
from agents.pm_agent import TaskPlan


class ArchitectureModule(BaseModel):
    """分析出的一个架构模块。"""

    name: str = Field(description="模块名")
    responsibility: str = Field(description="模块职责")
    files: list[str] = Field(description="涉及/建议涉及的文件路径")


class ArchitectureDependency(BaseModel):
    """模块之间的依赖关系。"""

    source: str = Field(description="依赖方模块名")
    target: str = Field(description="被依赖模块名")
    reason: str = Field(description="依赖原因")


class ArchitectureAnalysis(BaseModel):
    """架构分析产出。"""

    modules: list[ArchitectureModule] = Field(description="模块划分")
    dependencies: list[ArchitectureDependency] = Field(description="依赖关系")
    risk: list[str] = Field(description="风险点列表")
    reasoning: str = Field(description="分析推理过程摘要")


_SYSTEM_PROMPT: str = """你是软件工程团队的 Architect（架构师）。
你的职责：根据 PM 的任务计划和 RAG 检索到的相关代码，对现有代码库做架构分析，
判断新功能应如何融入/改造现有结构。

要求：
- 只做分析，绝对不要生成任何代码，也不要生成 Patch；
- 分析现有代码结构，给出合理的模块划分与模块间依赖；
- 指出主要风险（如耦合、兼容性、性能、安全问题）。

输出约束（必须遵守）：
- 只输出一个 JSON 对象，不要 Markdown、不要 ```json 围栏、不要解释文字；
- JSON 结构必须为：
{
  "modules": [
    { "name": "模块名", "responsibility": "职责", "files": ["文件路径"] }
  ],
  "dependencies": [
    { "source": "依赖方模块", "target": "被依赖模块", "reason": "原因" }
  ],
  "risk": ["风险点1", "风险点2"],
  "reasoning": "整体分析推理摘要（字符串）"
}"""


def _build_user_prompt(task_plan: TaskPlan, retrieved_chunks: list[SearchResult]) -> str:
    """构造用户消息：任务计划 + 检索到的代码片段。"""
    sections: list[str] = []

    plan_json = task_plan.model_dump_json(indent=2)
    sections.append(f"【任务计划 TaskPlan】\n{plan_json}")

    if retrieved_chunks:
        chunk_lines: list[str] = []
        for chunk in retrieved_chunks:
            chunk_lines.append(
                f"- {chunk.file_path}:{chunk.line_range} [{chunk.symbol_name}] "
                f"(score={chunk.score})\n  {chunk.code[:800]}"
            )
        sections.append("【检索到的相关代码】\n" + "\n".join(chunk_lines))
    else:
        sections.append("【检索到的相关代码】(无)")

    return "\n\n".join(sections)


def generate_architecture_analysis(
    task_plan: TaskPlan,
    retrieved_chunks: list[SearchResult],
) -> ArchitectureAnalysis:
    """调用 Architect Agent，产出架构分析。

    Args:
        task_plan: PM 的任务计划。
        retrieved_chunks: RAG 检索到的代码片段（可为空列表）。

    Returns:
        符合 ArchitectureAnalysis Schema 的 Pydantic 对象。

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
                "content": _build_user_prompt(task_plan, retrieved_chunks),
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
    return ArchitectureAnalysis.model_validate(data)


if __name__ == "__main__":
    from rag.retriever import search_code

    request = sys.argv[1] if len(sys.argv) > 1 else "Add Google OAuth login."
    print(f"用户需求: {request}\n")

    # 演示链路: PM → RAG 检索 → Architect
    plan = None
    if len(sys.argv) > 2:
        plan = TaskPlan.model_validate(json.loads(sys.argv[2]))
    else:
        from agents.pm_agent import generate_task_plan

        plan = generate_task_plan(request)
        print("PM TaskPlan 已生成\n")

    chunks = search_code(request, top_k=5)
    print(f"RAG 检索到 {len(chunks)} 个片段\n")

    analysis = generate_architecture_analysis(plan, chunks)
    print(analysis.model_dump_json(indent=2))
