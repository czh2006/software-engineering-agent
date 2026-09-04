"""RAG 代码解析器：使用 Tree-sitter 解析 RepositoryFile，提取代码符号。

输入：RepositoryFile（见 rag.loader.RepositoryFile）。
输出：Symbol 列表（name / type / start_line / end_line / file_path / source_code）。
支持语言：Python、TypeScript（含 TSX）。

约束：
- 不做 Embedding
- 不写数据库
- 只返回 Symbol 列表
- 不依赖 LangChain（使用 Tree-sitter 官方绑定）
"""

import tree_sitter_python
import tree_sitter_typescript
from pydantic import BaseModel, Field
from tree_sitter import Language, Node, Parser

from rag.loader import RepositoryFile

# ---------- 语言对象（进程内单例） ----------
_PY_LANGUAGE: Language = Language(tree_sitter_python.language())
_TS_LANGUAGE: Language = Language(tree_sitter_typescript.language_typescript())

# ---------- 语法节点类型 → Symbol.type ----------
_FUNCTION_NODES: frozenset[str] = frozenset(
    {
        "function_definition",  # Python
        "function_declaration",  # TS
        "method_definition",  # TS class method
        "arrow_function",  # TS 箭头函数
        "generator_function_declaration",  # TS function*
    }
)
_CLASS_NODES: frozenset[str] = frozenset(
    {
        "class_definition",  # Python
        "class_declaration",  # TS
    }
)
_IMPORT_NODES: frozenset[str] = frozenset(
    {
        "import_statement",  # Python / TS
        "import_from_statement",  # Python from ... import ...
    }
)


class Symbol(BaseModel):
    """解析出的代码符号。"""

    name: str = Field(description="符号名称")
    type: str = Field(description="符号类型：function / class / import")
    start_line: int = Field(description="起始行号（1-based）")
    end_line: int = Field(description="结束行号（1-based）")
    file_path: str = Field(description="所属文件路径")
    source_code: str = Field(description="符号对应的源码")


def _node_text(node: Node, source: bytes) -> str:
    """取节点对应的原始源码文本。"""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _extract_identifier_recursive(node: Node, source: bytes) -> str | None:
    """递归查找子树中第一个 identifier 文本。"""
    if node.type == "identifier":
        return _node_text(node, source)
    for child in node.named_children:
        result = _extract_identifier_recursive(child, source)
        if result is not None:
            return result
    return None


def _extract_name(node: Node, source: bytes) -> str | None:
    """按节点类型提取符号名称。"""
    # 1. 优先取 'name' 字段（函数/类的名称）
    name_child = node.child_by_field_name("name")
    if name_child is not None and name_child.type == "identifier":
        return _node_text(name_child, source)
    # 2. 兜底：取第一个 identifier（如 import 的目标名）
    return _extract_identifier_recursive(node, source)


def _walk(
    node: Node,
    source: bytes,
    file_path: str,
    symbols: list[Symbol],
) -> None:
    """深度优先遍历 AST，收集符号。"""
    node_type: str = node.type

    if node_type in _FUNCTION_NODES:
        name = _extract_name(node, source)
        if name is not None:
            symbols.append(
                Symbol(
                    name=name,
                    type="function",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    file_path=file_path,
                    source_code=_node_text(node, source),
                )
            )
    elif node_type in _CLASS_NODES:
        name = _extract_name(node, source)
        if name is not None:
            symbols.append(
                Symbol(
                    name=name,
                    type="class",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    file_path=file_path,
                    source_code=_node_text(node, source),
                )
            )
    elif node_type in _IMPORT_NODES:
        name = _extract_name(node, source)
        if name is not None:
            symbols.append(
                Symbol(
                    name=name,
                    type="import",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    file_path=file_path,
                    source_code=_node_text(node, source),
                )
            )

    # 继续深入（类里可能有方法，函数里可能有嵌套函数）
    for child in node.named_children:
        _walk(child, source, file_path, symbols)


def parse_repository_files(files: list[RepositoryFile]) -> list[Symbol]:
    """解析一组仓库文件，返回所有符号（不 Embedding、不落库）。"""
    symbols: list[Symbol] = []
    for repo_file in files:
        if repo_file.language == "python":
            language = _PY_LANGUAGE
        elif repo_file.language == "typescript":
            language = _TS_LANGUAGE
        else:
            # 仅支持 Python / TypeScript
            continue

        source: bytes = repo_file.content.encode("utf-8")
        try:
            parser = Parser(language)
            tree = parser.parse(source)
        except Exception:
            # 单个文件解析失败不中断整体
            continue

        _walk(tree.root_node, source, repo_file.path, symbols)

    return symbols


if __name__ == "__main__":
    import json
    import sys

    from rag.loader import load_repository

    target = sys.argv[1] if len(sys.argv) > 1 else "."
    repo_files = load_repository(target)
    symbols = parse_repository_files(repo_files)
    print(f"解析 {len(repo_files)} 个文件，提取 {len(symbols)} 个符号")
    print(
        json.dumps(
            [s.model_dump() for s in symbols],
            ensure_ascii=False,
            indent=2,
        )
    )
