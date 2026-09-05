"""Architect Tool Loop（LangGraph 节点）。

把 Architect 的"工具调用循环"下沉到 LangGraph 图里：
    Architect(决策)
        ↓ call_tool
    ArchTool（经 MCP Client 执行 1 个工具，失败自动重试 1 次）
        ↓
    Architect(决策)  ← 携带 ToolResult 再来一轮
        ↓ finish / 达到上限
    ArchFinalize → 产出 ArchitectureAnalysis → 继续后续节点(Retriever)

状态（graph.state.WorkflowState 新增字段）：
- tool_calls_made: int           已执行工具次数（上限 MAX_TOOL_CALLS=8）
- tool_call: PlannedToolCall     当前计划/已执行的那次工具调用
- tool_result: str               最近一次工具结果文本（喂回 Architect 上下文）
- tool_log: list[ToolCallRecord] 全部工具调用记录（tool/arguments/duration/success/summary）
- architect_action: ArchitectAction  最近一轮 Architect 决策（call_tool | finish[+analysis]）

约束：
- 本模块不写入任何具体 MCP Tool；工具经 ArchitectTools（内部只用 MCP Client）调用，
  具体 Server/工具由 tools.registry + mcp_client 提供。
- 每次实际工具执行都会追加 timeline 条目。
- 达到上限立即停止；工具失败自动重试一次；无工具可用时直接降级分析，防止死循环。
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from agents import architect_agent as aa
from graph.state import TimelineEntry, WorkflowState

logger = logging.getLogger("graph.architect_loop")

MAX_TOOL_CALLS: int = aa.MAX_TOOL_CALLS  # = 8

# 模块级工具运行器缓存（best-effort）；测试可 monkeypatch get_tool_runner
_UNSET = object()
_runner: Any = _UNSET


def get_tool_runner() -> aa.ArchitectTools | None:
    """返回 Architect 可用的同步 MCP 工具运行器（懒加载、可空）。"""
    global _runner
    if _runner is _UNSET:
        _runner = aa.build_mcp_tools()
    return _runner


def _entry(agent_name: str, status: str, duration: float) -> TimelineEntry:
    return {
        "agent_name": agent_name,
        "status": status,  # type: ignore[typeddict-item]
        "duration": round(duration, 3),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


# ---------- Architect（决策）节点 ----------

def architect_node(state: WorkflowState) -> dict:
    """让 Architect 基于 计划+检索片段+历史工具结果 做一轮决策。"""
    plan = state.get("task_plan")
    if plan is None:
        raise RuntimeError("Architect 节点需要 task_plan（PM 未执行）")

    chunks = list(state.get("retrieved_chunks") or [])
    summaries = aa.summarize_records(state.get("tool_log") or [])
    runner = get_tool_runner()
    available = runner.available_tools() if runner is not None else []
    start = time.monotonic()
    try:
        action = aa.architect_turn(plan, chunks, summaries, available=available)
    except Exception:
        # 决策失败不中断：降级为结束，走最终分析（含全部工具结果）兜底
        logger.exception("Architect 决策失败，降级为直接结束")
        action = aa.ArchitectAction(action="finish", reasoning="Architect 决策失败（降级结束）")
    timeline = [*state.get("timeline", []), _entry("Architect", "done", time.monotonic() - start)]
    return {"architect_action": action, "timeline": timeline}


# ---------- 工具执行节点（只经 MCP Client） ----------

def tool_call_node(state: WorkflowState) -> dict:
    """执行 Architect 决定的那个工具（失败自动重试一次；受上限约束）。"""
    action = state.get("architect_action")
    if action is None or action.action != "call_tool":
        raise RuntimeError("ArchTool 节点需要 call_tool 决策")

    fq = action.tool
    args = dict(action.arguments or {})
    calls = int(state.get("tool_calls_made", 0) or 0)
    log = list(state.get("tool_log") or [])
    timeline = list(state.get("timeline") or [])
    runner = get_tool_runner()

    # 允许执行次数：1 次 + 失败时重试 1 次；且不超剩余额度
    budget = MAX_TOOL_CALLS - calls
    max_attempts = min(2, budget)
    attempts = 0
    last: aa.ToolCallRecord | None = None

    for _ in range(max_attempts):
        if calls >= MAX_TOOL_CALLS:
            break
        start = time.monotonic()
        if runner is None:
            rec = aa.ToolCallRecord(
                tool=fq,
                arguments=args,
                duration=_ms(start),
                success=False,
                summary="[mcp_error] 工具运行器不可用",
            )
        else:
            rec = runner.execute(fq, args)  # 内部只用 MCP Client
        calls += 1
        attempts += 1
        log.append(rec)
        timeline.append(
            _entry(
                f"ArchTool:{fq}#{calls}",
                "done" if rec.success else "failed",
                time.monotonic() - start,
            )
        )
        last = rec
        if rec.success:
            break
        # 失败：若还有一次重试额度则继续尝试
        if attempts < max_attempts:
            continue
        break

    tool_result = (
        f"{fq} args={json.dumps(args, ensure_ascii=False)[:200]}\n"
        + (last.summary if last is not None else "[no result]")
    )
    return {
        "tool_calls_made": calls,
        "tool_log": log,
        "tool_call": aa.PlannedToolCall(tool=fq, arguments=args),
        "tool_result": tool_result,
        "timeline": timeline,
    }


# ---------- 结束节点：产出 ArchitectureAnalysis ----------

def _final_analyze(
    plan: Any,
    chunks: list[Any],
    summaries: list[str],
) -> aa.ArchitectureAnalysis:
    """兜底最终分析（达到上限仍无 analysis 时用全部上下文生成）。"""
    return aa.analyze_architecture(plan, chunks, summaries)


def architect_finalize_node(state: WorkflowState) -> dict:
    """产出最终 ArchitectureAnalysis（供后续 Retriever/Coder 使用）。"""
    plan = state.get("task_plan")
    if plan is None:
        raise RuntimeError("Architect 结束节点需要 task_plan")

    chunks = list(state.get("retrieved_chunks") or [])
    summaries = aa.summarize_records(state.get("tool_log") or [])
    action = state.get("architect_action")

    analysis = None
    if action is not None and action.action == "finish" and action.analysis is not None:
        analysis = action.analysis
    else:
        # 达到上限或降级结束：用最终分析 LLM 从 计划+片段+全部工具结果 生成
        analysis = _final_analyze(plan, chunks, summaries)

    return {"architecture_analysis": analysis}


# ---------- 条件路由 ----------

def decide_from_architect(state: WorkflowState) -> str:
    """Decision：读取 Architect 决策，决定 调用工具 / 结束。"""
    action = state.get("architect_action")
    if action is None or action.action == "finish":
        return "ArchFinalize"
    if int(state.get("tool_calls_made", 0) or 0) >= MAX_TOOL_CALLS:
        return "ArchFinalize"  # 达到上限必须停止
    if get_tool_runner() is None:
        return "ArchFinalize"  # 无工具可用：直接结束，防死循环
    return "ArchTool"


def route_after_tool(state: WorkflowState) -> str:
    """工具执行后：未达上限回 Architect，达上限结束。"""
    if int(state.get("tool_calls_made", 0) or 0) >= MAX_TOOL_CALLS:
        return "ArchFinalize"
    return "Architect"


# ---------- 把 Tool Loop 挂到 Workflow ----------

def add_architect_tool_loop(builder: Any, *, entry: str = "PM", exit_node: str = "Retriever") -> None:
    """向 StateGraph builder 注册 Architect Tool Loop 的节点与边。

    需保证 builder 已注册 entry（如 PM）与 exit_node（如 Retriever）。
    """
    builder.add_node("Architect", architect_node)
    builder.add_node("ArchTool", tool_call_node)
    builder.add_node("ArchFinalize", architect_finalize_node)

    builder.add_edge(entry, "Architect")
    builder.add_conditional_edges(
        "Architect",
        decide_from_architect,
        {"ArchTool": "ArchTool", "ArchFinalize": "ArchFinalize"},
    )
    builder.add_conditional_edges(
        "ArchTool",
        route_after_tool,
        {"Architect": "Architect", "ArchFinalize": "ArchFinalize"},
    )
    builder.add_edge("ArchFinalize", exit_node)
