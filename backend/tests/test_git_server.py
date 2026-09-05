"""git MCP Server 的 pytest 测试。

覆盖：四个只读工具 + 安全要求
（只读白名单 / 参数数组防注入 / 结构化 GitError / exit_code+stderr 捕获）。
"""

import subprocess
from pathlib import Path

import pytest

from mcp_servers import git_server as gs


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """测试内用系统 git 构造仓库（与 git_server 实现无关）。"""
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """构造带 已提交/已暂存/已修改/未跟踪 四种状态的仓库。"""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Tester")

    # commit 1
    (root / "a.py").write_text("print(1)\n", encoding="utf-8")
    _git(root, "add", "a.py")
    _git(root, "commit", "-q", "-m", "feat: add a.py")

    # commit 2（修改 a.py）
    (root / "a.py").write_text("print(2)\n", encoding="utf-8")
    _git(root, "add", "a.py")
    _git(root, "commit", "-q", "-m", "feat: update a.py")

    # 之后的状态：
    #   b.py 已暂存(staged) / a.py 已修改未暂存(unstaged) / c.py 未跟踪(untracked)
    (root / "b.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "add", "b.py")
    (root / "a.py").write_text("print(3)\n", encoding="utf-8")
    (root / "c.py").write_text("y = 2\n", encoding="utf-8")

    monkeypatch.setenv("GIT_ROOT", str(root))
    return root


# ---------- git_status ----------

def test_status_reports_branch_and_states(repo):
    st = gs.git_status()
    assert st["branch"] == "main"
    assert st["staged"] == ["b.py"]
    assert st["unstaged"] == ["a.py"]
    assert st["untracked"] == ["c.py"]


def test_status_states_are_disjoint(repo):
    st = gs.git_status()
    assert "a.py" not in st["staged"]
    assert "b.py" not in st["unstaged"]
    assert "c.py" not in st["staged"]
    assert "c.py" not in st["unstaged"]


# ---------- git_diff ----------

def test_diff_unstaged_by_default(repo):
    diff = gs.git_diff()["diff"]
    assert "diff --git a/a.py b/a.py" in diff
    assert "-print(2)" in diff
    assert "+print(3)" in diff
    assert "b.py" not in diff  # 已暂存的不应出现在未暂存 diff


def test_diff_staged_only(repo):
    diff = gs.git_diff(staged=True)["diff"]
    assert "diff --git a/b.py b/b.py" in diff
    assert "+x = 1" in diff
    assert "a.py" not in diff  # 未暂存的修改不应出现在暂存 diff


def test_diff_empty_when_clean(repo):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "chore: snapshot")
    assert gs.git_diff()["diff"] == ""
    assert gs.git_diff(staged=True)["diff"] == ""


# ---------- git_log ----------

def test_log_returns_newest_first(repo):
    commits = gs.git_log(limit=10)["commits"]
    assert len(commits) == 2
    assert commits[0]["message"] == "feat: update a.py"
    assert commits[1]["message"] == "feat: add a.py"
    for c in commits:
        assert len(c["commit_hash"]) == 40
        assert c["author"] == "Tester"
        assert c["timestamp"]


def test_log_respects_limit(repo):
    assert len(gs.git_log(limit=1)["commits"]) == 1


def test_log_invalid_limit_rejected(repo):
    with pytest.raises(gs.GitError):
        gs.git_log(limit=0)
    with pytest.raises(gs.GitError):
        gs.git_log(limit=1000)


# ---------- git_show ----------

def test_show_returns_commit_content(repo):
    head = gs.git_log(limit=1)["commits"][0]["commit_hash"]
    c = gs.git_show(head)
    assert c["commit_hash"] == head
    assert c["message"] == "feat: update a.py"
    assert c["author"] == "Tester"
    assert c["timestamp"]
    assert "-print(1)" in c["diff"]
    assert "+print(2)" in c["diff"]


def test_show_invalid_hash_raises_structured_error(repo):
    with pytest.raises(gs.GitError) as ei:
        gs.git_show("deadbeef")
    assert ei.value.exit_code is not None  # 捕获 exit_code
    assert ei.value.stderr  # 捕获 stderr


def test_show_rejects_option_like_rev(repo):
    with pytest.raises(gs.GitError):
        gs.git_show("-n")  # 防参数注入
    with pytest.raises(gs.GitError):
        gs.git_show("")


# ---------- 安全：只读白名单 / 结构化错误 ----------

@pytest.mark.parametrize(
    "bad_args",
    [
        ("commit", "-m", "x"),
        ("push",),
        ("reset", "--hard"),
        ("checkout", "main"),
        ("merge", "main"),
        ("rebase", "main"),
        ("rm", "a.py"),
    ],
)
def test_write_commands_rejected(repo, bad_args):
    with pytest.raises(gs.GitError, match="只读"):
        gs.run_git(repo, *bad_args)


def test_unknown_command_rejected(repo):
    with pytest.raises(gs.GitError):
        gs.run_git(repo, "banana")


def test_run_git_captures_failure(repo):
    with pytest.raises(gs.GitError) as ei:
        gs.run_git(repo, "show", "deadbeef")
    assert ei.value.exit_code != 0
    assert ei.value.stderr


def test_not_a_repo_raises(tmp_path):
    other = tmp_path / "not-a-repo"
    other.mkdir()
    with pytest.raises(gs.GitError):
        gs.git_status_impl(other)


def test_status_impl_explicit_root(repo, monkeypatch):
    monkeypatch.delenv("GIT_ROOT", raising=False)
    st = gs.git_status_impl(repo)
    assert st["branch"] == "main"
    assert st["staged"] == ["b.py"]


def test_repository_root_default(monkeypatch):
    monkeypatch.delenv("GIT_ROOT", raising=False)
    assert gs.repository_root() == Path(__file__).resolve().parents[2]


def test_git_error_to_dict():
    err = gs.GitError("boom", exit_code=128, stderr="fatal: x", command_args=("show", "x"))
    d = err.to_dict()
    assert d["error"] == "git_error"
    assert d["exit_code"] == 128
    assert d["stderr"] == "fatal: x"
