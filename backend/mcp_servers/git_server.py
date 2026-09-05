"""Git MCP Server（只读）— 使用 MCP Python SDK v2。

Server 名称：git
工具（全部只读，绝不写入）：
- git_status()               -> { branch, staged[], unstaged[], untracked[] }
- git_diff(staged=False)     -> { diff }
- git_log(limit=10)          -> { commits: [{commit_hash, author, message, timestamp}] }
- git_show(commit_hash)      -> { commit_hash, author, message, timestamp, diff }

安全约束：
- 只操作配置的 repository root（可用 GIT_ROOT 覆盖；默认取仓库根）。
- 只读白名单：仅允许 status/diff/log/show/branch/ls-files/rev-parse，
  从代码层面禁止 commit / push / reset / checkout 等写操作。
- 所有 subprocess 一律使用参数数组，禁止 shell=True。
- 设置 timeout；捕获 stdout / stderr / exit_code；异常以结构化 GitError 抛出。

本模块不实现 Agent、不连接任何 LLM。
"""

import os
import subprocess
from pathlib import Path

from mcp.server.mcpserver import MCPServer

# ---------- 常量 ----------
GIT_TIMEOUT_SECONDS: float = 30.0  # 每次 git 调用超时上限
MAX_LOG_LIMIT: int = 500  # git_log 的 limit 上限（防滥用）

# 只读子命令白名单（写命令 commit/push/reset/checkout 等一律拒绝）
_ALLOWED_READONLY_COMMANDS = frozenset(
    {"status", "diff", "log", "show", "branch", "ls-files", "rev-parse"}
)


# ---------- 结构化错误 ----------

