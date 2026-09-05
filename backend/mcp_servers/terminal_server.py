"""Terminal MCP Server（受限命令执行）— 使用 MCP Python SDK v2。

Server 名称：terminal
工具：
- run_command(command, timeout_seconds=30)
    -> { command, stdout, stderr, exit_code, duration_ms }

安全约束：
1. 禁止 shell=True —— 一律 subprocess 参数数组。
2. command 必须经过解析 —— 用 quote-aware 分词器切成 argv（不是整串交给 shell）。
3. 只允许白名单命令：python / pytest / npm / node / ruff / mypy。
4. 显式禁止：rm / sudo / shutdown / reboot / chmod / curl / wget / git push / git reset / git clean。
5. 工作目录固定为 repository root（TERMINAL_ROOT 覆盖，默认仓库根），命令无法 cd。
6. timeout 限制 1~60 秒（默认 30）。
7. 捕获 TimeoutExpired / OSError 等异常。
8. 输出结构化结果：非零退出码 / 超时均作为 dict 返回，不抛错；仅非法输入抛 TerminalError。
9. 引号外禁止 shell 元字符（; | & < > ` $() 及 Windows % ^）——不允许任意管道/重定向/复合命令。
10. Windows 下仅对 .cmd/.bat（如 npm.cmd）用 cmd.exe /d /s /c 受控拉起，参数已全量校验。

本模块不实现 Agent、不连接任何 LLM。
"""

import os
import shutil
import subprocess
import time
from pathlib import Path

from mcp.server.mcpserver import MCPServer

# ---------- 策略常量 ----------
# 默认允许的命令（可执行文件白名单）
ALLOWED_COMMANDS: frozenset[str] = frozenset(
    {"python", "pytest", "npm", "node", "ruff", "mypy"}
)
# 显式禁止的单命令（清晰报错 + 防未来白名单扩展误放行）
FORBIDDEN_COMMANDS: frozenset[str] = frozenset(
    {"rm", "sudo", "shutdown", "reboot", "chmod", "curl", "wget"}
)
# git 只读之外的破坏性子命令
GIT_FORBIDDEN_SUBCOMMANDS: frozenset[str] = frozenset({"push", "reset", "clean"})

MAX_TIMEOUT_SECONDS: int = 60
DEFAULT_TIMEOUT_SECONDS: int = 30

# 引号外禁止的 shell 元字符（管道 / 重定向 / 复合命令 / 命令替换）
_SHELL_META = frozenset(";|&<>`")
# Windows cmd 环境下额外的注入字符
_WINDOWS_CMD_META = frozenset("%^")

# 凭据类环境变量后缀（默认不下发子进程，防被 python -c/脚本/生命周期脚本读取外传）
_SENSITIVE_ENV_SUFFIXES: tuple[str, ...] = (
    "_API_KEY", "_SECRET", "_SECRET_KEY", "_PASSWORD", "_PASSWD",
    "_TOKEN", "_CREDENTIAL", "_CREDENTIALS", "_ACCESS_KEY",
)


