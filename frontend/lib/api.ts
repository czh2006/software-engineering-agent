/**
 * 后端 API 客户端与类型定义。
 *
 * 类型与后端 Pydantic Schema（app/schemas/*.py）保持一致。
 */

/** 健康检查响应（对应后端 HealthResponse）。 */
export interface HealthResponse {
    status: string;
    version: string;
    environment: string;
}

const API_URL: string = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const BASE_URL = `${API_URL}/api/v1`;

/** 请求后端健康检查接口。 */
export async function fetchHealth(): Promise<HealthResponse> {
    const res = await fetch(`${BASE_URL}/health`, {
        cache: "no-store",
    });

    if (!res.ok) {
        throw new Error(`健康检查失败：HTTP ${res.status}`);
    }

    return (await res.json()) as HealthResponse;
}

/** 聊天消息（前端展示用）。 */
export interface ChatMessage {
    role: "user" | "assistant";
    content: string;
}

/** 聊天响应（对应后端 ChatResponse）。 */
export interface ChatResponse {
    message: string;
    session_id: string;
    created_at: string;
}

/** 发送聊天消息到后端（Day1 Mock）。 */
export async function sendChat(message: string): Promise<ChatResponse> {
    const res = await fetch(`${BASE_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
    });

    if (!res.ok) {
        throw new Error(`聊天请求失败：HTTP ${res.status}`);
    }

    return (await res.json()) as ChatResponse;
}

/** RAG 检索请求参数。 */
export interface RagSearchParams {
    query: string;
    top_k: number;
}

/** RAG 检索单条结果（对应后端 SearchResult）。 */
export interface RagSearchResult {
    file_path: string;
    symbol_name: string;
    score: number;
    code: string;
    line_range: string;
}

const RAG_URL = `${API_URL}/rag`;

/** 调用后端 RAG 语义检索接口。 */
export async function searchCode(
    query: string,
    topK = 5
): Promise<RagSearchResult[]> {
    const res = await fetch(`${RAG_URL}/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, top_k: topK } satisfies RagSearchParams),
    });

    if (!res.ok) {
        throw new Error(`RAG 检索失败：HTTP ${res.status}`);
    }

    const data = (await res.json()) as { results: RagSearchResult[] };
    return data.results;
}
