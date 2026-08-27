"use client";

import { Bot, Settings, Users } from "lucide-react";

interface TeamMember {
    id: string;
    role: string;
    name: string;
    status: "active" | "busy" | "idle";
}

/** Day1 假数据：软件工程团队成员。 */
const TEAM: TeamMember[] = [
    { id: "pm", role: "PM", name: "需求拆解", status: "active" },
    { id: "architect", role: "Architect", name: "架构设计", status: "active" },
    { id: "coder", role: "Coder", name: "代码实现", status: "busy" },
    { id: "qa", role: "QA", name: "测试验证", status: "idle" },
    { id: "reviewer", role: "Reviewer", name: "代码审查", status: "idle" },
];

const STATUS_DOT: Record<TeamMember["status"], string> = {
    active: "bg-emerald-500",
    busy: "bg-amber-500",
    idle: "bg-muted-foreground",
};

/** 侧边栏：软件工程团队成员列表（假数据）。 */
export function Sidebar() {
    return (
        <aside className="flex h-full w-56 shrink-0 flex-col border-r border-border bg-card">
            <div className="flex items-center gap-2 border-b border-border px-4 py-3">
                <Bot className="h-5 w-5 text-primary" />
                <span className="text-sm font-semibold">SE Team</span>
            </div>

            <div className="flex items-center gap-2 px-4 py-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                <Users className="h-3.5 w-3.5" />
                团队成员
            </div>

            <nav className="flex-1 space-y-1 px-2">
                {TEAM.map((m) => (
                    <button
                        key={m.id}
                        className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-muted"
                    >
                        <span
                            className={`h-2 w-2 shrink-0 rounded-full ${STATUS_DOT[m.status]}`}
                        />
                        <span className="font-medium">{m.role}</span>
                        <span className="ml-auto truncate text-xs text-muted-foreground">
                            {m.name}
                        </span>
                    </button>
                ))}
            </nav>

            <div className="border-t border-border p-2">
                <button className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted">
                    <Settings className="h-4 w-4" />
                    设置
                </button>
            </div>
        </aside>
    );
}
