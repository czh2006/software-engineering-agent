"""Architect Agent（可调用只读 MCP 工具）— 依据 TaskPlan + 检索片段 + 仓库实况做架构分析。

输入：
- task_plan：PM 拆解的任务计划（TaskPlan）。
- retrieved_chunks：RAG 检索到的相关代码片段（list[SearchResult]，可为空）。

输出：
- ArchitectureAnalysis（modules / dependencies / risk / reasoning）。

新增能力：Architect 可通过统一 MCP Client 调用只读 MCP 工具探查仓库。
- 允许：filesystem.list_files / filesystem.read_file / filesystem.search_files
        / git.git_status / git.git_log
- 禁止：terminal.run_command / python.run_python_file 及一切写操作（不在白名单即拒绝）。

架构约束：
1. 本模块不 import 任何具体 MCP Server 模块（mcp_servers.*）；工具对象经
   tools.registry 的 discovery 与 mcp_client.client.MCPClient 获取/调用。
2. Agent 只通过 MCP Client 调用工具；不直接触碰工具实现。
3. 先由"规划 LLM"判断是否需要工具（可返回 0 个调用）。
4. 工具返回的结构化结果（摘要）并入最终分析上下文。
5. 单次任务最多 MAX_TOOL_CALLS（8）次工具调用。
6. 每次工具调用记录 tool / arguments / duration / result summary。
7. 工具失败不中断：记录后继续；最终仍产出 ArchitectureAnalysis。
8. 不改动 LangGraph State（本文件不引入状态字段）。

实现：
- 规划：LLM 决定 tool_calls（JSON）。
- 执行：ArchitectTools（同步 facade，内部 asyncio.run 桥接 MCPClient）。
- 分析：LLM 依据 计划+检索片段+MCP 结果 输出 ArchitectureAnalysis（JSON+Pydantic）。
"""

import asyncio
import json
import logging
import sys
import time
from typing import Any, Callable, Iterable, Literal

from openai import OpenAI
from pydantic import BaseModel, Field

from app.core.config import get_settings
from rag.retriever import SearchResult
from agents.pm_agent import TaskPlan

logger = logging.getLogger("agents.architect")

# 允许 Architect 调用的只读 MCP 工具（server.tool 全名）
ALLOWED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "filesystem.list_files",
        "filesystem.read_file",
        "filesystem.search_files",
        "git.git_status",
        "git.git_log",
    }
)
MAX_TOOL_CALLS: int = 8  # 单次任务工具调用上限
TOOL_RESULT_MAX_CHARS: int = 1500  # 单条工具结果写入上下文的最大长度


# ---------- 架构分析 Schema（对外不变） ----------

class ArchitectureModule(BaseModel):
    """分析出的一个架构模块。"""

    name: str = Field(description="模块名")
    responsibility: str = Field(default="", description="模块职责")
    files: list[str] = Field(default_factory=list, description="涉及/建议涉及的文件路径")


class ArchitectureDependency(BaseModel):
    """模块之间的依赖关系。"""

    source: str = Field(description="依赖方模块名")
    target: str = Field(description="被依赖模块名")
    reason: str = Field(default="", description="依赖原因")


class ArchitectureAnalysis(BaseModel):
    """架构分析产出。"""

    modules: list[ArchitectureModule] = Field(description="模块划分")
    dependencies: list[ArchitectureDependency] = Field(default_factory=list, description="依赖关系")
    risk: list[str] = Field(default_factory=list, description="风险点列表")
    reasoning: str = Field(default="", description="分析推理过程摘要")


# ---------- 工具规划 / 调用日志 Schema ----------

class PlannedToolCall(BaseModel):
    """规划阶段决定的一次工具调用。"""

    tool: str = Field(description="完整工具名（server.tool），如 filesystem.search_files")
    arguments: dict[str, Any] = Field(default_factory=dict, description="工具参数")


class ToolPlan(BaseModel):
    """规划 LLM 的产出：是否/如何调用工具。"""

    reasoning: str = Field(default="", description="决策理由")
    tool_calls: list[PlannedToolCall] = Field(default_factory=list, description="要执行的工具调用（可为空）")


class ToolCallRecord(BaseModel):
    """一次工具调用的执行日志（tool / arguments / duration / result summary）。"""

    tool: str
    arguments: dict[str, Any]
    duration: int  # ms
    success: bool
    summary: str  # 结果摘要


