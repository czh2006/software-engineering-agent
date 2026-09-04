"""RAG Embedder：为 CodeChunk 建立 ChromaDB 向量索引。

Collection : repository-code
Document   : code
Metadata   : symbol_name / file_path / language / line_range

本模块只实现 build_index(chunks)；Retriever 留待后续实现。
"""

from pathlib import Path

import chromadb
from chromadb import Collection

from rag.chunker import CodeChunk

COLLECTION_NAME: str = "repository-code"

# ChromaDB 持久化目录：backend/.chroma
CHROMA_DIR: Path = Path(__file__).resolve().parent.parent / ".chroma"


def _get_collection() -> Collection:
    """获取（或创建）目标 collection。"""
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client.get_or_create_collection(name=COLLECTION_NAME)


def build_index(chunks: list[CodeChunk]) -> int:
    """将 CodeChunk 写入 ChromaDB（upsert），建立向量索引。

    每个 chunk 的 code 作为 document 被自动 Embedding；
    symbol_name / file_path / language / line_range 作为 metadata 存储。

    Args:
        chunks: 待索引的 CodeChunk 列表。

    Returns:
        实际写入的 chunk 数量。
    """
    if not chunks:
        return 0

    collection = _get_collection()
    ids = [chunk.chunk_id for chunk in chunks]
    documents = [chunk.code for chunk in chunks]
    metadatas = [
        {
            "symbol_name": chunk.symbol_name,
            "file_path": chunk.file_path,
            "language": chunk.language,
            # Chroma metadata 仅接受标量，将元组转成 "start-end"
            "line_range": f"{chunk.metadata.line_range[0]}-{chunk.metadata.line_range[1]}",
        }
        for chunk in chunks
    ]

    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    return len(ids)


if __name__ == "__main__":
    import sys

    from rag.chunker import chunk_symbols
    from rag.loader import load_repository
    from rag.parser import parse_repository_files

    target = sys.argv[1] if len(sys.argv) > 1 else "."
    repo_files = load_repository(target)
    symbols = parse_repository_files(repo_files)
    chunks = chunk_symbols(symbols)

    count = build_index(chunks)
    collection = _get_collection()
    print(f"已索引 {count} 个 chunks -> collection '{COLLECTION_NAME}'")
    print(f"collection 现有条数: {collection.count()}")
