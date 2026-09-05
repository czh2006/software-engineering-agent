"""统一 MCP Client（MCP Python SDK v2，进程内连接）。

- connect(server)                         注册一个进程内 MCP Server 用于路由。
- list_tools([server_name])               工具发现：返回已注册 Server 的工具元数据。
- call_tool(server_name, tool_name, arguments)  调用某 Server 上的工具，返回规范化结果。

能力：
- async/await（MCP SDK v2 的 ClientSession + InMemoryTransport，进程内、无子进程）。
- 支持 structured_content：保留 server 返回的 structuredContent（若有）。
- 支持错误结果：工具内异常 -> isError 结果 -> CallResult(ok=False)，不抛给调用方；
  仅"未注册 Server / 路由缺失"等客户端错误抛 ValueError。
- 设置 timeout（默认 30s）：ClientSession read_timeout + asyncio.timeout 双层兜底。
- 工具调用日志：server / tool / arguments / duration / success（records + logging）。

连接模型（重要）：
- connect() 只做"注册"，不做长连接；每次 list_tools / call_tool 在一条短生命周期
  会话内完成（async with InMemoryTransport + ClientSession），由 SDK 负责正确收尾。
  这与官方示例的进程内测试模式一致，避免手工管理嵌套 task-group/cancel-scope 的脆性问题；
  每次操作含 initialize 握手，进程内开销可忽略。

明确不做的事：
- 不执行 shell / 不拉起子进程 / 不修改具体 MCP Server / 不复制任何工具实现。

本模块不实现 Agent、不连接任何 LLM。
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from pydantic import BaseModel, Field

from mcp.client._memory import InMemoryTransport
from mcp.client.session import ClientSession

logger = logging.getLogger("mcp_client")

DEFAULT_TIMEOUT_SECONDS: float = 30.0


# ---------- 元数据 / 结果 / 日志模型 ----------

class ToolInfo(BaseModel):
    """client 视角下的工具发现元数据。"""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    server_name: str


class CallResult(BaseModel):
    """单次工具调用的规范化结果。"""

    ok: bool
    is_error: bool
    content: str = ""  # 文本表示（拼接所有 TextContent）
    structured_content: Any = None  # server 的 structuredContent（若有）
    server_name: str
    tool_name: str
    duration_ms: int


class ToolCallRecord(BaseModel):
    """工具调用日志条目（server / tool / arguments / duration / success）。"""

    server: str
    tool: str
    arguments: dict[str, Any] | None
    duration: int  # ms
    success: bool


# ---------- 内部：单次操作的短生命周期会话 ----------

class _ServerConnection:
    """绑定一个进程内 Server；每次操作开启一条短生命周期 ClientSession。"""

    def __init__(self, server: Any, *, timeout_seconds: float) -> None:
        self.server = server
        self.name = getattr(server, "name", None)
        self._timeout_seconds = timeout_seconds

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[ClientSession]:
        """开启 InMemoryTransport + ClientSession 并完成 initialize 握手。"""
        async with InMemoryTransport(self.server) as (read, write):
            async with ClientSession(
                read, write, read_timeout_seconds=self._timeout_seconds
            ) as session:
                await session.initialize()
                yield session

    async def list_tools(self) -> list[ToolInfo]:
        async with self._session() as session:
            result = await session.list_tools()
        out: list[ToolInfo] = []
        for t in result.tools:
            name = getattr(t, "name", None)
            if not name:
                continue
            desc = getattr(t, "description", None) or ""
            schema = getattr(t, "input_schema", None)
            if schema is None:
                schema = getattr(t, "inputSchema", None)
            if not isinstance(schema, dict):
                schema = {}
            out.append(ToolInfo(name=name, description=desc, input_schema=schema, server_name=self.name or ""))
        return out

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None) -> Any:
        async with self._session() as session:
            return await session.call_tool(tool_name, arguments)


# ---------- 规范化 ----------

def normalize_result(raw: Any, server_name: str, tool_name: str, duration_ms: int) -> CallResult:
    """把 SDK 的 CallToolResult 规范化为 CallResult（文本 + structuredContent + isError）。"""
    is_error = bool(getattr(raw, "is_error", False))
    text = _content_to_text(getattr(raw, "content", None))
    structured = getattr(raw, "structured_content", None)
    return CallResult(
        ok=not is_error,
        is_error=is_error,
        content=text,
        structured_content=structured,
        server_name=server_name,
        tool_name=tool_name,
        duration_ms=duration_ms,
    )


def _content_to_text(content: Any) -> str:
    """把 content block 列表拼成纯文本。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict):
            text = block.get("text") or block.get("content")
        else:
            text = getattr(block, "text", None)
        if text is not None:
            parts.append(str(text))
    return "\n".join(parts)