class ArchitectAction(BaseModel):
    """Architect 单轮产出：要么调用一个工具，要么结束并给出最终架构分析。

    供 LangGraph 的 Architect(决策) 节点使用；action=finish 时 analysis 为最终产出。
    """

    action: Literal["finish", "call_tool"]
    reasoning: str = Field(default="", description="本轮推理/决策理由")
    tool: str = Field(default="", description="action=call_tool 时的完整工具名 server.tool")
    arguments: dict[str, Any] = Field(default_factory=dict, description="action=call_tool 时的参数")
    analysis: ArchitectureAnalysis | None = Field(default=None, description="action=finish 时的最终架构分析")


# ---------- Prompts ----------

_SYSTEM_PROMPT: str = """你是软件工程团队的 Architect（架构师）。
你的职责：根据 PM 的任务计划和相关资料（RAG 检索片段 + MCP 工具探查到的仓库实况），
对现有代码库做架构分析，判断新功能应如何融入/改造现有结构。

要求：
- 只做分析，绝对不要生成任何代码，也不要生成 Patch；
- 分析现有代码结构，给出合理的模块划分与模块间依赖；
- 指出主要风险（如耦合、兼容性、性能、安全问题）；
- 若提供了【MCP 工具执行结果】，请以其为准并结合它们给出有依据的结论。

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

_PLANNER_PROMPT: str = """你是软件工程团队 Architect 的"探索决策器"。
在开始最终架构分析之前，判断是否需要调用只读 MCP 工具探查代码库以获得更准确的依据。

可用工具（只读，只能从中选择，禁止其它任何工具）：
- filesystem.list_files    参数 {"path": "目录，默认 ."}
- filesystem.read_file     参数 {"path": "文件路径"}
- filesystem.search_files  参数 {"query": "关键词", "path": "目录，默认 ."}
- git.git_status           无参数
- git.git_log              参数 {"limit": 10}

约束：
- 只调用真正有帮助的工具；若现有信息已足够可直接返回空 tool_calls。
- 单次最多 {max_calls} 次工具调用；不要重复同样的调用。
- 这些工具全部只读，绝不涉及写操作。

