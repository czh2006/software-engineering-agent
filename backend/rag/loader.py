"""RAG 仓库加载器：加载本地项目中的源码/文档文件内容。

输入：project_path 本地项目根目录路径。
输出：RepositoryFile 列表（path / extension / content / language）。
支持语言：Python、TypeScript、JavaScript、Markdown。
过滤目录：node_modules、.git、dist、build、.venv、__pycache__。

实现约束：
- 使用 pathlib 遍历
- 不读取超过 1MB 的文件（超大文件直接跳过）
- 完整类型注解
- 不依赖 LangChain
"""

import json
import sys
from pathlib import Path
from typing import Iterator, Literal

from pydantic import BaseModel, Field

Language = Literal["python", "typescript", "javascript", "markdown"]

# 支持的语言 → 扩展名映射
SUPPORTED_LANGUAGES: dict[Language, tuple[str, ...]] = {
    "python": (".py",),
    "typescript": (".ts", ".tsx"),
    "javascript": (".js", ".jsx", ".mjs", ".cjs"),
    "markdown": (".md", ".mdx"),
}

# 遍历时需要跳过的目录名
# 除指定项外，补充 .next（Next.js 构建产物，与 dist/build 同类），避免污染 RAG 内容
IGNORED_DIRS: frozenset[str] = frozenset(
    {"node_modules", ".git", "dist", "build", ".venv", "__pycache__", ".next"}
)

# 单文件大小上限：1MB
MAX_FILE_SIZE_BYTES: int = 1024 * 1024


class RepositoryFile(BaseModel):
    """仓库中的单个源码/文档文件。"""

    path: str = Field(description="相对项目根目录的路径（POSIX 风格）")
    extension: str = Field(description="文件扩展名（含点，如 .py）")
    content: str = Field(description="文件文本内容")
    language: Language = Field(description="文件语言")


def _classify_language(path: Path) -> Language | None:
    """根据扩展名判断语言；不支持的扩展名返回 None。"""
    extension = path.suffix.lower()
    for language, extensions in SUPPORTED_LANGUAGES.items():
        if extension in extensions:
            return language
    return None


def _iter_files(root: Path) -> Iterator[Path]:
    """递归遍历目录（pathlib 实现），跳过被忽略的目录。"""
    for entry in root.iterdir():
        if entry.is_dir():
            if entry.name in IGNORED_DIRS:
                continue
            yield from _iter_files(entry)
        elif entry.is_file():
            yield entry


def load_repository(project_path: str) -> list[RepositoryFile]:
    """加载本地项目，返回支持的源码/文档文件及其内容。

    Args:
        project_path: 本地项目根目录路径。

    Returns:
        RepositoryFile 列表；被忽略目录、不支持的语言、
        超过 1MB 的文件、读取失败的文件均会被跳过。

    Raises:
        NotADirectoryError: 当 project_path 不存在或不是目录时。
    """
    root = Path(project_path).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"路径不是目录：{root}")

    files: list[RepositoryFile] = []
    for file_path in _iter_files(root):
        # 1. 语言识别（不支持则跳过）
        language = _classify_language(file_path)
        if language is None:
            continue

        # 2. 大小过滤：不读取超过 1MB 的文件
        if file_path.stat().st_size > MAX_FILE_SIZE_BYTES:
            continue

        # 3. 读取内容（UTF-8 容错，二进制/编码异常不中断）
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        files.append(
            RepositoryFile(
                path=file_path.relative_to(root).as_posix(),
                extension=file_path.suffix.lower(),
                content=content,
                language=language,
            )
        )

    return files


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    result = load_repository(target)
    print(f"共加载 {len(result)} 个文件")
    print(json.dumps([f.model_dump() for f in result], ensure_ascii=False, indent=2))
