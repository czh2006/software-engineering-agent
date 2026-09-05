"""Agent Node 封装：每个 Node 封装一个 Agent 的执行。

约定：
- 每个节点函数输入 WorkflowState；
- 返回 dict（仅含本节点更新的字段 + timeline），由 LangGraph 合并回 state；
- 每个节点执行后向 timeline 追加结构化条目 TimelineEntry：
  { agent_name, status, duration, timestamp }
"""

import time
from datetime import datetime, timezone
from typing import Callable

from graph.state import TimelineEntry, WorkflowState


def _complete_entry(agent_name: str, duration: float) -> TimelineEntry:
    """构造一条执行完成的时间线条目。"""
    return {
        "agent_name": agent_name,
        "status": "done",
        "duration": round(duration, 3),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _run_agent(state: WorkflowState, agent_name: str, fn: Callable, *args):
    """执行 Agent 并测量耗时，返回 (结果, 追加后的 timeline)。"""
    start = time.monotonic()
    result = fn(*args)
    duration = time.monotonic() - start
    timeline = [*state.get("timeline", []), _complete_entry(agent_name, duration)]
    return result, timeline


def pm_node(state: WorkflowState) -> dict:
    """PM Node：把用户需求拆解为 TaskPlan。"""
    from agents.pm_agent import generate_task_plan

    plan, timeline = _run_agent(
        state, "PM", generate_task_plan, state["user_request"]
    )
    return {"task_plan": plan, "timeline": timeline}


# Architect 的 Tool Loop 由 graph/architect_loop.py 提供（图级循环），此处不再定义。
def retriever_node(state: WorkflowState) -> dict:
    """Retriever Node：为任务计划检索相关代码片段。"""
    from agents.retriever_agent import retrieve_for_task_plan

    plan = state.get("task_plan")
    if plan is None:
        raise RuntimeError("Retriever 节点需要 task_plan（PM 未执行）")

    chunks, timeline = _run_agent(
        state, "Retriever", retrieve_for_task_plan, plan
    )
    return {"retrieved_chunks": chunks, "timeline": timeline}


def coder_node(state: WorkflowState) -> dict:
    """Coder Node：综合计划/架构/检索结果，产出实现计划 PatchPlan。"""
    from agents.coder_agent import generate_patch_plan

    plan = state.get("task_plan")
    architecture = state.get("architecture_analysis")
    chunks = state.get("retrieved_chunks") or []
    if plan is None or architecture is None:
        raise RuntimeError("Coder 节点需要 task_plan 与 architecture_analysis")

    patch, timeline = _run_agent(
        state, "Coder", generate_patch_plan, plan, architecture, chunks
    )
    return {"patch_plan": patch, "timeline": timeline}


def reviewer_node(state: WorkflowState) -> dict:
    """Reviewer Node：审查实现计划并给出结论。"""
    from agents.reviewer_agent import generate_review

    patch = state.get("patch_plan")
    if patch is None:
        raise RuntimeError("Reviewer 节点需要 patch_plan（Coder 未执行）")

    review, timeline = _run_agent(state, "Reviewer", generate_review, patch)
    return {"review_result": review, "timeline": timeline}

