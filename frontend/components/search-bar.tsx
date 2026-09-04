"use client";

import { useState } from "react";
import { AlertTriangle, Loader2, RefreshCw, Search, SearchX } from "lucide-react";
import { SearchResult } from "@/components/search-result";
import { useCodeSearch } from "@/hooks/useCodeSearch";

/** 代码搜索工作区：输入 Query → Search → 展示结果（TanStack Query 管理状态）。 */
export function SearchBar() {
    const [input, setInput] = useState("");
    const [query, setQuery] = useState("");

    // Loading / Error / Retry 均由 useCodeSearch 管理
    const { data, isPending, isFetching, isError, error, refetch } =
        useCodeSearch(query);

    const hasQuery = query.trim().length > 0;
    const isSearching = hasQuery && (isPending || isFetching);

    function handleSearch() {
        const q = input.trim();
        if (!q || isFetching) return;
        setQuery(q);
    }

    return (
        <section className="flex h-full flex-col rounded-lg border border-border bg-card">
            <div className="flex items-center gap-2 border-b border-border p-3">
                <div className="flex flex-1 items-center gap-2 rounded-md border border-input bg-background px-3 transition-colors focus-within:ring-2 focus-within:ring-ring">
                    <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <input
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === "Enter") {
                                handleSearch();
                            }
                        }}
                        placeholder="搜索代码语义，如：加载并解析项目代码文件"
                        className="h-9 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                    />
                </div>
                <button
                    onClick={handleSearch}
                    disabled={!input.trim() || isFetching}
                    className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
                >
                    {isFetching ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                        <Search className="h-4 w-4" />
                    )}
                    Search
                </button>
            </div>

            <div className="flex-1 space-y-2 overflow-y-auto p-3">
                {/* 尚未搜索 */}
                {!hasQuery && (
                    <p className="px-1 text-sm text-muted-foreground">
                        输入 Query 并按 Search / Enter 开始代码检索
                    </p>
                )}

                {/* Loading */}
                {isSearching && (
                    <p className="flex items-center gap-2 px-1 text-sm text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        正在检索代码…（失败将自动重试）
                    </p>
                )}

                {/* Error：显示错误 + 手动重试 */}
                {hasQuery && !isPending && !isFetching && isError && (
                    <div className="flex items-center justify-between rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2">
                        <p className="flex items-center gap-2 text-sm text-red-600">
                            <AlertTriangle className="h-4 w-4" />
                            搜索失败：{error instanceof Error ? error.message : String(error)}
                        </p>
                        <button
                            onClick={() => void refetch()}
                            className="inline-flex shrink-0 items-center gap-1 rounded-md bg-red-600/10 px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-600/20"
                        >
                            <RefreshCw className="h-3.5 w-3.5" />
                            重试
                        </button>
                    </div>
                )}

                {/* 空结果 */}
                {hasQuery && !isPending && !isFetching && !isError && data && data.length === 0 && (
                    <p className="flex items-center gap-2 px-1 text-sm text-muted-foreground">
                        <SearchX className="h-4 w-4" />
                        未找到相关代码
                    </p>
                )}

                {/* 结果列表 */}
                {data?.map((r) => (
                    <SearchResult
                        key={`${r.file_path}:${r.symbol_name}:${r.line_range}`}
                        result={r}
                    />
                ))}
            </div>
        </section>
    );
}
