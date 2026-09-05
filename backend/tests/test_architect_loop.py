"""Architect Tool Loop（LangGraph）测试。

用"桩 Architect 决策 + 真实 MCP Client / filesystem Server + 真实 LangGraph 循环图"验证：
1. 不需要工具：直接 finish 出分析
2. 一次工具调用
3. 多次工具调用
4. 工具失败（自动重试一次后继续）
5. 超过最大次数（8 次后强制停止并兜底出分析）

验证点：ToolCall/ToolResult 状态、最多 8 次、防死循环、每次 Tool Call 写 timeline、
节点不接触具体 MCP Tool（经 MCP Client）。
"""

import pytest

from langgraph.graph import END, START, StateGraph

from agents import architect_agent as aa
from app.schemas.workflow import TaskItem, TaskPlan
from graph import architect_loop as al
from graph.state import WorkflowState


# ---------- helpers ----------

def _make_plan() -> TaskPlan:
    return TaskPlan(
        goal="Analyze the authentication architecture of this repository.",
        priority="high",
        tasks=[TaskItem(title="分析认证架构", description="分析认证相关代码", owner="architect", depends_on=[])],
        expected_files=["auth_service.py"],
    )


def _analysis(reasoning: str = "stub-analysis") -> aa.ArchitectureAnalysis:
    return aa.ArchitectureAnalysis(
        modules=[aa.ArchitectureModule(name="auth", responsibility="认证模块", files=["auth_service.py"])],
        dependencies=[],
        risk=["low"],
        reasoning=reasoning,
    )


def _finish(reasoning: str = "信息已足够") -> aa.ArchitectAction:
    return aa.ArchitectAction(action="finish", reasoning=reasoning, analysis=_analysis(reasoning))


def _call(tool: str, arguments: dict | None = None) -> aa.ArchitectAction:
    return aa.ArchitectAction(action="call_tool", reasoning="需要探查", tool=tool, arguments=arguments or {})


def _turn_stub(script: list[aa.ArchitectAction]):
    it = iter(script)

    def stub(plan, chunks, summaries, *, available=None):
        try:
            return next(it)
        except StopIteration:
            return _finish("脚本耗尽，默认结束")

    return stub


