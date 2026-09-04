"use client";

import { useQuery } from "@tanstack/react-query";
import { searchCode, type RagSearchResult } from "@/lib/api";

/**
 * 基于 TanStack Query 的代码语义搜索 hook。
 *
 * 请求：POST /rag/search（见 lib/api.ts 的 searchCode）。
 * 特性：
 * - Loading：isPending（首次）/ isFetching（重取/重试中）
 * - Error：  isError + error（可用 refetch 手动重试）
 * - Retry：  失败自动重试 3 次（指数退避），enabled=false 时不发请求
 */
export function useCodeSearch(query: string, topK = 5) {
    const trimmed = query.trim();

    return useQuery<RagSearchResult[]>({
        queryKey: ["codeSearch", trimmed, topK],
        queryFn: () => searchCode(trimmed, topK),
        // 仅在用户实际提交查询后才发起请求
        enabled: trimmed.length > 0,
        // 自动重试：最多 3 次，指数退避（1s, 2s, 4s，上限 10s）
        retry: 3,
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10_000),
        // 1 分钟内相同查询复用缓存，避免重复请求
        staleTime: 60 * 1000,
    });
}
