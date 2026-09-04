"""RAG Retriever：基于 ChromaDB 的语义代码检索。

实现 search_code(query, top_k, language=None)。
输入：query / top_k / 可选 metadata 过滤（language）。
输出：SearchResult[]（file_path / symbol_name / score / code / line_range）。
"""

from pydantic import BaseModel, Field

from rag.embedder import _get_collection


class SearchResult(BaseModel):
    """代码检索结果。"""

    file_path: str = Field(description="文件路径")
    symbol_name: str = Field(description="符号名称")
    score: float = Field(description="相似度分数（0~1，越大越相关）")
    code: str = Field(description="匹配到的代码")
    line_range: str = Field(description="行范围（start-end）")


def search_code(
    query: str,
    top_k: int = 5,
    language: str | None = None,
) -> list[SearchResult]:
    """在 ChromaDB collection 中检索与 query 最相关的代码片段。

    Args:
        query: 自然语言 / 代码描述查询。
        top_k: 返回结果数量上限。
        language: 可选 metadata 过滤，如 "python" / "typescript"。

    Returns:
        按相关性排序的 SearchResult 列表。
    """
    collection = _get_collection()
    where = {"language": language} if language else None

    result = collection.query(
        query_texts=[query],
        n_results=max(1, top_k),
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    documents = (result.get("documents") or [[]])[0] or []
    metadatas = (result.get("metadatas") or [[]])[0] or []
    distances = (result.get("distances") or [[]])[0] or []

    hits: list[SearchResult] = []
    for document, metadata, distance in zip(documents, metadatas, distances):
        # Chroma 返回 distance（越小越近）；转换为相似度 score（0~1）
        score = round(1.0 / (1.0 + distance), 4) if distance is not None else 0.0
        metadata = metadata or {}
        hits.append(
            SearchResult(
                file_path=str(metadata.get("file_path", "")),
                symbol_name=str(metadata.get("symbol_name", "")),
                score=score,
                code=document or "",
                line_range=str(metadata.get("line_range", "")),
            )
        )

    return hits


if __name__ == "__main__":
    import sys

    query = sys.argv[1] if len(sys.argv) > 1 else "加载并解析项目代码文件"
    top_k = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    language = sys.argv[3] if len(sys.argv) > 3 else None

    results = search_code(query, top_k=top_k, language=language)
    print(f"query='{query}' top_k={top_k} language={language} -> {len(results)} 条")
    for r in results:
        print(f"  [{r.score:.3f}] {r.symbol_name:<22} {r.file_path}:{r.line_range}")
