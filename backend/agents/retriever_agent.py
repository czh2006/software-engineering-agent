"""Retriever Agent：根据 TaskPlan 检索相关代码片段。

输入：TaskPlan（PM 的任务计划）。
输出：RetrievedChunks（去重、按相关性排序的代码片段列表）。

说明：
- 本模块**不实现向量搜索**，直接调用 backend/rag/retriever.py 的 search_code；
- 对 TaskPlan 中的每个任务构造检索查询并聚合结果；
- 每个 Chunk 字段：symbol_name / file_path / score / code。
"""

import sys

from pydantic import BaseModel, Field

from rag.retriever import search_code
from agents.pm_agent import TaskPlan


class RetrievedChunk(BaseModel):
    """检索到的一个相关代码片段。"""

    symbol_name: str = Field(description="符号名")
    file_path: str = Field(description="文件路径")
    score: float = Field(description="相似度分数（越大越相关）")
    code: str = Field(description="代码内容")


def retrieve_for_task_plan(
    task_plan: TaskPlan,
    top_k_per_task: int = 3,
    max_chunks: int = 10,
) -> list[RetrievedChunk]:
    """为 TaskPlan 检索相关代码。

    对计划中的每个任务（结合 goal）发起一次检索，
    合并所有结果，按 file_path + symbol_name 去重（保留最高分），
    最终按分数降序截取前 max_chunks 个。

    Args:
        task_plan: PM 的任务计划。
        top_k_per_task: 每个任务查询取回的数量。
        max_chunks: 最终返回的片段总数上限。

    Returns:
        去重排序后的 RetrievedChunk 列表。
    """
    # 关键：直接复用现有向量检索（不在此实现向量搜索）
    queries: list[str] = []
    if task_plan.goal:
        queries.append(task_plan.goal)
    queries.extend(
        f"{task.title} {task.description}".strip()
        for task in task_plan.tasks
        if task.title
    )

    best_by_key: dict[tuple[str, str], RetrievedChunk] = {}
    for query in queries:
        for result in search_code(query, top_k=top_k_per_task):
            key = (result.file_path, result.symbol_name)
            chunk = RetrievedChunk(
                symbol_name=result.symbol_name,
                file_path=result.file_path,
                score=result.score,
                code=result.code,
            )
            # 同 key 只保留分数更高的一条
            if key not in best_by_key or chunk.score > best_by_key[key].score:
                best_by_key[key] = chunk

    ranked = sorted(best_by_key.values(), key=lambda c: c.score, reverse=True)
    return ranked[:max_chunks]


if __name__ == "__main__":
    import json

    request = sys.argv[1] if len(sys.argv) > 1 else "Add Google OAuth login."

    if len(sys.argv) > 2:
        plan = TaskPlan.model_validate(json.loads(sys.argv[2]))
    else:
        from agents.pm_agent import generate_task_plan

        plan = generate_task_plan(request)
        print("PM TaskPlan 已生成\n")

    chunks = retrieve_for_task_plan(plan)
    print(f"检索到 {len(chunks)} 个去重片段：\n")
    for c in chunks:
        print(f"  [{c.score:.3f}] {c.symbol_name:<20} {c.file_path}")