# ---------- 统一 Client ----------

class MCPClient:
    """统一 MCP Client：注册多个 Server，提供发现 / 调用 / 路由 / 日志。"""

    def __init__(self, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        if timeout_seconds is None or timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须 > 0")
        self.timeout_seconds = float(timeout_seconds)
        self._connections: dict[str, _ServerConnection] = {}
        self._records: list[ToolCallRecord] = []

    # -- 注册 / 路由 --

    async def connect(self, server: Any, name: str | None = None) -> str:
        """注册一个进程内 MCP Server 供路由；返回名字（重名覆盖）。"""
        server_name = name or getattr(server, "name", None)
        if not server_name or not isinstance(server_name, str):
            raise ValueError("无法注册：Server 缺少字符串 name")
        self._connections[server_name] = _ServerConnection(
            server, timeout_seconds=self.timeout_seconds
        )
        return server_name

    async def disconnect(self, server_name: str) -> None:
        """注销一个 Server（无长连接需要关闭，仅移除路由）。"""
        if server_name not in self._connections:
            raise ValueError(f"未注册的 Server：{server_name!r}")
        del self._connections[server_name]

    async def aclose(self) -> None:
        """清空全部注册（幂等）。"""
        self._connections.clear()

    def connected_servers(self) -> list[str]:
        return sorted(self._connections)

    # -- 工具发现 --

    async def list_tools(self, server_name: str | None = None) -> list[ToolInfo]:
        """列出已注册 Server 的工具；server_name=None 时聚合所有。"""
        if server_name is not None:
            return await self._require(server_name).list_tools()
        out: list[ToolInfo] = []
        for name in sorted(self._connections):
            out.extend(await self._require(name).list_tools())
        return out

    # -- 工具调用 --

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> CallResult:
        """调用 server_name 上的工具，返回规范化 CallResult。

        - 超时 / 工具内错误 / 协议错误 -> CallResult(ok=False)，不抛给调用方。
        - 未知 Server -> ValueError（客户端路由错误）。
        """
        conn = self._require(server_name)
        arguments = dict(arguments) if arguments else {}
        start = time.monotonic()
        try:
            async with asyncio.timeout(self.timeout_seconds):
                raw = await conn.call_tool(tool_name, arguments)
            result = normalize_result(raw, server_name, tool_name, _ms(start))
        except TimeoutError:
            result = CallResult(
                ok=False,
                is_error=True,
                content=f"[timeout] 工具调用超时（>{self.timeout_seconds:g}s）：{server_name}.{tool_name}",
                server_name=server_name,
                tool_name=tool_name,
                duration_ms=_ms(start),
            )
        except Exception as exc:  # 协议级错误（如未知工具）也收敛为错误结果
            result = CallResult(
                ok=False,
                is_error=True,
                content=f"[mcp_error] {type(exc).__name__}: {exc}",
                server_name=server_name,
                tool_name=tool_name,
                duration_ms=_ms(start),
            )
        self._record(
            ToolCallRecord(
                server=server_name,
                tool=tool_name,
                arguments=arguments,
                duration=result.duration_ms,
                success=result.ok,
            )
        )
        return result

    # -- 日志 --

    @property
    def records(self) -> list[ToolCallRecord]:
        """返回全部工具调用日志（server/tool/arguments/duration/success）。"""
        return list(self._records)

    def clear_records(self) -> None:
        self._records.clear()

    # -- 内部 --

    def _require(self, server_name: str) -> _ServerConnection:
        conn = self._connections.get(server_name)
        if conn is None:
            raise ValueError(
                f"未注册的 Server：{server_name!r}（已注册：{self.connected_servers()}）"
            )
        return conn

    def _record(self, record: ToolCallRecord) -> None:
        self._records.append(record)
        logger.info(
            "tool_call server=%s tool=%s duration_ms=%d success=%s args=%s",
            record.server,
            record.tool,
            record.duration,
            record.success,
            record.arguments,
        )

    async def __aenter__(self) -> "MCPClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
