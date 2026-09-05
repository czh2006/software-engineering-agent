"""统一 MCP Tool Registry（discovery / routing / metadata）。

职责边界（重要）：
- discovery  —— 发现并注册可用的 MCP Server（进程内 MCPServer 实例）。
- routing    —— 维护 tool name -> MCP Server 的映射，按工具名找到承载它的 Server。
- metadata   —— 汇总每个工具的 name / description / input_schema 供外部（Agent / 客户端）查询。

明确不做的事：
- 不执行 shell / 不拉起 stdio 子进程 —— 只与已注册的进程内 MCPServer 握手（list_tools）。
- 不复制任何 Tool 的实现 —— 执行逻辑仍归属各 Server；Registry 只保存其元数据与路由。

本模块不实现 Agent、不连接任何 LLM。
"""

import importlib
from typing import Any, Protocol

from pydantic import BaseModel, Field

# ---------- 元数据模型 ----------

class ToolMetadata(BaseModel):
    """单个 MCP 工具的只读元数据（不含实现）。"""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    server_name: str
    server_version: str = ""


# ---------- Server 抽象（本仓库 4 个 MCP Server 均满足） ----------

class ToolServer(Protocol):
    """进程内 MCP Server 的最小接口（MCP SDK v2 的 MCPServer 已满足）。"""

    name: str
    version: str | None

    async def list_tools(self) -> list[Any]: ...


# ---------- 内置 Server discovery 名单 ----------
# 别名 -> 模块路径；仅"名单"，注册时才 import（避免模块级副作用）
BUILTIN_SERVER_MODULES: dict[str, str] = {
    "filesystem": "mcp_servers.filesystem_server",
    "git": "mcp_servers.git_server",
    "terminal": "mcp_servers.terminal_server",
    "python": "mcp_servers.python_server",
}


def builtin_server_names() -> list[str]:
    """发现：返回内置可发现的 MCP Server 名单（不 import、不连接）。"""
    return sorted(BUILTIN_SERVER_MODULES)


# ---------- Registry ----------

class MCPRegistry:
    """注册 + 连接 + 工具元数据 + 按工具名路由到 Server。"""

    def __init__(self) -> None:
        self._servers: dict[str, ToolServer] = {}
        self._tools: dict[str, ToolMetadata] = {}

    # -- 注册 / 注销（discovery） --

    def register_server(self, server: ToolServer) -> None:
        """注册一个进程内 MCP Server（重名则覆盖，并清空元数据缓存）。"""
        name = getattr(server, "name", None)
        if not name or not isinstance(name, str):
            raise ValueError("无法注册：Server 缺少字符串 name")
        self._servers[name] = server
        self._tools = {}  # 新 Server 可能改变工具集 → 下次连接时重建

    def unregister_server(self, name: str) -> None:
        """注销一个 Server；不存在时抛 ValueError。"""
        if name not in self._servers:
            raise ValueError(f"未注册的 Server：{name!r}")
        del self._servers[name]
        self._tools = {}

    def server_names(self) -> list[str]:
        """已注册 Server 的名字列表。"""
        return sorted(self._servers)

    def has_server(self, name: str) -> bool:
        return name in self._servers

    def get_server(self, name: str) -> ToolServer:
        if name not in self._servers:
            raise ValueError(f"未注册的 Server：{name!r}")
        return self._servers[name]

    # -- 连接（与进程内 Server 握手，拉取工具元数据） --

    async def connect(self) -> list[ToolMetadata]:
        """连接所有已注册 Server：调用各自 list_tools() 建立工具索引。

        返回全量工具元数据；跨 Server 出现同名工具视为冲突并报错。
        """
        tools: dict[str, ToolMetadata] = {}
        for server_name, server in self._servers.items():
            server_version = getattr(server, "version", None) or ""
            listed = await server.list_tools()
            for raw in listed:
                meta = _to_metadata(raw, server_name, server_version)
                if meta.name in tools:
                    raise ValueError(
                        f"工具名冲突：{meta.name!r} 已由 Server "
                        f"{tools[meta.name].server_name!r} 注册，又出现在 {server_name!r}"
                    )
                tools[meta.name] = meta
        self._tools = tools
        return list(self._tools.values())

    # -- 工具元数据（metadata） --

    async def list_tools(self) -> list[ToolMetadata]:
        """返回全部工具元数据；未连接则先连接。"""
        if not self._tools:
            await self.connect()
        return list(self._tools.values())

    def tool_names(self) -> list[str]:
        """全部工具名（需先 connect/list_tools）。"""
        self._ensure_connected()
        return sorted(self._tools)

    def tool_count(self) -> int:
        self._ensure_connected()
        return len(self._tools)

    def get_tool(self, name: str) -> ToolMetadata:
        """按名字取工具元数据；不存在抛 ValueError。"""
        self._ensure_connected()
        if name not in self._tools:
            raise ValueError(f"未知工具：{name!r}")
        return self._tools[name]

    def get_tool_description(self, name: str) -> str:
        return self.get_tool(name).description

    def get_tool_input_schema(self, name: str) -> dict[str, Any]:
        return self.get_tool(name).input_schema

    # -- 路由（routing）：tool name -> Server --

    def find_server_name(self, tool_name: str) -> str:
        """返回承载该工具的 Server 名。"""
        return self.get_tool(tool_name).server_name

    def server_for_tool(self, tool_name: str) -> ToolServer:
        """返回承载该工具的 Server 对象（供后续执行器调用，Registry 自身不执行）。"""
        return self.get_server(self.find_server_name(tool_name))

    # -- 内部 --

    def _ensure_connected(self) -> None:
        if not self._tools:
            raise RuntimeError("Registry 尚未连接：请先 await connect() 或 list_tools()")


def _to_metadata(raw: Any, server_name: str, server_version: str) -> ToolMetadata:
    name = getattr(raw, "name", None)
    if not name or not isinstance(name, str):
        raise ValueError(f"Server {server_name!r} 返回了无 name 的工具：{raw!r}")
    description = getattr(raw, "description", None) or ""
    schema = getattr(raw, "input_schema", None)
    if schema is None:
        schema = getattr(raw, "inputSchema", None)  # 兼容 camelCase 命名
    if not isinstance(schema, dict):
        schema = {}
    return ToolMetadata(
        name=name,
        description=description,
        input_schema=schema,
        server_name=server_name,
        server_version=server_version,
    )


# ---------- 便捷加载（discovery + 注册） ----------

def load_builtin_servers(target: MCPRegistry | None = None) -> list[str]:
    """导入并注册全部内置 MCP Server；返回已注册 Server 名单。"""
    reg = target if target is not None else registry
    for module_path in BUILTIN_SERVER_MODULES.values():
        module = importlib.import_module(module_path)
        reg.register_server(module.server)
    return reg.server_names()


# 模块级默认单例（可在需要统一索引时直接使用）
registry: MCPRegistry = MCPRegistry()
