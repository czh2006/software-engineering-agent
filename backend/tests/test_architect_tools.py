"""Architect Agent（MCP 工具调用）测试。

验证（使用桩 LLM + 真实 MCP Client/filesystem Server，不连外部 LLM）：
- 对给定需求，Architect 会尝试调用 search_files / list_files 等只读工具；
- 工具结果并入最终上下文，最终产出 ArchitectureAnalysis；
- 禁用工具（terminal.run_command / python.run_python_file）被拒绝、不执行；
- 单次最多 8 次工具调用；工具失败后继续；每次调用记录 tool/arguments/duration/summary。
"""

import pytest

from app.schemas.workflow import TaskItem, TaskPlan
from agents.architect_agent import (
    ALLOWED_TOOL_NAMES,
    MAX_TOOL_CALLS,
    ArchitectureAnalysis,
    ArchitectureModule,
    ArchitectTools,
    PlannedToolCall,
    ToolPlan,
    build_mcp_tools,
    generate_architecture_analysis,
    generate_architecture_analysis_with_records,
)

ACCEPTANCE_REQUEST = "Analyze the authentication architecture of this repository."


def _make_plan(goal: str = ACCEPTANCE_REQUEST) -> TaskPlan:
    return TaskPlan(
        goal=goal,
        priority="high",
        tasks=[
            TaskItem(
                title="分析认证相关架构",
                description=goal,
                owner="architect",
                depends_on=[],
            )
        ],
        expected_files=["auth_service.py"],
    )


