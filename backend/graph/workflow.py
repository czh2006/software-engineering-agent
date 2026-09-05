"""Software Engineering Workflow（LangGraph 编排）。

节点顺序：
    START → PM → [Architect Tool Loop] → Retriever → Coder → Reviewer → END

其中 Architect Tool Loop（graph/architect_loop.py）为图级循环：
    Architect(决策) →(call_tool)→ ArchTool → Architect → … → ArchFinalize
- Architect 可反复调用只读 MCP 工具（经 MCP Client），单次最多 8 次；
- finish 或达到上限后由 ArchFinalize 产出 ArchitectureAnalysis，再进入 Retriever。

- 节点实现：graph/nodes.py（PM/Retriever/Coder/Reviewer）+ graph/architect_loop.py（Architect Loop）。
- State 使用 graph.state.WorkflowState。
"""

from langgraph.graph import END, START, StateGraph

from graph.architect_loop import add_architect_tool_loop
from graph.nodes import coder_node, pm_node, retriever_node, reviewer_node
from graph.state import WorkflowState


def build_workflow():
    """构建并编译 LangGraph StateGraph（PM → Architect Tool Loop → Retriever → Coder → Reviewer）。"""
    builder = StateGraph(WorkflowState)

    builder.add_node("PM", pm_node)
    builder.add_node("Retriever", retriever_node)
    builder.add_node("Coder", coder_node)
    builder.add_node("Reviewer", reviewer_node)

    builder.add_edge(START, "PM")
    # 注册 Architect/ArchTool/ArchFinalize，并连接 PM → …Loop… → Retriever
    add_architect_tool_loop(builder)
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
