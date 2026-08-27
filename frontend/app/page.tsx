import { ChatPanel } from "@/components/chat-panel";
import { DiffPanel } from "@/components/diff-panel";
import { Sidebar } from "@/components/sidebar";
import { TerminalPanel } from "@/components/terminal-panel";
import { TimelinePanel } from "@/components/timeline-panel";

/** Day1 工作台：软件工程团队协作界面（全部假数据）。 */
export default function Home() {
    return (
        <div className="flex h-screen overflow-hidden bg-background text-foreground">
            <Sidebar />
            <main className="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)_minmax(0,1fr)] gap-3 p-3">
                <div className="grid min-h-0 grid-cols-1 gap-3 lg:grid-cols-2">
                    <ChatPanel />
                    <DiffPanel />
                </div>
                <div className="grid min-h-0 grid-cols-1 gap-3 lg:grid-cols-2">
                    <TimelinePanel />
                    <TerminalPanel />
                </div>
            </main>
        </div>
    );
}
