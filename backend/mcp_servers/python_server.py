"""Python 文件执行 MCP Server（受限）— 使用 MCP Python SDK v2。

Server 名称：python
工具：
- run_python_file(path)
    -> { path, stdout, stderr, exit_code, duration_ms }

安全约束：
- path 必须位于 repository root 内（PYTHON_ROOT 覆盖，默认仓库根）；禁止 ../ 穿越与越界绝对路径。
- 只允许 .py 文件；目标必须是存在的普通文件。
- 用 subprocess 执行 Python 文件（sys.executable），timeout 上限 30 秒。
- 绝不 eval / 绝不 exec / 不接受任意 Python 字符串作为代码执行 —— 只运行磁盘上的文件。
- 非零退出码 / 超时作为结构化结果返回；仅路径/参数非法抛 ValueError。

本模块不实现 Agent、不连接任何 LLM。
"""

import os
import subprocess
import sys
import time
from pathlib import Path

from mcp.server.mcpserver import MCPServer

# ---------- 常量 ----------
MAX_TIMEOUT_SECONDS: int = 30  # 单次执行超时上限

# 凭据类环境变量后缀（默认不下发子进程，防被脚本读取外传）
_SENSITIVE_ENV_SUFFIXES: tuple[str, ...] = (
    "_API_KEY", "_SECRET", "_SECRET_KEY", "_PASSWORD", "_PASSWD",
    "_TOKEN", "_CREDENTIAL", "_CREDENTIALS", "_ACCESS_KEY",
)


def _subprocess_env() -> dict[str, str]:
    """构造子进程环境：保留基本变量，默认剔除凭据类变量。

    运维若确实需要透传，可设 MCP_EXEC_KEEP_ENV=1 放行。
    """
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if os.getenv("MCP_EXEC_KEEP_ENV"):
        return env
    for key in list(env):
        if key.upper().endswith(_SENSITIVE_ENV_SUFFIXES):
            env.pop(key)
    return env


def repository_root() -> Path:
    """返回配置的 repository root（可用 PYTHON_ROOT 覆盖）。

    默认取本文件位置向上一级为仓库根：backend/mcp_servers -> repo root。
    """
    env = os.getenv("PYTHON_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


# ---------- 路径护栏（禁止越界 / 仅 .py） ----------

def _resolve_within(root: Path, user_path: str) -> Path:
    """把用户路径解析到 root 内；../ 穿越或越界直接抛 ValueError。"""
    root = root.resolve()
    if user_path in ("", "."):
        return root
    candidate = (root / user_path).resolve()
    if candidate != root and not candidate.is_relative_to(root):
        raise ValueError(f"路径越界：{user_path!r}（限制在 {root} 内，禁止 ../ 穿越）")
    return candidate


def _require_py_file(root: Path, user_path: str) -> Path:
    """校验路径在 root 内、存在、是普通文件、扩展名是 .py。"""
    candidate = _resolve_within(root, user_path)
    if not candidate.is_file():
        raise ValueError(f"不是文件或不存在：{user_path!r}")
    if candidate.suffix.lower() != ".py":
        raise ValueError(f"只允许 .py 文件：{user_path!r}")
    return candidate


# ---------- 核心实现（供测试与工具复用，root 显式传入） ----------

def run_python_file_impl(
    root: Path,
    path: str,
    timeout_seconds: int = MAX_TIMEOUT_SECONDS,
) -> dict:
    """在 root 内以 subprocess 运行一个 .py 文件，返回结构化结果。

    - timeout_seconds 仅供内部/测试注入；上限 MAX_TIMEOUT_SECONDS（30）。
    - 绝不 eval / exec / 执行代码字符串。
    """
    root = Path(root).resolve()

    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
        raise ValueError("timeout_seconds 必须是整数")
    if not (1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS):
        raise ValueError(f"timeout_seconds 必须在 1~{MAX_TIMEOUT_SECONDS} 秒之间")

    target = _require_py_file(root, path)

    env = _subprocess_env()
    env["PYTHONDONTWRITEBYTECODE"] = "1"  # 运行不写 __pycache__

    start = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, str(target)],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            env=env,
        )
        exit_code = proc.returncode
        stdout = proc.stdout
        stderr = proc.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code = None
        stdout = _to_text(exc.stdout)
        stderr = _to_text(exc.stderr)
        if stderr and not stderr.endswith("\n"):
            stderr += "\n"
        stderr += f"[timeout] 运行超时（>{timeout_seconds}s），进程已终止"
    except OSError as exc:
        raise ValueError(f"运行 {path!r} 失败：{exc}") from exc

    duration_ms = int((time.monotonic() - start) * 1000)
    return {
        "path": str(target),
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
    }


def _to_text(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output


# ---------- MCP Server 与工具注册 ----------

server = MCPServer(name="python", version="0.1.0")


@server.tool(
    name="run_python_file",
    description="Run a .py file inside the repository root via subprocess (max 30s; no eval/exec)",
)
def run_python_file(path: str) -> dict:
    """运行仓库内一个 .py 文件并返回结构化结果。"""
    return run_python_file_impl(repository_root(), path)


if __name__ == "__main__":
    # 启动（stdio 传输）
    server.run(transport="stdio")
