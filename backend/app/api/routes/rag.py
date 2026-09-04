"""RAG 检索路由：POST /rag/search。"""

from fastapi import APIRouter

from app.schemas.rag import RagSearchRequest, RagSearchResponse
from rag.retriever import search_code

router = APIRouter(tags=["rag"])


@router.post(
    "/search",
    response_model=RagSearchResponse,
    summary="RAG 代码语义检索",
)
async def rag_search(payload: RagSearchRequest) -> RagSearchResponse:
    """基于 ChromaDB 向量索引执行代码检索。"""
    results = search_code(query=payload.query, top_k=payload.top_k)
    return RagSearchResponse(results=results)