class GitError(Exception):
    """Git 操作失败的统一结构化错误（携带 exit_code / stderr / 命令）。"""

    def __init__(
        self,
        message: str,
        *,
        exit_code: int | None = None,
        stderr: str | None = None,
        command_args: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code
        self.stderr = (stderr or "").strip()
        self.command_args = command_args

    def to_dict(self) -> dict:
        """机器可读的结构化错误载荷。"""
        return {
            "error": "git_error",
            "message": self.message,
            "exit_code": self.exit_code,
            "stderr": self.stderr,
        }


def repository_root() -> Path:
    """返回配置的 repository root（可用 GIT_ROOT 覆盖）。

    默认取本文件位置向上一级为仓库根：backend/mcp_servers -> repo root。
    """
    env = os.getenv("GIT_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


# ---------- subprocess 执行（参数数组 / 无 shell / 带超时 / 捕获三要素） ----------

def run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """执行只读 git 命令。

    - 白名单外子命令直接抛 GitError（从根上禁止 commit/push/reset/checkout）。
    - 参数数组调用，绝不使用 shell=True。
    - 超时 GIT_TIMEOUT_SECONDS；捕获 stdout/stderr/exit_code。
    - 非零退出码以结构化 GitError 抛出。
    """
    if not args:
        raise GitError("缺少 git 子命令")
    if args[0] not in _ALLOWED_READONLY_COMMANDS:
        raise GitError(
            f"禁止的 git 子命令：{args[0]!r}（本服务器只读，仅允许："
            f"{', '.join(sorted(_ALLOWED_READONLY_COMMANDS))}）"
        )

    root = Path(root).resolve()
    if not root.is_dir():
        raise GitError(f"repository root 不存在或不是目录：{root}")

    cmd = ["git", *args]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise GitError("未找到 git 可执行文件，请确认 git 已安装并加入 PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(
            f"git 命令超时（>{GIT_TIMEOUT_SECONDS:g}s）：{' '.join(cmd)}"
        ) from exc

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        snippet = stderr[:500] if stderr else ""
        raise GitError(
            f"git {' '.join(args)} 失败 (exit {proc.returncode})"
            + (f"：{snippet}" if snippet else ""),
            exit_code=proc.returncode,
            stderr=stderr,
            command_args=args,
        )
    return proc


def _lines(output: str) -> list[str]:
    """把命令输出拆成非空行列表（去掉行尾空白）。"""
    return [ln.strip() for ln in output.splitlines() if ln.strip()]


# ---------- 核心实现（供测试与工具复用，root 显式传入） ----------

def git_status_impl(root: Path) -> dict:
    """返回当前分支 + 暂存/未暂存/未跟踪 文件列表。"""
    root = Path(root).resolve()

    branch = run_git(root, "branch", "--show-current").stdout.strip()
    if not branch:
        # detached HEAD 场景：用短哈希标记当前提交
        try:
            short = run_git(root, "rev-parse", "--short", "HEAD").stdout.strip()
            branch = f"(detached HEAD {short})"
        except GitError:
            branch = "(detached HEAD)"

    staged = _lines(run_git(root, "diff", "--cached", "--name-only").stdout)
    unstaged = _lines(run_git(root, "diff", "--name-only").stdout)
    untracked = _lines(run_git(root, "ls-files", "--others", "--exclude-standard").stdout)

    return {"branch": branch, "staged": staged, "unstaged": unstaged, "untracked": untracked}


def git_diff_impl(root: Path, staged: bool = False) -> dict:
    """返回工作区（或暂存区）diff。"""
    root = Path(root).resolve()
    if staged:
        args = ("diff", "--cached", "--no-ext-diff", "--no-color")
    else:
        args = ("diff", "--no-ext-diff", "--no-color")
    return {"diff": run_git(root, *args).stdout}


def git_log_impl(root: Path, limit: int = 10) -> dict:
    """返回最近 limit 条提交（新→旧）。"""
    root = Path(root).resolve()
    if not isinstance(limit, int) or isinstance(limit, bool) or not (1 <= limit <= MAX_LOG_LIMIT):
        raise GitError(f"limit 必须是 1~{MAX_LOG_LIMIT} 的整数")

    # 每条记录以 \x1e 结尾；字段以 \x1f 分隔；%B 完整提交信息（允许跨行）
    fmt = "%H%x1f%an%x1f%aI%x1f%B%x1e"
    output = run_git(root, "log", "-n", str(limit), f"--pretty=format:{fmt}").stdout

    commits: list[dict] = []
    for record in output.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        parts = record.split("\x1f", 3)
        if len(parts) < 4:
            continue
        commit_hash, author, timestamp, message = parts
        commits.append(
            {
                "commit_hash": commit_hash,
                "author": author,
                "message": message.strip("\n"),
                "timestamp": timestamp,
            }
        )
    return {"commits": commits}


def git_show_impl(root: Path, commit_hash: str) -> dict:
    """返回单个 commit 的元信息 + 该提交引入的 diff。"""
    root = Path(root).resolve()
    if not commit_hash or not commit_hash.strip():
        raise GitError("commit_hash 不能为空")
    rev = commit_hash.strip()
    if rev.startswith("-"):
        raise GitError("commit_hash 不能以 '-' 开头（防参数注入）")

    fmt = "%H%x1f%an%x1f%aI%x1f%B"
    meta = run_git(root, "show", "-s", f"--format={fmt}", rev).stdout
    parts = meta.split("\x1f", 3)
    if len(parts) < 4:
        raise GitError(f"无法解析 commit 元数据：{rev!r}")
    full_hash, author, timestamp, message = parts

    diff_out = run_git(root, "show", "--no-ext-diff", "--no-color", "--format=", rev).stdout

    return {
        "commit_hash": full_hash,
        "author": author,
        "message": message.strip("\n"),
        "timestamp": timestamp,
        "diff": diff_out,
    }


# ---------- MCP Server 与工具注册 ----------

server = MCPServer(name="git", version="0.1.0")


@server.tool(name="git_status", description="Show git working-tree status: branch, staged, unstaged, untracked")
def git_status() -> dict:
    """查看仓库状态（只读）。"""
    return git_status_impl(repository_root())


@server.tool(name="git_diff", description="Show working-tree diff; pass staged=true for staged (cached) diff")
def git_diff(staged: bool = False) -> dict:
    """查看工作区/暂存区 diff（只读）。"""
    return git_diff_impl(repository_root(), staged)


@server.tool(name="git_log", description="List recent commit history (newest first)")
def git_log(limit: int = 10) -> dict:
    """查看最近提交历史（只读）。"""
    return git_log_impl(repository_root(), limit)


@server.tool(name="git_show", description="Show a single commit's metadata and its diff")
def git_show(commit_hash: str) -> dict:
    """查看单个 commit 内容（只读）。"""
    return git_show_impl(repository_root(), commit_hash)


if __name__ == "__main__":
    # 启动（stdio 传输）
    server.run(transport="stdio")
