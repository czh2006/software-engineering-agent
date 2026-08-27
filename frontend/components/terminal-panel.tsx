"use client";

import { SquareTerminal } from "lucide-react";

interface LogLine {
    text: string;
    tone: "cmd" | "ok" | "info" | "err";
}

/** Day1 假数据：终端日志。 */
const LOGS: LogLine[] = [
    { tone: "cmd", text: "$ sea team run --task \"登录功能\"" },
    { tone: "info", text: "→ 正在分析代码仓库..." },
    { tone: "ok", text: "✓ 依赖解析完成" },
    { tone: "info", text: "→ 正在生成 Git Patch..." },
    { tone: "ok", text: "✓ 运行 12 个测试，全部通过" },
    { tone: "err", text: "✗ 审查建议：session 过期需增加刷新逻辑" },
    { tone: "cmd", text: "$ " },
];

const TONE_CLASS: Record<LogLine["tone"], string> = {
    cmd: "text-foreground",
    ok: "text-emerald-600",
    info: "text-muted-foreground",
    err: "text-red-500",
};

/** 终端面板：命令执行日志（假数据）。 */
export function TerminalPanel() {
    return (
        <section className="flex h-full flex-col rounded-lg border border-border bg-black/90">
            <header className="flex items-center gap-2 border-b border-white/10 px-4 py-3">
                <SquareTerminal className="h-4 w-4 text-primary" />
                <h2 className="text-sm font-semibold text-white">终端</h2>
                <div className="ml-auto flex gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-full bg-red-500/80" />
                    <span className="h-2.5 w-2.5 rounded-full bg-amber-500/80" />
                    <span className="h-2.5 w-2.5 rounded-full bg-emerald-500/80" />
                </div>
            </header>
            <div className="flex-1 overflow-y-auto p-4 font-mono text-xs leading-6">
                {LOGS.map((log, i) => (
                    <p key={i} className={TONE_CLASS[log.tone]}>
                        {log.text}
                    </p>
                ))}
            </div>
        </section>
    );
}
