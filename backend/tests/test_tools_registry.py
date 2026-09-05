"""MCP Tool Registry 的单元测试。

覆盖：注册/注销、连接(list_tools 握手)、元数据（name/description/input_schema）、
路由（tool name -> Server）、冲突检测、内置 discovery 与真实 Server 集成。
Registry 不执行 shell / 不复制工具实现 —— 测试只验证索引与元数据。
"""

import asyncio
from typing import Any

import pytest

from tools.registry import (
    BUILTIN_SERVER_MODULES,
    MCPRegistry,
    ToolMetadata,
    builtin_server_names,
    load_builtin_servers,
)


def _run(coro) -> Any:
    return asyncio.run(coro)


# ---------- 桩：进程内 MCPServer 的最小替身 ----------

class FakeTool:
    def __init__(self, name: str, description: str = "", input_schema: dict | None = None) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema or {"type": "object", "properties": {}}


class FakeServer:
    def __init__(self, name: str, tools: list[FakeTool], version: str = "0.0.1") -> None:
        self.name = name
        self.version = version
        self._tools = tools

    async def list_tools(self) -> list[FakeTool]:
        return self._tools


def make_server(name: str, specs: list[dict]) -> FakeServer:
    tools = [
        FakeTool(name=s["name"], description=s.get("description", ""), input_schema=s.get("input_schema"))
        for s in specs
    ]
    return FakeServer(name, tools)


# ---------- 注册 / 注销 ----------

def test_register_and_server_names():
    reg = MCPRegistry()
    reg.register_server(make_server("alpha", [{"name": "a_tool"}]))
    reg.register_server(make_server("beta", [{"name": "b_tool"}]))
    assert reg.server_names() == ["alpha", "beta"]
    assert reg.has_server("alpha")
    assert not reg.has_server("nope")


def test_register_requires_name():
    class NoName:
        async def list_tools(self):
            return []

    reg = MCPRegistry()
    with pytest.raises(ValueError):
        reg.register_server(NoName())  # type: ignore[arg-type]


def test_unregister_server():
    reg = MCPRegistry()
    reg.register_server(make_server("alpha", [{"name": "a_tool"}]))
    reg.unregister_server("alpha")
    assert reg.server_names() == []
    with pytest.raises(ValueError):
        reg.unregister_server("alpha")


# ---------- 连接 / list_tools / 元数据 ----------

def test_connect_builds_tool_index():
    reg = MCPRegistry()
    reg.register_server(
        make_server("fs", [{"name": "read_file", "description": "读取文件"}, {"name": "list_files"}])
    )
    metas = _run(reg.connect())
    assert {m.name for m in metas} == {"read_file", "list_files"}
    read = reg.get_tool("read_file")
    assert isinstance(read, ToolMetadata)
    assert read.description == "读取文件"
    assert read.server_name == "fs"


def test_list_tools_auto_connects():
    reg = MCPRegistry()
    reg.register_server(make_server("fs", [{"name": "read_file"}]))
    metas = _run(reg.list_tools())  # 未显式 connect 也会触发
    assert len(metas) == 1
    assert metas[0].name == "read_file"
    assert metas[0].server_version == "0.0.1"


def test_tool_names_sorted_and_metadata():
    reg = MCPRegistry()
    reg.register_server(make_server("s", [{"name": "b"}, {"name": "a"}]))
    _run(reg.connect())
    assert reg.tool_names() == ["a", "b"]
    assert reg.tool_count() == 2


def test_get_description_and_input_schema():
    reg = MCPRegistry()
    schema = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
    reg.register_server(make_server("fs", [{"name": "read_file", "description": "d", "input_schema": schema}]))
    _run(reg.connect())
    assert reg.get_tool_description("read_file") == "d"
    assert reg.get_tool_input_schema("read_file") == schema


def test_description_defaults_empty_when_none():
    reg = MCPRegistry()
    reg.register_server(make_server("s", [{"name": "t", "description": None}]))  # type: ignore[dict-item]
    _run(reg.connect())
    assert reg.get_tool_description("t") == ""