def _subprocess_env() -> dict[str, str]:
    """构造子进程环境：保留基本变量，默认剔除凭据类变量。

    运维若确实需要透传（如私有 npm registry 的 NPM_TOKEN），可设 MCP_EXEC_KEEP_ENV=1 放行。
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


class TerminalError(Exception):
    """非法命令 / 参数 / 环境问题的结构化错误（可携带机器可读载荷）。"""

    def __init__(self, message: str, *, code: str = "terminal_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code

    def to_dict(self) -> dict:
        return {"error": self.code, "message": self.message}


def repository_root() -> Path:
    """返回配置的 repository root（可用 TERMINAL_ROOT 覆盖）。

    默认取本文件位置向上一级为仓库根：backend/mcp_servers -> repo root。
    """
    env = os.getenv("TERMINAL_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


# ---------- 解析（无 shell，quote-aware 分词） ----------

def _parse_command(command: str) -> list[str]:
    """把 command 解析成 argv；引号外出现 shell 元字符即拒绝。

    规则：
    - 单/双引号成组并剥除；引号内字符原样保留（反斜杠不转义，兼容 Windows 路径）。
    - 引号外空白分词；引号外出现 ; | & < > ` $()（Windows 另含 % ^）→ 拒绝。
    - 反引号/重定向/管道/复合命令在无 shell 下无意义且危险，直接判非法。
    """
    if not command or not command.strip():
        raise TerminalError("command 不能为空")

    tokens: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i, n = 0, len(command)

    while i < n:
        ch = command[i]

        if quote is not None:
            if ch == quote:
                quote = None
            else:
                buf.append(ch)
            i += 1
            continue

        if ch in ("'", '"'):
            quote = ch
            i += 1
            continue

        if ch.isspace():
            if buf:
                tokens.append("".join(buf))
                buf = []
            i += 1
            continue

        if ch in _SHELL_META:
            raise TerminalError(
                f"命令含被禁止的 shell 字符 {ch!r}（不允许管道/重定向/复合命令）"
            )
        if os.name == "nt" and ch in _WINDOWS_CMD_META:
            raise TerminalError(
                f"命令含被禁止的字符 {ch!r}（Windows cmd 注入风险）"
            )
        if ch == "$" and i + 1 < n and command[i + 1] == "(":
            raise TerminalError("命令含被禁止的 $(...) 命令替换")

        buf.append(ch)
        i += 1

    if quote is not None:
        raise TerminalError("命令引号未闭合")
    if buf:
        tokens.append("".join(buf))
    if not tokens:
        raise TerminalError("command 解析后为空")
    return tokens


# ---------- 白名单 / 禁止清单校验 ----------

def _validate_tool(tokens: list[str]) -> str:
    tool = tokens[0]
    if tool in ALLOWED_COMMANDS:
        return tool
    if tool in FORBIDDEN_COMMANDS:
        raise TerminalError(f"禁止的命令：{tool!r}")
    if tool == "git":
        sub = tokens[1] if len(tokens) > 1 else ""
        if sub in GIT_FORBIDDEN_SUBCOMMANDS:
            raise TerminalError(f"禁止的 git 子命令：git {sub}")
        raise TerminalError("不允许的命令：git（git 只读操作请走 git MCP Server）")
    raise TerminalError(
        f"不允许的命令：{tool!r}（白名单：{', '.join(sorted(ALLOWED_COMMANDS))}）"
    )


# ---------- 执行 ----------

def _resolve_tool(tool: str) -> str:
    exe = shutil.which(tool)
    if exe is None:
        raise TerminalError(f"在 PATH 中找不到可执行文件：{tool!r}（请确认已安装）")
    return exe


def _build_argv(exe: str, args: list[str]) -> list[str]:
    """构造无 shell 的 argv。

    Windows 下仅 .cmd/.bat（如 npm.cmd）无法被 CreateProcess 直接执行，
    用 cmd.exe /d /s /c 受控拉起（参数经全量校验，无管道/重定向）。
    其余（python/pytest/node/ruff/mypy 的 .exe）直接参数数组执行。
    """
    argv = [exe, *args]
    if os.name == "nt" and exe.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/d", "/s", "/c", subprocess.list2cmdline(argv)]
    return argv


def _validate_timeout(timeout_seconds: int) -> int:
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
        raise TerminalError("timeout_seconds 必须是整数")
    if not (1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS):
        raise TerminalError(
            f"timeout_seconds 必须在 1~{MAX_TIMEOUT_SECONDS} 秒之间（当前 {timeout_seconds}）"
        )
    return timeout_seconds


def _to_text(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output


def run_command_impl(root: Path, command: str, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> dict:
    """在 root 内执行一条白名单命令，返回结构化结果。

    - 非零退出码 / 超时：正常返回 dict（exit_code 分别记为实际值 / None）。
    - 非法命令 / 超时参数越界 / 找不到可执行文件：抛 TerminalError。
    """
    root = Path(root).resolve()
    timeout = _validate_timeout(timeout_seconds)
    tokens = _parse_command(command)
    tool = _validate_tool(tokens)
    exe = _resolve_tool(tool)
    argv = _build_argv(exe, tokens[1:])

    env = _subprocess_env()

    start = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
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
        stderr += f"[timeout] 命令超时（>{timeout}s），进程已终止"
    except OSError as exc:
        raise TerminalError(f"执行 {tool!r} 失败：{exc}") from exc

    duration_ms = int((time.monotonic() - start) * 1000)
    return {
        "command": command,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
    }


# ---------- MCP Server 与工具注册 ----------

server = MCPServer(name="terminal", version="0.1.0")


@server.tool(
    name="run_command",
    description="Run a whitelisted command (python/pytest/npm/node/ruff/mypy) in the repository root; no shell, max 60s",
)
def run_command(command: str, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> dict:
    """执行白名单命令并返回结构化结果（只读约束见模块文档）。"""
    return run_command_impl(repository_root(), command, timeout_seconds)


if __name__ == "__main__":
    # 启动（stdio 传输）
    server.run(transport="stdio")