def _build_loop_graph():
    builder = StateGraph(WorkflowState)

    def _noop(state):
        return {}

    builder.add_node("PM", _noop)
    builder.add_node("Retriever", _noop)
    builder.add_edge(START, "PM")
    al.add_architect_tool_loop(builder)  # entry=PM, exit=Retriever
    builder.add_edge("Retriever", END)
    return builder.compile()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    (tmp_path / "auth_service.py").write_text("class AuthService: pass\n", encoding="utf-8")
    monkeypatch.setenv("FILESYSTEM_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def tools(repo):
    """真实（进程内）MCP 工具运行器，root=repo。"""
    runner = aa.build_mcp_tools()
    assert runner is not None
    return runner


def _run_case(monkeypatch, tools, script):
    monkeypatch.setattr(aa, "architect_turn", _turn_stub(script))
    monkeypatch.setattr(al, "get_tool_runner", lambda: tools)
    graph = _build_loop_graph()
    initial = {"user_request": _make_plan().goal, "task_plan": _make_plan(), "retrieved_chunks": []}
    return graph.invoke(initial)


# ---------- 1. 不需要工具 ----------

def test_no_tools_needed(repo, tools, monkeypatch):
    res = _run_case(monkeypatch, tools, [_finish()])
    assert isinstance(res["architecture_analysis"], aa.ArchitectureAnalysis)
    assert res["architecture_analysis"].modules[0].name == "auth"
    assert (res.get("tool_calls_made") or 0) == 0
    assert (res.get("tool_log") or []) == []
    # 只有 Architect，没有 ArchTool timeline
    assert not any(e["agent_name"].startswith("ArchTool") for e in res.get("timeline", []))


# ---------- 2. 一次工具调用 ----------

def test_single_tool_call(repo, tools, monkeypatch):
    res = _run_case(
        monkeypatch,
        tools,
        [
            _call("filesystem.search_files", {"query": "auth"}),
            _finish("已拿到认证文件"),
        ],
    )
    assert isinstance(res["architecture_analysis"], aa.ArchitectureAnalysis)
    assert res["tool_calls_made"] == 1
    assert len(res["tool_log"]) == 1
    rec = res["tool_log"][0]
    assert rec.tool == "filesystem.search_files"
    assert rec.success is True
    assert "auth_service.py" in rec.summary
    # ToolCall/ToolResult 状态写入
    assert res["tool_call"].tool == "filesystem.search_files"
    assert "auth_service.py" in res["tool_result"]
    # timeline 记录这次 Tool Call
    tool_entries = [e for e in res["timeline"] if e["agent_name"].startswith("ArchTool")]
    assert len(tool_entries) == 1


# ---------- 3. 多次工具调用 ----------

def test_multiple_tool_calls(repo, tools, monkeypatch):
    res = _run_case(
        monkeypatch,
        tools,
        [
            _call("filesystem.search_files", {"query": "auth"}),
            _call("filesystem.list_files", {"path": "."}),
            _finish("信息足够"),
        ],
    )
    assert res["tool_calls_made"] == 2
    assert len(res["tool_log"]) == 2
    assert res["tool_log"][0].tool == "filesystem.search_files"
    assert res["tool_log"][1].tool == "filesystem.list_files"
    assert all(r.success for r in res["tool_log"])
    tool_entries = [e for e in res["timeline"] if e["agent_name"].startswith("ArchTool")]
    assert len(tool_entries) == 2


# ---------- 4. 工具失败（自动重试一次后继续） ----------

def test_tool_failure_retried_once_then_continue(repo, tools, monkeypatch):
    res = _run_case(
        monkeypatch,
        tools,
        [
            _call("filesystem.read_file", {"path": "missing.txt"}),
            _finish("读取失败但已记录，给出基于现有信息的分析"),
        ],
    )
    # 失败自动重试一次 → 实际执行 2 次，均为失败
    assert res["tool_calls_made"] == 2
    assert len(res["tool_log"]) == 2
    assert res["tool_log"][0].success is False
    assert res["tool_log"][1].success is False
    assert res["tool_log"][0].arguments == {"path": "missing.txt"}
    assert "error" in res["tool_log"][0].summary.lower()
    # 失败不中断：仍产出 ArchitectureAnalysis
    assert isinstance(res["architecture_analysis"], aa.ArchitectureAnalysis)
    tool_entries = [e for e in res["timeline"] if e["agent_name"].startswith("ArchTool")]
    assert len(tool_entries) == 2
    assert all(e["status"] == "failed" for e in tool_entries)


# ---------- 5. 超过最大次数（必须停止 + 兜底分析） ----------

def test_exceeds_max_tool_calls_stops_and_finalizes(repo, tools, monkeypatch):
    # Architect 每次都还要调工具（最多被调用 MAX_TOOL_CALLS 次）
    script = [_call("filesystem.search_files", {"query": "auth"}) for _ in range(al.MAX_TOOL_CALLS)]
    fallback_calls = {"n": 0}

    def fake_final(plan, chunks, summaries):
        fallback_calls["n"] += 1
        return _analysis("兜底分析：达到工具上限")

    monkeypatch.setattr(al, "_final_analyze", fake_final)
    res = _run_case(monkeypatch, tools, script)

    # 恰好执行 8 次即停（不多不少，防死循环）
    assert res["tool_calls_made"] == al.MAX_TOOL_CALLS
    assert len(res["tool_log"]) == al.MAX_TOOL_CALLS
    assert fallback_calls["n"] == 1  # 无最终分析 → 兜底分析生成一次
    assert isinstance(res["architecture_analysis"], aa.ArchitectureAnalysis)
    assert "兜底" in res["architecture_analysis"].reasoning
    tool_entries = [e for e in res["timeline"] if e["agent_name"].startswith("ArchTool")]
    assert len(tool_entries) == al.MAX_TOOL_CALLS