def test_unknown_tool_raises():
    reg = MCPRegistry()
    reg.register_server(make_server("s", [{"name": "a"}]))
    _run(reg.connect())
    with pytest.raises(ValueError):
        reg.get_tool("missing")
    with pytest.raises(ValueError):
        reg.get_tool_description("missing")


def test_access_before_connect_raises():
    reg = MCPRegistry()
    reg.register_server(make_server("s", [{"name": "a"}]))
    with pytest.raises(RuntimeError):
        reg.tool_names()


# ---------- 路由 ----------

def test_find_server_for_tool():
    fs = make_server("fs", [{"name": "read_file"}])
    git = make_server("git", [{"name": "git_status"}])
    reg = MCPRegistry()
    reg.register_server(fs)
    reg.register_server(git)
    _run(reg.connect())
    assert reg.find_server_name("read_file") == "fs"
    assert reg.find_server_name("git_status") == "git"
    assert reg.server_for_tool("read_file") is fs
    assert reg.server_for_tool("git_status") is git


def test_find_server_unknown_tool_raises():
    reg = MCPRegistry()
    reg.register_server(make_server("s", [{"name": "a"}]))
    _run(reg.connect())
    with pytest.raises(ValueError):
        reg.find_server_name("missing")


def test_duplicate_tool_name_conflict():
    reg = MCPRegistry()
    reg.register_server(make_server("one", [{"name": "dup"}]))
    reg.register_server(make_server("two", [{"name": "dup"}]))
    with pytest.raises(ValueError, match="冲突"):
        _run(reg.connect())


def test_register_same_name_overwrites_and_invalidates():
    reg = MCPRegistry()
    reg.register_server(make_server("srv", [{"name": "old_tool"}]))
    _run(reg.connect())
    assert reg.tool_names() == ["old_tool"]
    reg.register_server(make_server("srv", [{"name": "new_tool"}]))  # 覆盖同名 Server
    # 缓存已失效：未重连前同步访问会报错，connect 后只有新 Server 的工具
    with pytest.raises(RuntimeError):
        reg.tool_names()
    _run(reg.connect())
    assert reg.tool_names() == ["new_tool"]


# ---------- 内置 discovery / 真实 Server 集成 ----------

def test_builtin_server_names_without_import():
    assert builtin_server_names() == ["filesystem", "git", "python", "terminal"]
    assert set(BUILTIN_SERVER_MODULES) == {"filesystem", "git", "terminal", "python"}


def test_load_builtin_servers_connect_all():
    reg = MCPRegistry()
    names = load_builtin_servers(reg)
    assert names == ["filesystem", "git", "python", "terminal"]
    metas = _run(reg.connect())
    tool_names = {m.name for m in metas}
    assert tool_names == {
        "list_files", "read_file", "search_files",        # filesystem
        "git_status", "git_diff", "git_log", "git_show",  # git
        "run_command",                                    # terminal
        "run_python_file",                                # python
    }
    # 路由到正确 Server（真实对象）
    assert reg.find_server_name("list_files") == "filesystem"
    assert reg.find_server_name("git_status") == "git"
    assert reg.find_server_name("run_command") == "terminal"
    assert reg.find_server_name("run_python_file") == "python"


def test_real_filesystem_server_metadata():
    from mcp_servers import filesystem_server

    reg = MCPRegistry()
    reg.register_server(filesystem_server.server)
    _run(reg.connect())
    read = reg.get_tool("read_file")
    assert read.server_name == "filesystem"
    assert "path" in read.input_schema.get("properties", {})
    assert reg.server_for_tool("search_files") is filesystem_server.server


# ---------- 元数据模型 ----------

def test_tool_metadata_defaults():
    m = ToolMetadata(name="x", server_name="s")
    assert m.description == ""
    assert m.input_schema == {}
    assert m.server_version == ""
