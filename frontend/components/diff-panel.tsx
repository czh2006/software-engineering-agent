"use client";

import { FileCode2 } from "lucide-react";

type DiffLineType = "add" | "del" | "ctx";

interface DiffLine {
    type: DiffLineType;
    text: string;
}

interface DiffFile {
    path: string;
    lines: DiffLine[];
}

/** Day1 假数据：代码变更（Git Patch）。 */
const DIFF_FILES: DiffFile[] = [
    {
        path: "src/auth/login.ts",
        lines: [
            { type: "ctx", text: "  export function handleLogin() {" },
            { type: "del", text: "-    const token = legacyToken();" },
            { type: "add", text: "+    const token = await signIn(credentials);" },
            { type: "add", text: "+    session.set(token);" },
            { type: "ctx", text: "  }" },
        ],
    },
    {
        path: "src/auth/session.ts",
        lines: [
            { type: "add", text: "+  export class Session {" },
            { type: "add", text: "+    constructor(private token: string) {}" },
            { type: "add", text: "+  }" },
            { type: "del", text: "-  // legacy session handling removed" },
        ],
    },
];

const LINE_CLASS: Record<DiffLineType, string> = {
    add: "bg-emerald-500/10 text-emerald-700",
    del: "bg-red-500/10 text-red-600 line-through",
    ctx: "text-muted-foreground",
};

const LINE_PREFIX: Record<DiffLineType, string> = {
    add: "+",
    del: "-",
    ctx: " ",
};

/** Diff 面板：代码变更展示（假数据）。 */
export function DiffPanel() {
    return (
        <section className="flex h-full flex-col rounded-lg border border-border bg-card">
            <header className="flex items-center gap-2 border-b border-border px-4 py-3">
                <FileCode2 className="h-4 w-4 text-primary" />
                <h2 className="text-sm font-semibold">代码变更</h2>
                <span className="ml-auto rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                    2 files changed
                </span>
            </header>
            <div className="flex-1 space-y-3 overflow-y-auto p-4">
                {DIFF_FILES.map((file) => (
                    <div
                        key={file.path}
                        className="overflow-hidden rounded-md border border-border"
                    >
                        <div className="border-b border-border bg-muted/50 px-3 py-1.5 font-mono text-xs">
                            {file.path}
                        </div>
                        <pre className="overflow-x-auto p-2 font-mono text-xs leading-5">
                            {file.lines.map((line, i) => (
                                <div
                                    key={i}
                                    className={`whitespace-pre ${LINE_CLASS[line.type]}`}
                                >
                                    {LINE_PREFIX[line.type]}
                                    {line.text}
                                </div>
                            ))}
                        </pre>
                    </div>
                ))}
            </div>
        </section>
    );
}
