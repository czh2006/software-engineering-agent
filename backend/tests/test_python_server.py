"""python MCP Server 的 pytest 测试。

覆盖：
- 正常执行（stdout / stderr / exit_code=0）
- 非零退出码 / 异常退出（结构化返回，不抛错）
- 超时（exit_code=None，stderr 带 [timeout]）
- 安全：只 .py / 越界穿越 / 越界绝对路径 / 目录 / 不存在 / timeout 上限
- 仅运行文件（无 eval/exec/代码字符串路径）
"""

from pathlib import Path

import pytest

from mcp_servers import python_server as ps


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """构造带若干 .py 样本的临时 repository root。"""
    (tmp_path / "hello.py").write_text(
        "print('hello-from-python')\nprint('你好 world')\n", encoding="utf-8"
    )
    (tmp_path / "stderr.py").write_text(
        "import sys\nprint('boom-msg', file=sys.stderr)\n", encoding="utf-8"
    )
    (tmp_path / "exit2.py").write_text(
        "import sys\nsys.exit(2)\n", encoding="utf-8"
    )
    (tmp_path / "raise1.py").write_text(
        "raise RuntimeError('kaboom')\n", encoding="utf-8"
    )
    (tmp_path / "slow.py").write_text(
        "import time\ntime.sleep(60)\n", encoding="utf-8"
    )
    (tmp_path / "not_code.txt").write_text(
        "print('should not run')\n", encoding="utf-8"
    )
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "inner.py").write_text("print('inner')\n", encoding="utf-8")
    # root 之外的越界文件
    outside = tmp_path.parent / "outside.py"
    outside.write_text("print('outside')\n", encoding="utf-8")

    monkeypatch.setenv("PYTHON_ROOT", str(tmp_path))
    return tmp_path


# ---------- 正常执行 ----------

def test_run_python_file_ok(repo):
    res = ps.run_python_file("hello.py")  # 工具层（读 PYTHON_ROOT env）
    assert res["exit_code"] == 0
    assert "hello-from-python" in res["stdout"]
    assert "你好 world" in res["stdout"]  # utf-8 解码正常
    assert res["path"].endswith("hello.py")
    assert res["duration_ms"] >= 0


def test_run_impl_explicit_root(repo, monkeypatch):
    monkeypatch.delenv("PYTHON_ROOT", raising=False)
    res = ps.run_python_file_impl(repo, "sub/inner.py")
    assert res["exit_code"] == 0
    assert "inner" in res["stdout"]


def test_stdout_and_stderr_captured(repo):
    res = ps.run_python_file_impl(repo, "stderr.py")
    assert res["exit_code"] == 0
    assert "boom-msg" in res["stderr"]
    assert isinstance(res["stdout"], str)


# ---------- 非零退出码（结构化结果） ----------

def test_nonzero_exit_code_returned(repo):
    res = ps.run_python_file_impl(repo, "exit2.py")
    assert res["exit_code"] == 2


def test_raised_exception_returns_exit_1(repo):
    res = ps.run_python_file_impl(repo, "raise1.py")
    assert res["exit_code"] == 1
    assert "RuntimeError" in res["stderr"]


# ---------- 超时 ----------

def test_timeout_returns_structured_result(repo):
    res = ps.run_python_file_impl(repo, "slow.py", timeout_seconds=2)
    assert res["exit_code"] is None
    assert "timeout" in res["stderr"].lower()
    assert res["duration_ms"] < 15000


def test_timeout_upper_bound_enforced(repo):
    with pytest.raises(ValueError):
        ps.run_python_file_impl(repo, "hello.py", timeout_seconds=31)
    with pytest.raises(ValueError):
        ps.run_python_file_impl(repo, "hello.py", timeout_seconds=0)


# ---------- 安全：路径 / 扩展名 ----------

def test_non_py_rejected(repo):
    with pytest.raises(ValueError, match=".py"):
        ps.run_python_file_impl(repo, "not_code.txt")


def test_missing_file_rejected(repo):
    with pytest.raises(ValueError):
        ps.run_python_file_impl(repo, "nope.py")


def test_directory_rejected(repo):
    with pytest.raises(ValueError):
        ps.run_python_file_impl(repo, "sub")


def test_traversal_rejected(repo):
    with pytest.raises(ValueError, match="越界"):
        ps.run_python_file_impl(repo, "../outside.py")


def test_outside_absolute_rejected(repo):
    outside = repo.parent / "outside.py"
    with pytest.raises(ValueError):
        ps.run_python_file_impl(repo, str(outside))


def test_empty_path_rejected(repo):
    with pytest.raises(ValueError):
        ps.run_python_file_impl(repo, "")


# ---------- 其它 ----------

def test_repository_root_default(monkeypatch):
    monkeypatch.delenv("PYTHON_ROOT", raising=False)
    assert ps.repository_root() == Path(__file__).resolve().parents[2]


def test_no_string_code_execution_api(repo):
    # run_python_file 只接受文件路径：-c / 代码字符串都不是 .py 文件 → 拒绝
    for bad in ("-c print(1)", "print(1)", "hello.py; rm -rf /"):
        with pytest.raises(ValueError):
            ps.run_python_file_impl(repo, bad)


# ---------- High 修复：凭据 env 不下发子进程 ----------

def test_sensitive_env_not_inherited(repo, monkeypatch):
    (repo / "envprobe.py").write_text(
        "import os\nprint('OPENAI_API_KEY' in os.environ, 'MYAPP_TOKEN' in os.environ)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-123")
    monkeypatch.setenv("MYAPP_TOKEN", "tok-xyz")
    res = ps.run_python_file_impl(repo, "envprobe.py")
    assert res["exit_code"] == 0
    assert res["stdout"].strip() == "False False"  # 凭据不出现在子进程 env
