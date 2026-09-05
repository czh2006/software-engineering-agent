"""Filesystem MCP Server（只读）— 使用 MCP Python SDK v2。

Server 名称：filesystem
工具（全部只读，不实现写入）：
- list_files(path)      -> { files: list[str] }
- read_file(path)       -> { path, content }
- search_files(query, path) -> { matching_files: list[str] }

安全约束：
- 所有路径限定在配置的 repository root 内；禁止 ../ 穿越与越界读取。
- 禁止读取 .env、私钥 / SSH key 等敏感文件。
- 单个文件最大 1MB。
- 目录递归深度限制为 5（遍历时跳过巨型/依赖目录）。

本模块不实现 Agent、不连接任何 LLM。
"""

import json
import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer

# ---------- 安全常量 ----------
MAX_FILE_SIZE_BYTES: int = 1024 * 1024  # 1MB
MAX_DEPTH: int = 5  # 目录递归深度上限

# 精确禁止的文件名
_FORBIDDEN_EXACT_NAMES = frozenset(
    {".env", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", "known_hosts", "authorized_keys"}
)
# 前缀（.env.local / .env.production 等）
_FORBIDDEN_PREFIXES = (".env.",)
# 私钥 / 证书类后缀
_FORBIDDEN_SUFFIXES = (
    ".pem", ".key", ".p12", ".pfx", ".ppk", ".p8", ".asc", ".gpg",
)
# 遍历时跳过的目录（巨型/隐藏/无源码价值）
_SKIP_DIRS = frozenset(
    {".git", ".ssh", ".venv", "venv", "node_modules", "__pycache__",
     "dist", "build", ".next", ".cache"}
)


def repository_root() -> Path:
    """返回配置的 repository root（可用 FILESYSTEM_ROOT 覆盖）。

    默认取本文件位置向上一级为仓库根：backend/mcp_servers -> repo root。
    """
    env = os.getenv("FILESYSTEM_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


# ---------- 安全工具函数 ----------

def _is_sensitive_name(name: str) -> bool:
    """文件名是否命中敏感规则（.env / 私钥 / SSH key / 证书）。"""
    if name in _FORBIDDEN_EXACT_NAMES:
        return True
    if name.startswith(_FORBIDDEN_PREFIXES):
        return True
    if name.lower().endswith(_FORBIDDEN_SUFFIXES):
        return True
    return False


def _resolve_within(root: Path, user_path: str) -> Path:
    """把用户路径解析到 root 内；../ 穿越或越界直接抛错。"""
    root = root.resolve()
    if user_path in ("", "."):
        return root
    candidate = (root / user_path).resolve()
    if candidate != root and not candidate.is_relative_to(root):
        raise ValueError(f"路径越界：{user_path!r}（限制在 {root} 内，禁止 ../ 穿越）")
    return candidate


def _check_path_inside(root: Path, user_path: str) -> Path:
    """校验路径属于 root 且目标本身不是敏感文件。"""
    candidate = _resolve_within(root, user_path)
    rel = candidate.relative_to(root)
    if any(part in (".ssh",) for part in rel.parts):
        raise ValueError("禁止访问 .ssh 目录")
    if _is_sensitive_name(candidate.name):
        raise ValueError(f"禁止读取敏感文件：{candidate.name!r}")
    return candidate


def _walk_files(root: Path, current: Path, depth: int, out: list[str]) -> None:
    """递归收集 root 下的普通文件（root-relative），限深 MAX_DEPTH。"""
    if depth > MAX_DEPTH:
        return
    try:
        entries = sorted(current.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return
    for entry in entries:
        if entry.is_dir():
            if entry.name in _SKIP_DIRS or entry.name in (".ssh",):
                continue
            _walk_files(root, entry, depth + 1, out)
        elif entry.is_file():
            if _is_sensitive_name(entry.name):
                continue
            out.append(entry.relative_to(root).as_posix())


# ---------- 核心实现（供测试与工具复用，root 显式传入） ----------

def list_files_impl(root: Path, path: str = ".") -> list[str]:
    """列出 path 目录下（递归、限深）的文件列表。"""
    root = root.resolve()
    base = _resolve_within(root, path)
    if not base.is_dir():
        raise ValueError(f"不是目录或不存在：{path!r}")

    files: list[str] = []
    _walk_files(root, base, 0, files)
    return files


def read_file_impl(root: Path, path: str) -> dict:
    """读取单个文件，返回 {path, content}；越界/敏感/超大均拒绝。"""
    root = root.resolve()
    candidate = _check_path_inside(root, path)
    if not candidate.is_file():
        raise ValueError(f"不是文件或不存在：{path!r}")

    if candidate.stat().st_size > MAX_FILE_SIZE_BYTES:
        raise ValueError(f"文件超过大小上限(1MB)：{candidate.name!r}")

    content = candidate.read_text(encoding="utf-8", errors="replace")
    return {"path": str(candidate), "content": content}


def search_files_impl(root: Path, query: str, path: str = ".") -> list[str]:
    """在 path 目录下按文件名匹配 query（子串、不区分大小写）。"""
    if not query or not query.strip():
        raise ValueError("query 不能为空")

    root = root.resolve()
    base = _resolve_within(root, path)
    if not base.is_dir():
        raise ValueError(f"不是目录或不存在：{path!r}")

    needle = query.strip().casefold()
    files: list[str] = []
    _walk_files(root, base, 0, files)
    return [f for f in files if needle in Path(f).name.casefold()]


# ---------- MCP Server 与工具注册 ----------

server = MCPServer(name="filesystem", version="0.1.0")


@server.tool(name="list_files", description="List files under a directory (read-only, max depth 5)")
def list_files(path: str = ".") -> dict:
    """列出目录下的文件。"""
    return {"files": list_files_impl(repository_root(), path)}


@server.tool(name="read_file", description="Read a single file's content (read-only, max 1MB)")
def read_file(path: str) -> dict:
    """读取文件内容。"""
    return read_file_impl(repository_root(), path)


@server.tool(name="search_files", description="Search files by filename substring")
def search_files(query: str, path: str = ".") -> dict:
    """按文件名子串搜索。"""
    return {"matching_files": search_files_impl(repository_root(), query, path)}


if __name__ == "__main__":
    # 启动（stdio 传输）
    server.run(transport="stdio")