输出约束（必须遵守）：
- 只输出一个 JSON 对象，不要 Markdown、不要 ```json 围栏、不要解释文字；
- JSON 结构必须为：
{{
  "reasoning": "简要说明是否需要工具以及理由",
  "tool_calls": [
    {{ "tool": "filesystem.search_files", "arguments": {{ "query": "关键词" }} }}
  ]
}}"""

_TURN_PROMPT: str = """你是软件工程团队的 Architect（架构师）。
你在 LangGraph 的迭代循环中工作：每轮可以决定再调用一个只读工具探查仓库，或认为信息已足够并直接输出最终架构分析。

可用工具（只读，只能从中选择，禁止其它任何工具；每轮最多调用 1 个）：
- filesystem.list_files    参数 {{"path": "目录，默认 ."}}
- filesystem.read_file     参数 {{"path": "文件路径"}}
- filesystem.search_files  参数 {{"query": "关键词", "path": "目录，默认 ."}}
- git.git_status           无参数
- git.git_log              参数 {{"limit": 10}}

约束：
- 只调用真正有帮助的工具；避免重复已经调用过且已拿到结果的问题。
- 若现有上下文（任务计划 + 检索片段 + 历史工具结果）足以给出有依据的架构分析，就直接 finish。
- 分析只读，绝不涉及写操作；绝不输出代码/Patch。

输出约束（必须遵守）：
- 只输出一个 JSON 对象，不要 Markdown、不要 ```json 围栏、不要解释文字。
- 若要再调用工具，输出：
{{"action": "call_tool", "reasoning": "为何调用", "tool": "filesystem.search_files", "arguments": {{"query": "关键词"}}}}
- 若要结束，输出完整分析：
{{
  "action": "finish",
  "reasoning": "为何认为信息已足够",
  "analysis": {{
    "modules": [{{"name": "模块名", "responsibility": "职责", "files": ["文件路径"]}}],
    "dependencies": [{{"source": "依赖方", "target": "被依赖方", "reason": "原因"}}],
    "risk": ["风险点1"],
    "reasoning": "整体分析推理摘要"
  }}
}}"""


# ---------- OpenAI 工具函数 ----------

def _make_client(settings: Any) -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)


def _chat_json(client: OpenAI, model: str, messages: list[dict]) -> dict:
    """调用 Chat Completions 并返回解析后的 JSON dict。"""
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    content: str = (response.choices[0].message.content or "").strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()
    data = json.loads(content)  # 非 JSON 时抛错
    if not isinstance(data, dict):
        raise ValueError("模型未返回 JSON 对象")
    return data


def _build_user_prompt(task_plan: TaskPlan, retrieved_chunks: list[SearchResult]) -> str:
    """构造基础用户消息：任务计划 + 检索到的代码片段。"""
    sections: list[str] = []
    sections.append(f"【任务计划 TaskPlan】\n{task_plan.model_dump_json(indent=2)}")

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


def _clip(text: str, limit: int = TOOL_RESULT_MAX_CHARS) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "\n…(截断)"


# ---------- 默认 LLM：规划工具调用 ----------

def _plan_tool_calls(task_plan: TaskPlan, retrieved_chunks: list[SearchResult]) -> ToolPlan:
    """默认规划实现：让 LLM 判断是否需要工具并列出工具调用。"""
    settings = get_settings()
    if not settings.openai_api_key:
        raise ValueError("未配置 OPENAI_API_KEY。请在 backend/.env 或环境变量中设置后重试。")

    client = _make_client(settings)
    allowed_desc = "\n".join(f"- {t}" for t in sorted(ALLOWED_TOOL_NAMES))
    user = _build_user_prompt(task_plan, retrieved_chunks)
    data = _chat_json(
        client,
        settings.openai_model,
        [
            {"role": "system", "content": _PLANNER_PROMPT.format(max_calls=MAX_TOOL_CALLS)},
            {
                "role": "user",
                "content": f"{user}\n\n【可调用工具列表】\n{allowed_desc}\n\n请输出你的探索决策 JSON。",
            },
        ],
    )
    return ToolPlan.model_validate(data)

def summarize_records(records: list[ToolCallRecord]) -> list[str]:
    """把工具调用记录列表格式化为供 LLM 上下文使用的文本列表。"""
    return [_fmt_record(i, rec) for i, rec in enumerate(records, start=1)]


# ---------- 默认 LLM：单轮 决策/分析（供 LangGraph Tool Loop 节点使用） ----------

def architect_turn(
    task_plan: TaskPlan,
    retrieved_chunks: list[SearchResult],
    tool_results: list[str],
    *,
    available: Iterable[str] | None = None,
) -> ArchitectAction:
    """让 Architect 做一轮决策：再调用一个工具，或结束并给出最终架构分析。

    Args:
        task_plan: PM 的任务计划。
        retrieved_chunks: RAG 检索片段。
        tool_results: 历史工具执行结果的格式化文本列表。
        available: 当前可调用的工具全名（默认全部 ALLOWED_TOOL_NAMES）。

    Returns:
        ArchitectAction（finish 时携带完整 analysis）。

    Raises:
        ValueError: 未配置 OPENAI_API_KEY 或模型输出无法解析。
    """
    settings = get_settings()
    if not settings.openai_api_key:
        raise ValueError("未配置 OPENAI_API_KEY。请在 backend/.env 或环境变量中设置后重试。")

    client = _make_client(settings)
    allowed = sorted(available) if available is not None else sorted(ALLOWED_TOOL_NAMES)
    allowed_desc = "\n".join(f"- {t}" for t in allowed)

    sections: list[str] = [_build_user_prompt(task_plan, retrieved_chunks)]
    if tool_results:
        sections.append("【历史 MCP 工具执行结果】\n" + "\n\n".join(tool_results))
    else:
        sections.append("【历史 MCP 工具执行结果】(尚无)")

    data = _chat_json(
        client,
        settings.openai_model,
        [
            {"role": "system", "content": _TURN_PROMPT},
            {
                "role": "user",
                "content": "\n\n".join(sections) + f"\n\n【当前可用工具】\n{allowed_desc}\n\n请输出本轮决策 JSON。",
            },
        ],
    )
    action = ArchitectAction.model_validate(data)
    # 防御：finish 必须带 analysis，否则按 call_tool 缺省兜底
    if action.action == "finish" and action.analysis is None:
        raise ValueError("模型 finish 时未提供 analysis")
    return action

# ---------- 默认 LLM：最终分析（供 LangGraph Finalize / 单次入口复用） ----------

def analyze_architecture(
    task_plan: TaskPlan,
    retrieved_chunks: list[SearchResult],
    tool_results: list[str],
) -> ArchitectureAnalysis:
    """默认分析实现：依据 计划+片段+MCP 结果 输出 ArchitectureAnalysis（公开供图节点/测试调用）。"""
    settings = get_settings()
    if not settings.openai_api_key:
        raise ValueError("未配置 OPENAI_API_KEY。请在 backend/.env 或环境变量中设置后重试。")

    client = _make_client(settings)
    sections: list[str] = [_build_user_prompt(task_plan, retrieved_chunks)]
    if tool_results:
        sections.append("【MCP 工具执行结果】\n" + "\n\n".join(tool_results))
    else:
        sections.append("【MCP 工具执行结果】(未调用任何工具)")

    data = _chat_json(
        client,
        settings.openai_model,
        [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": "\n\n".join(sections)}],
    )
    return ArchitectureAnalysis.model_validate(data)


# ---------- 同步 MCP 工具 facade（Agent 只经此调用工具） ----------

class ArchitectTools:
    """Architect 可用的只读 MCP 工具（同步 facade，内部用 asyncio.run 桥接 MCPClient）。

    只暴露 ALLOWED_TOOL_NAMES 内的工具；每次执行记录 ToolCallRecord。
    本类不导入具体 MCP Server 模块（由构建方经 registry 注入 MCPServer 对象）。
    """

    def __init__(self, client: Any, server_names: list[str]) -> None:
        self._client = client
        self._servers = set(server_names)
        self.records: list[ToolCallRecord] = []

    def connected_servers(self) -> list[str]:
        return sorted(self._servers)

    def available_tools(self) -> list[str]:
        return sorted(
            t for t in ALLOWED_TOOL_NAMES if t.split(".", 1)[0] in self._servers
        )

    def execute(self, tool_fq: str, arguments: dict[str, Any] | None = None) -> ToolCallRecord:
        """执行一次工具调用并记录（禁止的工具不执行，直接记为失败）。"""
        args = dict(arguments or {})
        start = time.monotonic()

        if tool_fq not in ALLOWED_TOOL_NAMES:
            record = ToolCallRecord(
                tool=tool_fq,
                arguments=args,
                duration=_ms(start),
                success=False,
                summary=f"[blocked] 不允许的工具：{tool_fq}（只允许 {', '.join(sorted(ALLOWED_TOOL_NAMES))}）",
            )
        else:
            server, tool = tool_fq.split(".", 1)
            if server not in self._servers:
                record = ToolCallRecord(
                    tool=tool_fq,
                    arguments=args,
                    duration=_ms(start),
                    success=False,
                    summary=f"[error] Server 未连接：{server}",
                )
            else:
                try:
                    result = asyncio.run(self._client.call_tool(server, tool, args))
                    detail = (result.content or "").strip()
                    if not detail and not result.ok:
                        detail = "[error] 工具返回空结果"
                    record = ToolCallRecord(
                        tool=tool_fq,
                        arguments=args,
                        duration=_ms(start),
                        success=bool(result.ok),
                        summary=f"[{'ok' if result.ok else 'error'}] {_clip(detail)}",
                    )
                except Exception as exc:  # 工具/连接异常也收敛为记录，不中断
                    logger.exception("工具调用异常：%s.%s", server, tool)
                    record = ToolCallRecord(
                        tool=tool_fq,
                        arguments=args,
                        duration=_ms(start),
                        success=False,
                        summary=f"[mcp_error] {type(exc).__name__}: {exc}",
                    )
        self.records.append(record)
        logger.info(
            "tool_call tool=%s args=%s duration_ms=%d success=%s",
            record.tool, record.arguments, record.duration, record.success,
        )
        return record


def build_mcp_tools(timeout_seconds: float = 30.0) -> "ArchitectTools | None":
    """构建 Architect 的同步工具 facade（best-effort）。

    经 tools.registry（discovery 层）加载全部内置 Server 再交给 MCPClient；
    本函数不 import mcp_servers.* 具体实现。加载失败返回 None（Agent 无工具继续）。
    """
    try:
        from tools.registry import MCPRegistry, load_builtin_servers
        from mcp_client.client import MCPClient

        reg = MCPRegistry()
        load_builtin_servers(reg)
        client = MCPClient(timeout_seconds=timeout_seconds)

        async def _connect() -> list[str]:
            for name in reg.server_names():
                await client.connect(reg.get_server(name))
            return client.connected_servers()

        servers = asyncio.run(_connect())
        return ArchitectTools(client, servers)
    except Exception:
        logger.exception("构建 MCP 工具失败，Architect 将以无工具模式继续")
        return None


def _fmt_record(index: int, rec: ToolCallRecord) -> str:
    args = json.dumps(rec.arguments, ensure_ascii=False)[:300]
    return (
        f"{index}. tool={rec.tool}\n"
        f"   arguments={args}\n"
        f"   duration={rec.duration}ms  success={rec.success}\n"
        f"   result: {rec.summary}"
    )


# ---------- 编排入口 ----------

def generate_architecture_analysis(
    task_plan: TaskPlan,
    retrieved_chunks: list[SearchResult],
    *,
    tools: ArchitectTools | None = None,
    planner: Callable[[TaskPlan, list[SearchResult]], ToolPlan] | None = None,
    analyzer: Callable[[TaskPlan, list[SearchResult], list[str]], ArchitectureAnalysis] | None = None,
) -> ArchitectureAnalysis:
    """调用 Architect Agent，产出架构分析。

    流程：规划(判断是否需要工具并列出调用) → 经 MCPClient 执行(≤8 次，失败继续)
        → 结果并入上下文 → 最终架构分析。

    默认 planner/analyzer 走真实 LLM；测试可注入桩函数。
    """
    settings = get_settings()
    if (planner is None or analyzer is None) and not settings.openai_api_key:
        raise ValueError("未配置 OPENAI_API_KEY。请在 backend/.env 或环境变量中设置后重试。")

    retrieved = list(retrieved_chunks or [])

    if tools is None:
        tools = build_mcp_tools()

    records: list[ToolCallRecord] = []
    tool_results: list[str] = []

    if tools is not None and tools.available_tools():
        plan_fn: Callable[[TaskPlan, list[SearchResult]], ToolPlan] = planner or _plan_tool_calls
        try:
            plan = plan_fn(task_plan, retrieved)
        except Exception:
            # 规划失败不中断：降级为不调用工具并继续分析
            logger.exception("Architect 工具规划失败，降级为无工具分析")
            plan = ToolPlan(reasoning="工具规划失败", tool_calls=[])

        calls = plan.tool_calls[:MAX_TOOL_CALLS]
        for i, call in enumerate(calls, start=1):
            rec = tools.execute(call.tool, call.arguments)
            records.append(rec)
            tool_results.append(_fmt_record(i, rec))
        if len(plan.tool_calls) > MAX_TOOL_CALLS:
            tool_results.append(
                f"(注：规划了 {len(plan.tool_calls)} 次调用，超过上限 {MAX_TOOL_CALLS}，仅执行前 {MAX_TOOL_CALLS} 次)"
            )

    analyze_fn: Callable[[TaskPlan, list[SearchResult], list[str]], ArchitectureAnalysis] = (
        analyzer or analyze_architecture
    )
    return analyze_fn(task_plan, retrieved, tool_results)


def generate_architecture_analysis_with_records(
    task_plan: TaskPlan,
    retrieved_chunks: list[SearchResult],
    **kwargs: Any,
) -> tuple[ArchitectureAnalysis, list[ToolCallRecord]]:
    """同 generate_architecture_analysis，但额外返回本次工具调用记录。

    用于需要观察工具日志的调用方/测试；不改变 LangGraph State。
    """
    injected_tools = kwargs.get("tools")
    if injected_tools is None:
        injected_tools = build_mcp_tools()
        kwargs["tools"] = injected_tools
    analysis = generate_architecture_analysis(task_plan, retrieved_chunks, **kwargs)
    records = injected_tools.records if injected_tools is not None else []
    return analysis, list(records)


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


if __name__ == "__main__":
    from rag.retriever import search_code

    request = sys.argv[1] if len(sys.argv) > 1 else "Analyze the authentication architecture of this repository."
    print(f"用户需求: {request}\n")

    if len(sys.argv) > 2:
        plan = TaskPlan.model_validate(json.loads(sys.argv[2]))
    else:
        from agents.pm_agent import generate_task_plan

        plan = generate_task_plan(request)
        print("PM TaskPlan 已生成\n")

    chunks = search_code(request, top_k=5)
    print(f"RAG 检索到 {len(chunks)} 个片段\n")

    analysis, records = generate_architecture_analysis_with_records(plan, chunks)
    print(f"MCP 工具调用 {len(records)} 次\n")
    for r in records:
        print(f"- {r.tool} args={r.arguments} {r.duration}ms success={r.success}")
    print()
    print(analysis.model_dump_json(indent=2))
