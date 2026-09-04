"""Software Engineering Workflow（LangGraph 编排）。

节点顺序（用户定义）：
    START → PM → Architect → Retriever → Coder → Reviewer → END

- 每个节点调用对应 Agent，并把产出写入 WorkflowState。
- State 使用 graph.state.WorkflowState。
- 各节点返回的 dict 由 LangGraph 自动合并回共享 state。
"""

from langgraph.graph import END, START, StateGraph

from graph.state import WorkflowState


def _append_timeline(state: WorkflowState, step: str) -> list[str]:
    """向 timeline 追加一个步骤记录。"""
    return [*state.get("timeline", []), step]


def pm_node(state: WorkflowState) -> dict:
    """PM：把用户需求拆解为 TaskPlan。"""
    from agents.pm_agent import generate_task_plan

    plan = generate_task_plan(state["user_request"])
    return {
        "task_plan": plan,
        "timeline": _append_timeline(state, "PM: 任务拆解完成"),
    }


def architect_node(state: WorkflowState) -> dict:
    """Architect：基于任务计划做架构分析（在检索之前，暂无代码片段）。"""
    from agents.architect_agent import generate_architecture_analysis

    plan = state.get("task_plan")
    if plan is None:
        raise RuntimeError("Architect 节点需要 task_plan（PM 未执行）")

    analysis = generate_architecture_analysis(plan, [])
    return {
        "architecture_analysis": analysis,
        "timeline": _append_timeline(state, "Architect: 架构分析完成"),
    }


def retriever_node(state: WorkflowState) -> dict:
    """Retriever：为任务计划检索相关代码片段。"""
    from agents.retriever_agent import retrieve_for_task_plan

    plan = state.get("task_plan")
    if plan is None:
        raise RuntimeError("Retriever 节点需要 task_plan（PM 未执行）")

    chunks = retrieve_for_task_plan(plan)
    return {
        "retrieved_chunks": chunks,
        "timeline": _append_timeline(state, "Retriever: 代码检索完成"),
    }


def coder_node(state: WorkflowState) -> dict:
    """Coder：综合计划/架构/检索结果，产出实现计划 PatchPlan。"""
    from agents.coder_agent import generate_patch_plan

    plan = state.get("task_plan")
    architecture = state.get("architecture_analysis")
    chunks = state.get("retrieved_chunks") or []
    if plan is None or architecture is None:
        raise RuntimeError("Coder 节点需要 task_plan 与 architecture_analysis")

    patch = generate_patch_plan(plan, architecture, chunks)
    return {
        "patch_plan": patch,
        "timeline": _append_timeline(state, "Coder: 实现计划完成"),
    }


def reviewer_node(state: WorkflowState) -> dict:
    """Reviewer：审查实现计划并给出结论。"""
    from agents.reviewer_agent import generate_review

    patch = state.get("patch_plan")
    if patch is None:
        raise RuntimeError("Reviewer 节点需要 patch_plan（Coder 未执行）")

    review = generate_review(patch)
    return {
        "review_result": review,
        "timeline": _append_timeline(state, "Reviewer: 审查完成"),
    }


def build_workflow():
    """构建并编译 LangGraph StateGraph（PM → Architect → Retriever → Coder → Reviewer）。"""
    builder = StateGraph(WorkflowState)

    builder.add_node("PM", pm_node)
    builder.add_node("Architect", architect_node)
    builder.add_node("Retriever", retriever_node)
    builder.add_node("Coder", coder_node)
    builder.add_node("Reviewer", reviewer_node)

    builder.add_edge(START, "PM")
    builder.add_edge("PM", "Architect")
    builder.add_edge("Architect", "Retriever")
    builder.add_edge("Retriever", "Coder")
    builder.add_edge("Coder", "Reviewer")
    builder.add_edge("Reviewer", END)

    return builder.compile()


# 模块级编译一次，供外部直接调用
workflow = build_workflow()


def run_workflow(user_request: str) -> dict:
    """以用户需求启动整个 Workflow，返回最终 WorkflowState。"""
    return workflow.invoke({"user_request": user_request})


if __name__ == "__main__":
    import json
    import sys

    request = sys.argv[1] if len(sys.argv) > 1 else "Add Google OAuth login."
    final_state = run_workflow(request)
    print(json.dumps(final_state, indent=2, ensure_ascii=False, default=str))
