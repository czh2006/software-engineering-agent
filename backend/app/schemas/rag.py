"""RAG 检索接口的 Pydantic 模型。"""

from pydantic import BaseModel, Field

from rag.retriever import SearchResult


class RagSearchRequest(BaseModel):
    """RAG 代码检索请求。"""

    query: str = Field(
        description="检索查询（自然语言或代码描述）",
        min_length=1,
        examples=["加载并解析项目中的代码文件"],
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=50,
        description="返回结果数量上限",
        examples=[5],
    )


class RagSearchResponse(BaseModel):
    """RAG 代码检索响应。"""

    results: list[SearchResult] = Field(description="按相关性排序的检索结果")
