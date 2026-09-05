"""统一 MCP Client 的 pytest。

覆盖：连接/断开、工具发现、路由、调用成功/错误结果、structured_content 规范化、
超时、调用日志（server/tool/arguments/duration/success）、多 Server 路由。
不修改任何真实 MCP Server。
"""

import asyncio
import time
from types import SimpleNamespace

import pytest

from mcp.server.mcpserver import MCPServer

from mcp_client.client import MCPClient, normalize_result
from mcp_servers import filesystem_server, python_server


def _run(coro) -> None:
    return asyncio.run(coro)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """临时 repository root：同时作为 python/filesystem 两个 Server 的工作目录。"""
    (tmp_path / "hello.py").write_text("print('hi-from-client')\n", encoding="utf-8")
    (tmp_path / "note.txt").write_text("filesystem-note\n", encoding="utf-8")
    monkeypatch.setenv("PYTHON_ROOT", str(tmp_path))
    monkeypatch.setenv("FILESYSTEM_ROOT", str(tmp_path))
    return tmp_path


def make_slow_server(name: str = "stub") -> MCPServer:
    """构造一个工具会长时间 sleep 的 MCPServer（供超时测试，async 可取消）。"""
    srv = MCPServer(name=name, version="0.0.1")

    @srv.tool(name="slow", description="sleeps for a while")
    async def slow(seconds: int = 60) -> dict:
        await asyncio.sleep(seconds)
        return {"ok": True}

    return srv


# ---------- 连接管理 ----------

def test_connect_disconnect_and_aclose(repo):
    async def main():
        c = MCPClient()
        try:
            name = await c.connect(python_server.server)
            assert name == "python"
            assert c.connected_servers() == ["python"]
            await c.disconnect("python")
            assert c.connected_servers() == []
            with pytest.raises(ValueError):
                await c.disconnect("python")
            await c.aclose()  # 幂等
            await c.aclose()
        finally:
            await c.aclose()

    _run(main())


def test_connect_requires_name():
    class NoName:
        async def list_tools(self):
            return []

    async def main():
        c = MCPClient()
        with pytest.raises(ValueError):
            await c.connect(NoName())  # type: ignore[arg-type]
        await c.aclose()

    _run(main())


# ---------- 工具发现 ----------

def test_list_tools_single_server(repo):
    async def main():
        async with MCPClient() as c:
            await c.connect(python_server.server)
            tools = await c.list_tools("python")
            assert [t.name for t in tools] == ["run_python_file"]
            ti = tools[0]
            assert "py" in ti.description
            assert "path" in ti.input_schema.get("properties", {})
            assert ti.server_name == "python"

    _run(main())


def test_list_tools_aggregate_across_servers(repo):
    async def main():
        async with MCPClient() as c:
            await c.connect(filesystem_server.server)
            await c.connect(python_server.server)
            tools = await c.list_tools()
            by_server = {t.name: t.server_name for t in tools}
            assert by_server["list_files"] == "filesystem"
            assert by_server["read_file"] == "filesystem"
            assert by_server["search_files"] == "filesystem"
            assert by_server["run_python_file"] == "python"

    _run(main())


# ---------- 调用：成功 ----------

def test_call_tool_success(repo):
    async def main():
        async with MCPClient() as c:
            await c.connect(python_server.server)
            res = await c.call_tool("python", "run_python_file", {"path": "hello.py"})
            assert res.ok and not res.is_error
            assert res.server_name == "python"
            assert res.tool_name == "run_python_file"
            assert "hi-from-client" in res.content
            assert res.duration_ms >= 0

    _run(main())


def test_call_filesystem_read_file(repo):
    async def main():
        async with MCPClient() as c:
            await c.connect(filesystem_server.server)
            res = await c.call_tool("filesystem", "read_file", {"path": "note.txt"})
            assert res.ok
            assert "filesystem-note" in res.content

    _run(main())


# ---------- 调用：错误结果 / 路由错误 ----------

def test_call_tool_error_result(repo):
    async def main():
        async with MCPClient() as c:
            await c.connect(python_server.server)
            res = await c.call_tool("python", "run_python_file", {"path": "missing.py"})
            assert not res.ok and res.is_error  # 工具内异常 -> isError 结果，不抛出
            assert res.server_name == "python"
            assert res.tool_name == "run_python_file"

    _run(main())


def test_call_unknown_server_raises(repo):
    async def main():
        async with MCPClient() as c:
            with pytest.raises(ValueError):
                await c.call_tool("nope", "run_python_file", {})

    _run(main())


def test_call_unknown_tool_returns_error_result(repo):
    async def main():
        async with MCPClient() as c:
            await c.connect(python_server.server)
            res = await c.call_tool("python", "no_such_tool", {})
            assert not res.ok and res.is_error
            assert "no_such_tool" in res.content

    _run(main())


# ---------- 调用：超时 ----------

def test_call_tool_timeout_returns_error_result(repo):
    async def main():
        c = MCPClient(timeout_seconds=1)
        try:
            await c.connect(make_slow_server("stub"))
            t0 = time.monotonic()
            res = await c.call_tool("stub", "slow", {"seconds": 60})
            elapsed = time.monotonic() - t0
            assert not res.ok and res.is_error
            assert "timeout" in res.content.lower()
            assert elapsed < 10
            assert res.duration_ms < 10_000
            assert c.records[-1].success is False
        finally:
            await c.aclose()

    _run(main())


# ---------- 调用日志 ----------

def test_call_records_fields(repo):
    async def main():
        async with MCPClient() as c:
            await c.connect(python_server.server)
            await c.call_tool("python", "run_python_file", {"path": "hello.py"})  # 成功
            await c.call_tool("python", "run_python_file", {"path": "missing.py"})  # 失败
            recs = c.records
            assert len(recs) == 2
            ok_rec, err_rec = recs
            assert ok_rec.server == "python"
            assert ok_rec.tool == "run_python_file"
            assert ok_rec.arguments == {"path": "hello.py"}
            assert isinstance(ok_rec.duration, int) and ok_rec.duration >= 0
            assert ok_rec.success is True
            assert err_rec.success is False
            c.clear_records()
            assert c.records == []

    _run(main())


# ---------- structured_content 规范化 ----------

def test_normalize_result_structured_content():
    raw = SimpleNamespace(
        is_error=False,
        content=[SimpleNamespace(text="hello")],
        structured_content={"answer": 42},
    )
    r = normalize_result(raw, "srv", "tool", 5)
    assert r.ok and not r.is_error
    assert r.content == "hello"
    assert r.structured_content == {"answer": 42}
    assert r.duration_ms == 5


def test_normalize_result_error_flag():
    raw = SimpleNamespace(is_error=True, content=[SimpleNamespace(text="boom")], structured_content=None)
    r = normalize_result(raw, "srv", "tool", 1)
    assert not r.ok and r.is_error
    assert r.content == "boom"


def test_normalize_result_dict_content_blocks():
    raw = SimpleNamespace(
        is_error=False,
        content=[{"type": "text", "text": "a"}, {"text": "b"}],
        structured_content=None,
    )
    r = normalize_result(raw, "srv", "tool", 0)
    assert r.content == "a\nb"
