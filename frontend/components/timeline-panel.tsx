"use client";

import { CheckCircle2, Clock, Loader2, PlayCircle } from "lucide-react";

type StageStatus = "done" | "running" | "pending";

interface TimelineItem {
    stage: string;
    agent: string;
    status: StageStatus;
}

/** Day1 假数据：任务阶段时间线。 */
const TIMELINE: TimelineItem[] = [
    { stage: "需求分析", agent: "PM", status: "done" },
    { stage: "架构设计", agent: "Architect", status: "done" },
    { stage: "代码实现", agent: "Coder", status: "running" },
    { stage: "测试验证", agent: "QA", status: "pending" },
    { stage: "代码审查", agent: "Reviewer", status: "pending" },
];

const STATUS_ICON: Record<StageStatus, typeof CheckCircle2> = {
    done: CheckCircle2,
    running: Loader2,
    pending: Clock,
};

const STATUS_CLASS: Record<StageStatus, string> = {
    done: "text-emerald-600",
    running: "text-primary animate-spin",
    pending: "text-muted-foreground",
};

/** 时间线面板：任务执行阶段（假数据）。 */
export function TimelinePanel() {
    return (
        <section className="flex h-full flex-col rounded-lg border border-border bg-card">
            <header className="flex items-center gap-2 border-b border-border px-4 py-3">
                <PlayCircle className="h-4 w-4 text-primary" />
                <h2 className="text-sm font-semibold">任务时间线</h2>
            </header>
            <ol className="flex-1 space-y-0 overflow-y-auto p-4">
                {TIMELINE.map((item, i) => {
                    const Icon = STATUS_ICON[item.status];
                    const isLast = i === TIMELINE.length - 1;
                    return (
                        <li key={item.stage} className="relative flex gap-3 pb-4">
                            {!isLast && (
                                <span className="absolute left-[7px] top-4 h-full w-px bg-border" />
                            )}
                            <span className="relative z-10 flex h-4 w-4 items-center justify-center rounded-full bg-background">
                                <Icon className={`h-4 w-4 ${STATUS_CLASS[item.status]}`} />
                            </span>
                            <div className="pt-0.5">
                                <p className="text-sm font-medium">{item.stage}</p>
                                <p className="text-xs text-muted-foreground">
                                    负责人：{item.agent}
                                </p>
                            </div>
                        </li>
                    );
                })}
            </ol>
        </section>
    );
}
