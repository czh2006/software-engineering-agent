"""RAG 代码分块器：将 Symbol 转换为 CodeChunk。

输入：Symbol（见 rag.parser.Symbol）。
输出：CodeChunk 列表。

CodeChunk 字段：
- chunk_id / symbol_name / file_path / code / language
- metadata: { line_range, symbol_type, imports }

约束：不做 Embedding、不写数据库、不依赖 LangChain。
"""

import hashlib
import re
from pathlib import Path

from pydantic import BaseModel, Field

from rag.parser import Symbol

# 文件扩展名 → 语言（Symbol 无 language 字段，按路径推断）
_EXTENSION_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
}

# 轻量 import 行识别（仅用于 metadata 辅助信息，符号定位仍由 Tree-sitter 完成）
_IMPORT_LINE_RE = re.compile(r"^\s*(?:from\s+[\w.]+|import)\s+(.+)$")


class ChunkMetadata(BaseModel):
    """CodeChunk 的元数据。"""

    line_range: tuple[int, int] = Field(description="行范围（start, end）")
    symbol_type: str = Field(description="符号类型：function / class / import")
    imports: list[str] | None = Field(default=None, description="相关 import 的符号名")


class CodeChunk(BaseModel):
    """分块后的代码单元（供后续 RAG 使用）。"""

    chunk_id: str = Field(description="稳定分块 ID")
    symbol_name: str = Field(description="符号名称")
    file_path: str = Field(description="文件路径")
    code: str = Field(description="代码内容")
    language: str = Field(description="代码语言")
    metadata: ChunkMetadata = Field(description="元数据")


def _language_from_path(file_path: str) -> str:
    """根据文件扩展名推断语言。"""
    extension = Path(file_path).suffix.lower()
    return _EXTENSION_LANGUAGE.get(extension, "unknown")


def _extract_imports(source_code: str) -> list[str]:
    """从源码中提取 import 的符号名（用于 metadata）。"""
    imports: list[str] = []
    for line in source_code.splitlines():
        match = _IMPORT_LINE_RE.match(line)
        if match is None:
            continue
        rest = match.group(1)
        # 去掉字符串字面量（模块路径等）
        rest = re.sub(r'"[^"]*"|\'[^\']*\'', "", rest)
        for part in rest.split(","):
            part = part.strip()
            identifiers = [
                item
                for item in re.findall(r"[A-Za-z_]\w*", part)
                if item not in ("import", "from", "as")
            ]
            if identifiers:
                imports.append(identifiers[-1])
    return imports


def chunk_symbol(symbol: Symbol) -> CodeChunk:
    """将单个 Symbol 转换为 CodeChunk。"""
    source_code: str = symbol.source_code or ""
    imports = _extract_imports(source_code)

    # 稳定且可复现的 chunk_id（内容 + 位置哈希）
    chunk_id = hashlib.sha1(
        f"{symbol.file_path}:{symbol.start_line}:{symbol.name}".encode("utf-8")
    ).hexdigest()[:12]

    return CodeChunk(
        chunk_id=chunk_id,
        symbol_name=symbol.name,
        file_path=symbol.file_path,
        code=source_code,
        language=_language_from_path(symbol.file_path),
        metadata=ChunkMetadata(
            line_range=(symbol.start_line, symbol.end_line),
            symbol_type=symbol.type,
            imports=imports or None,
        ),
    )


def chunk_symbols(symbols: list[Symbol]) -> list[CodeChunk]:
    """批量将 Symbol 列表转换为 CodeChunk 列表。"""
    return [chunk_symbol(symbol) for symbol in symbols]


if __name__ == "__main__":
    import json
    import sys

    from rag.loader import load_repository
    from rag.parser import parse_repository_files

    target = sys.argv[1] if len(sys.argv) > 1 else "."
    repo_files = load_repository(target)
    symbols = parse_repository_files(repo_files)
    chunks = chunk_symbols(symbols)
    print(f"{len(symbols)} symbols -> {len(chunks)} chunks")
    print(json.dumps([c.model_dump() for c in chunks[:3]], ensure_ascii=False, indent=2))
