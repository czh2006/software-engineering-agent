"""filesystem MCP Server 的 pytest 测试。

覆盖：三个只读工具 + 安全要求（越界 / 敏感文件 / 大小 / 深度）。
"""

from pathlib import Path

import pytest

from mcp_servers import filesystem_server as fs


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """构造带安全陷阱的测试仓库，并把 FILESYSTEM_ROOT 指到它。"""
    (tmp_path / "a.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.ts").write_text("let x = 1;\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (tmp_path / "secret.pem").write_text("PRIVATE\n", encoding="utf-8")
    # root 之外的越界目标
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")

    # 深目录（超过 MAX_DEPTH=5，deep.py 不应被列出）
    d = tmp_path
    for i in range(1, 7):
        d = d / f"d{i}"
    d.mkdir(parents=True)
    (d / "deep.py").write_text("x = 1\n", encoding="utf-8")

    # 超大文件（>1MB）
    (tmp_path / "big.txt").write_bytes(b"x" * (fs.MAX_FILE_SIZE_BYTES + 1))

    monkeypatch.setenv("FILESYSTEM_ROOT", str(tmp_path))
    return tmp_path


# ---------- list_files ----------

def test_list_files_returns_files(repo):
    result = fs.list_files(".")
    files = set(result["files"])
    assert "a.py" in files
    assert "sub/b.ts" in files


def test_list_files_excludes_sensitive_and_deep(repo):
    files = set(fs.list_files(".")["files"])
    assert ".env" not in files
    assert "secret.pem" not in files
    assert not any(f.endswith("deep.py") for f in files)  # 深度 > 5


def test_list_files_path_traversal_rejected(repo):
    with pytest.raises(ValueError):
        fs.list_files("../../")


def test_list_files_subdir(repo):
    files = set(fs.list_files("sub")["files"])
    assert files == {"sub/b.ts"}


# ---------- read_file ----------

def test_read_file_content(repo):
    data = fs.read_file("a.py")
    assert data["content"] == "print(1)\n"
    assert data["path"].endswith("a.py")


def test_read_file_rejects_env(repo):
    with pytest.raises(ValueError):
        fs.read_file(".env")


def test_read_file_rejects_private_key(repo):
    with pytest.raises(ValueError):
        fs.read_file("secret.pem")


def test_read_file_rejects_traversal(repo):
    with pytest.raises(ValueError):
        fs.read_file("../outside.txt")


def test_read_file_rejects_outside_absolute(repo):
    outside = repo.parent / "outside.txt"
    with pytest.raises(ValueError):
        fs.read_file(str(outside))


def test_read_file_rejects_too_large(repo):
    with pytest.raises(ValueError):
        fs.read_file("big.txt")


def test_read_file_subdir(repo):
    data = fs.read_file("sub/b.ts")
    assert "let x = 1;" in data["content"]


# ---------- search_files ----------

def test_search_files_by_name(repo):
    result = fs.search_files("b", ".")
    assert "sub/b.ts" in result["matching_files"]


def test_search_files_case_insensitive(repo):
    result = fs.search_files("A", ".")
    assert "a.py" in result["matching_files"]


def test_search_files_empty_query_rejected(repo):
    with pytest.raises(ValueError):
        fs.search_files("", ".")


def test_search_files_ignores_sensitive(repo):
    result = fs.search_files("env", ".")["matching_files"]
    assert all(not f.startswith(".env") for f in result)


# ---------- 直接测 impl（显式 root） ----------

def test_impl_explicit_root(repo):
    assert fs.list_files_impl(repo, ".") == ["a.py", "big.txt", "sub/b.ts"]


def test_impl_forbidden_ssh_dir(repo):
    ssh = repo / ".ssh"
    ssh.mkdir()
    (ssh / "id_rsa").write_text("KEY\n", encoding="utf-8")
    with pytest.raises(ValueError):
        fs.read_file_impl(repo, ".ssh/id_rsa")
