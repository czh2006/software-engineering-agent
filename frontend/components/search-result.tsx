"use client";

import { FileCode2 } from "lucide-react";
import type { RagSearchResult } from "@/lib/api";

/** 单条 RAG 检索结果展示：Symbol / File / Score / Code Preview。 */
export function SearchResult({ result }: { result: RagSearchResult }) {
    return (
        <article className="overflow-hidden rounded-md border border-border bg-muted/30">
            <div className="flex items-center gap-2 border-b border-border bg-card px-3 py-2">
                <span className="rounded bg-primary/10 px-1.5 py-0.5 font-mono text-xs font-medium text-primary">
                    {result.symbol_name}
                </span>
                <span className="flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
                    <FileCode2 className="h-3.5 w-3.5 shrink-0" />
                    <span className="truncate">
                        {result.file_path}:{result.line_range}
                    </span>
                </span>
                <span className="ml-auto shrink-0 rounded-full bg-emerald-500/10 px-2 py-0.5 font-mono text-xs text-emerald-600">
                    {(result.score * 100).toFixed(1)}%
                </span>
            </div>
            <pre className="max-h-40 overflow-auto p-3 font-mono text-xs leading-5 text-muted-foreground">
                {result.code}
            </pre>
        </article>
    );
}