def _make_analysis(reasoning: str = "stub") -> ArchitectureAnalysis:
    return ArchitectureAnalysis(
        modules=[ArchitectureModule(name="auth", responsibility="认证模块", files=["auth_service.py"])],
        dependencies=[],
        risk=["low"],
        reasoning=reasoning,
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """临时仓库：含认证相关文件，filesystem server 以它为 root。"""
    (tmp_path / "auth_service.py").write_text("class AuthService: pass\n", encoding="utf-8")
    (tmp_path / "readme.txt").write_text("hello\n", encoding="utf-8")
    monkeypatch.setenv("FILESYSTEM_ROOT", str(tmp_path))
    return tmp_path


def _build_tools() -> ArchitectTools | None:
    return build_mcp_tools()


# ---------- 验收：会尝试 search_files，最终输出 ArchitectureAnalysis ----------

def test_acceptance_calls_search_files_and_returns_analysis(repo):
    tools = _build_tools()
    assert tools is not None and "filesystem.search_files" in tools.available_tools()

    def planner(plan, chunks):
        return ToolPlan(
            reasoning="需要确认认证相关文件",
            tool_calls=[PlannedToolCall(tool="filesystem.search_files", arguments={"query": "auth"})],
        )

    analyzer_seen: list = []

    def analyzer(plan, chunks, tool_results):
        analyzer_seen.append(tool_results)
        return _make_analysis(reasoning=f"tool_results={len(tool_results)}")

    analysis = generate_architecture_analysis(
        _make_plan(), [], tools=tools, planner=planner, analyzer=analyzer
    )

    assert isinstance(analysis, ArchitectureAnalysis)
    assert analysis.modules[0].name == "auth"

    # 至少尝试了一次 search_files 或 list_files
    assert any(r.tool in ("filesystem.search_files", "filesystem.list_files") for r in tools.records)
    assert len(tools.records) == 1
    rec = tools.records[0]
    assert rec.tool == "filesystem.search_files"
    assert rec.arguments == {"query": "auth"}
    assert rec.success is True
    assert "auth_service.py" in rec.summary  # 结构化结果进入记录
    assert rec.duration >= 0

    # 结果摘要确实进入了最终分析上下文
    assert analyzer_seen and len(analyzer_seen[0]) == 1


def test_acceptance_alt_list_files(repo):
    """备选验收路径：规划为 list_files 同样可行。"""
    tools = _build_tools()

    def planner(plan, chunks):
        return ToolPlan(
            reasoning="先看根目录结构",
            tool_calls=[PlannedToolCall(tool="filesystem.list_files", arguments={"path": "."})],
        )

    def analyzer(plan, chunks, tool_results):
        return _make_analysis()

    analysis = generate_architecture_analysis(
        _make_plan(), [], tools=tools, planner=planner, analyzer=analyzer
    )
    assert isinstance(analysis, ArchitectureAnalysis)
    assert tools.records[0].tool == "filesystem.list_files"
    assert tools.records[0].success is True
    assert "auth_service.py" in tools.records[0].summary


# ---------- 判断是否需要工具：可空 ----------

def test_no_tools_needed_when_planner_returns_empty(repo):
    tools = _build_tools()
    seen = []

    def planner(plan, chunks):
        return ToolPlan(reasoning="已有足够信息", tool_calls=[])

    def analyzer(plan, chunks, tool_results):
        seen.append(tool_results)
        return _make_analysis()

    analysis = generate_architecture_analysis(_make_plan(), [], tools=tools, planner=planner, analyzer=analyzer)
    assert isinstance(analysis, ArchitectureAnalysis)
    assert tools.records == []
    assert seen[0] == []  # 无工具结果并入上下文


# ---------- 禁用工具被拒绝（不执行） ----------

def test_disallowed_tools_are_blocked(repo):
    tools = _build_tools()

    def planner(plan, chunks):
        return ToolPlan(
            reasoning="尝试调用写/执行类工具",
            tool_calls=[
                PlannedToolCall(tool="terminal.run_command", arguments={"command": "rm -rf ."}),
                PlannedToolCall(tool="python.run_python_file", arguments={"path": "x.py"}),
                PlannedToolCall(tool="filesystem.list_files", arguments={"path": "."}),
            ],
        )

    def analyzer(plan, chunks, tool_results):
        return _make_analysis()

    generate_architecture_analysis(_make_plan(), [], tools=tools, planner=planner, analyzer=analyzer)

    assert len(tools.records) == 3
    assert tools.records[0].tool == "terminal.run_command"
    assert tools.records[0].success is False
    assert "blocked" in tools.records[0].summary
    assert tools.records[1].tool == "python.run_python_file"
    assert tools.records[1].success is False
    assert "blocked" in tools.records[1].summary
    # 白名单内的调用正常执行
    assert tools.records[2].tool == "filesystem.list_files"
    assert tools.records[2].success is True


# ---------- 上限 8 次 ----------

def test_max_tool_calls_capped(repo):
    tools = _build_tools()

    def planner(plan, chunks):
        calls = [
            PlannedToolCall(tool="filesystem.read_file", arguments={"path": "readme.txt"})
            for _ in range(MAX_TOOL_CALLS + 2)
        ]
        return ToolPlan(reasoning="反复读文件", tool_calls=calls)

    def analyzer(plan, chunks, tool_results):
        return _make_analysis()

    generate_architecture_analysis(_make_plan(), [], tools=tools, planner=planner, analyzer=analyzer)

    assert len(tools.records) == MAX_TOOL_CALLS  # 超过部分不执行


# ---------- 工具失败后继续 ----------

def test_tool_failure_does_not_abort(repo):
    tools = _build_tools()

    def planner(plan, chunks):
        return ToolPlan(
            reasoning="先读不存在的文件（失败），再搜 auth（成功）",
            tool_calls=[
                PlannedToolCall(tool="filesystem.read_file", arguments={"path": "missing.txt"}),
                PlannedToolCall(tool="filesystem.search_files", arguments={"query": "auth"}),
            ],
        )

    def analyzer(plan, chunks, tool_results):
        return _make_analysis(reasoning="仍然产出分析")

    analysis = generate_architecture_analysis(_make_plan(), [], tools=tools, planner=planner, analyzer=analyzer)

    assert isinstance(analysis, ArchitectureAnalysis)
    assert len(tools.records) == 2
    assert tools.records[0].success is False
    assert "missing.txt" in tools.records[0].summary or "error" in tools.records[0].summary.lower()
    assert tools.records[1].success is True
    assert "auth_service.py" in tools.records[1].summary


# ---------- 日志字段完整 ----------

def test_call_record_fields(repo):
    tools = _build_tools()

    def planner(plan, chunks):
        return ToolPlan(
            reasoning="x",
            tool_calls=[PlannedToolCall(tool="filesystem.search_files", arguments={"query": "auth"})],
        )

    def analyzer(plan, chunks, tool_results):
        return _make_analysis()

    generate_architecture_analysis(_make_plan(), [], tools=tools, planner=planner, analyzer=analyzer)

    rec = tools.records[0]
    for field in ("tool", "arguments", "duration", "success", "summary"):
        assert hasattr(rec, field)
    assert rec.tool == "filesystem.search_files"
    assert isinstance(rec.arguments, dict)
    assert isinstance(rec.duration, int)
    assert isinstance(rec.success, bool)
    assert isinstance(rec.summary, str) and rec.summary


# ---------- with_records 入口 ----------

def test_generate_with_records(repo):
    tools = _build_tools()

    def planner(plan, chunks):
        return ToolPlan(
            reasoning="x",
            tool_calls=[PlannedToolCall(tool="filesystem.search_files", arguments={"query": "auth"})],
        )

    def analyzer(plan, chunks, tool_results):
        return _make_analysis()

    analysis, records = generate_architecture_analysis_with_records(
        _make_plan(), [], tools=tools, planner=planner, analyzer=analyzer
    )
    assert isinstance(analysis, ArchitectureAnalysis)
    assert len(records) == 1
    assert records[0].tool == "filesystem.search_files"


# ---------- 默认路径：不注入 tools，仅空工具规划 ----------

def test_default_build_when_tools_omitted(repo):
    def planner(plan, chunks):
        return ToolPlan(reasoning="信息足够", tool_calls=[])

    def analyzer(plan, chunks, tool_results):
        return _make_analysis()

    # tools=None：内部走 build_mcp_tools()；规划为空则无工具执行
    analysis = generate_architecture_analysis(_make_plan(), [], planner=planner, analyzer=analyzer)
    assert isinstance(analysis, ArchitectureAnalysis)


# ---------- 默认 LLM 缺 key 时报错 ----------

def test_missing_api_key_raises(repo, monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "openai_api_key", None)
    with pytest.raises(ValueError):
        generate_architecture_analysis(_make_plan(), [], planner=None, analyzer=None)


# ---------- 常量/白名单 sanity ----------

def test_allowed_tool_names_are_readonly():
    assert ALLOWED_TOOL_NAMES == {
        "filesystem.list_files",
        "filesystem.read_file",
        "filesystem.search_files",
        "git.git_status",
        "git.git_log",
    }
    assert "terminal.run_command" not in ALLOWED_TOOL_NAMES
    assert "python.run_python_file" not in ALLOWED_TOOL_NAMES
    assert MAX_TOOL_CALLS == 8
