"use client";

import { useState } from "react";
import { Loader2, MessageSquare, SendHorizonal } from "lucide-react";
import { sendChat, type ChatMessage } from "@/lib/api";

const INITIAL_MESSAGES: ChatMessage[] = [
    {
        role: "assistant",
        content:
            "你好！我是软件工程团队。请描述你的需求，例如「为项目添加用户登录功能」。",
    },
];

/** 聊天面板：用户输入需求并展示团队回复（Day1 Mock）。 */
export function ChatPanel() {
    const [messages, setMessages] = useState<ChatMessage[]>(INITIAL_MESSAGES);
    const [input, setInput] = useState("");
    const [sending, setSending] = useState(false);

    async function handleSend() {
        const text = input.trim();
        if (!text || sending) return;
        setMessages((prev) => [...prev, { role: "user", content: text }]);
        setInput("");
        setSending(true);
        try {
            const res = await sendChat(text);
            setMessages((prev) => [
                ...prev,
                { role: "assistant", content: res.message },
            ]);
        } catch {
            // 后端未连接时的兜底 Mock 回复
            setMessages((prev) => [
                ...prev,
                {
                    role: "assistant",
                    content:
                        "（后端未连接，Mock）已收到需求，团队开始分析，结果将稍后返回。",
                },
            ]);
        } finally {
            setSending(false);
        }
    }

    return (
        <section className="flex h-full flex-col rounded-lg border border-border bg-card">
            <header className="flex items-center gap-2 border-b border-border px-4 py-3">
                <MessageSquare className="h-4 w-4 text-primary" />
                <h2 className="text-sm font-semibold">需求对话</h2>
                <span className="ml-auto rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                    5 名成员在线
                </span>
            </header>

            <div className="flex-1 space-y-4 overflow-y-auto p-4">
                {messages.map((msg, i) => (
                    <div
                        key={i}
                        className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                    >
                        <div
                            className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${msg.role === "user"
                                    ? "bg-primary text-primary-foreground"
                                    : "bg-muted text-foreground"
                                }`}
                        >
                            {msg.content}
                        </div>
                    </div>
                ))}
            </div>

            <div className="border-t border-border p-3">
                <div className="flex items-end gap-2">
                    <textarea
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === "Enter" && !e.shiftKey) {
                                e.preventDefault();
                                void handleSend();
                            }
                        }}
                        placeholder="输入需求，例如：实现用户登录功能…"
                        rows={2}
                        className="flex-1 resize-none rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
                    />
                    <button
                        onClick={() => void handleSend()}
                        disabled={sending || !input.trim()}
                        className="inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
                    >
                        {sending ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                            <SendHorizonal className="h-4 w-4" />
                        )}
                        发送
                    </button>
                </div>
            </div>
        </section>
    );
}
