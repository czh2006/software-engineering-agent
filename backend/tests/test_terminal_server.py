"""terminal MCP Server 的 pytest 测试。

覆盖（对应需求）：
- 正常 pytest（白名单内、工作目录=repository root、结构化返回）
- 非法命令（禁止清单 / 白名单外 / shell 元字符）
- 超时（返回结构化结果，exit_code=None）
- exit code != 0（非零退出码正常返回）
外加：python/node/npm 白名单执行、timeout 参数越界、空命令、默认 root。
"""

import shutil
from pathlib import Path

import pytest

from mcp_servers import terminal_server as ts


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """构造一个可被 pytest 收集通过的临时"repository root"。"""
    (tmp_path / "test_sample.py").write_text(
        "def test_ok():\n    assert 1 + 1 == 2\n", encoding="utf-8"
    )
    monkeypatch.setenv("TERMINAL_ROOT", str(tmp_path))
    return tmp_path


# ---------- 正常执行 ----------

def test_run_pytest_normal(repo):
    """工具层：在 repository root 里跑 pytest，正常返回 0。"""
    res = ts.run_command("pytest -q")
    assert res["exit_code"] == 0
    assert "passed" in res["stdout"]
    assert res["command"] == "pytest -q"
    assert isinstance(res["stderr"], str)
    assert res["duration_ms"] >= 0


def test_run_python_stdout_explicit_root(repo, monkeypatch):
    monkeypatch.delenv("TERMINAL_ROOT", raising=False)
    res = ts.run_command_impl(repo, 'python -c "print(41 + 1)"')
    assert res["exit_code"] == 0
    assert "42" in res["stdout"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node 不在 PATH")
def test_node_allowed(repo):
    res = ts.run_command_impl(repo, 'node -e "console.log(7)"')
    assert res["exit_code"] == 0
    assert "7" in res["stdout"]


@pytest.mark.skipif(shutil.which("npm") is None, reason="npm 不在 PATH")
def test_npm_allowed_via_cmd_shim(repo):
    """npm 是 .cmd shim，走受控 cmd.exe 路径也应成功。"""
    res = ts.run_command_impl(repo, "npm --version")
    assert res["exit_code"] == 0
    assert res["stdout"].strip()


# ---------- 非法命令 ----------

@pytest.mark.parametrize(
    "cmd",
    [
        "rm -rf x",
        "sudo reboot",
        "shutdown -h now",
        "chmod 777 a.py",
        "curl http://example.com",
        "wget http://example.com",
        "git push origin main",
        "git reset --hard",
        "git clean -fd",
    ],
)
def test_forbidden_commands_rejected(repo, cmd):
    with pytest.raises(ts.TerminalError):
        ts.run_command_impl(repo, cmd)


def test_not_in_whitelist_rejected(repo):
    with pytest.raises(ts.TerminalError, match="白名单"):
        ts.run_command_impl(repo, "gcc --version")


@pytest.mark.parametrize(
    "cmd",
    [
        "pytest -q | sort",          # 管道
        "pytest -q && echo done",    # 复合命令
        "pytest -q > out.txt",       # 重定向
        'python -c "x" ; echo hi',   # 引号外分号
        "python -c \"print(1)\" $(ls)",  # 命令替换
        "python -c \"print(1)\" `ls`",   # 反引号
    ],
)
def test_shell_operators_rejected(repo, cmd):
    with pytest.raises(ts.TerminalError):
        ts.run_command_impl(repo, cmd)


def test_empty_command_rejected(repo):
    with pytest.raises(ts.TerminalError):
        ts.run_command_impl(repo, "")
    with pytest.raises(ts.TerminalError):
        ts.run_command_impl(repo, "   ")


def test_unclosed_quote_rejected(repo):
    with pytest.raises(ts.TerminalError):
        ts.run_command_impl(repo, 'python -c "print(1)')


# ---------- 超时 ----------

def test_timeout_returns_structured_result(repo):
    res = ts.run_command_impl(repo, 'python -c "import time; time.sleep(60)"', timeout_seconds=2)
    assert res["exit_code"] is None  # 超时无退出码
    assert "timeout" in res["stderr"].lower()
    assert res["duration_ms"] < 15000
    assert res["command"].startswith("python")


def test_timeout_parameter_validated(repo):
    for bad in (0, -1, 61, 100):
        with pytest.raises(ts.TerminalError):
            ts.run_command_impl(repo, "pytest -q", timeout_seconds=bad)


# ---------- exit code != 0 ----------

def test_nonzero_exit_code_returned(repo):
    res = ts.run_command_impl(repo, 'python -c "import sys; sys.exit(3)"')
    assert res["exit_code"] == 3
    assert isinstance(res["stdout"], str)
    assert isinstance(res["stderr"], str)


def test_nonzero_does_not_raise(repo):
    # 非零退出码是正常"结果"，不是异常
    res = ts.run_command_impl(repo, 'python -c "import sys; sys.exit(1)"')
    assert res["exit_code"] == 1


# ---------- 其它 ----------

def test_repository_root_default(monkeypatch):
    monkeypatch.delenv("TERMINAL_ROOT", raising=False)
    assert ts.repository_root() == Path(__file__).resolve().parents[2]


def test_error_to_dict():
    err = ts.TerminalError("boom")
    d = err.to_dict()
    assert d["error"] == "terminal_error"
    assert d["message"] == "boom"


# ---------- High 修复：凭据 env 不下发子进程 ----------

def test_sensitive_env_not_inherited(repo, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-123")
    monkeypatch.setenv("MYAPP_TOKEN", "tok-xyz")
    cmd = (
        'python -c "import os; '
        "print('OPENAI_API_KEY' in os.environ, 'MYAPP_TOKEN' in os.environ)\""
    )
    res = ts.run_command_impl(repo, cmd)
    assert res["exit_code"] == 0
    assert res["stdout"].strip() == "False False"  # 两个凭据都不出现在子进程 env


def test_sensitive_env_kept_when_override(repo, monkeypatch):
    monkeypatch.setenv("MYAPP_TOKEN", "tok-xyz")
    monkeypatch.setenv("MCP_EXEC_KEEP_ENV", "1")  # 运维显式放行
    cmd = 'python -c "import os; print(\'MYAPP_TOKEN\' in os.environ)"'
    res = ts.run_command_impl(repo, cmd)
    assert res["exit_code"] == 0
    assert res["stdout"].strip() == "True"
