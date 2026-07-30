import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { ThreadTokenUsageResponse } from "./types";

/** 线程上下文压缩接口返回的数据。 */
export type ThreadCompactResponse = {
  thread_id: string;
  compacted: boolean;
  reason?: string | null;
  removed_message_count: number;
  preserved_message_count: number;
  summary_updated: boolean;
  checkpoint_id?: string | null;
  total_tokens: number;
};

/** 请求压缩线程上下文时可传入的选项。 */
export type CompactThreadContextOptions = {
  signal?: AbortSignal;
  agentName?: string | null;
};

/** 从消息轮次分叉线程接口返回的数据。 */
export type ThreadBranchResponse = {
  thread_id: string;
  parent_thread_id: string;
  parent_checkpoint_id: string;
  branched_from_message_id: string;
  workspace_clone_mode: string;
};

/** 创建分叉线程所需的来源消息与可选标题。 */
export type BranchThreadFromTurnInput = {
  messageId: string;
  messageIds?: string[];
  title?: string;
};

/** 从线程接口失败响应中读取错误详情。 */
async function readThreadAPIError(
  response: Response,
  fallback: string,
): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail) {
      return body.detail;
    }
  } catch {
    // 无法读取响应体时，使用调用方提供的回退消息。
  }
  return fallback;
}

/** 获取线程的累计令牌用量。 */
export async function fetchThreadTokenUsage(
  threadId: string,
): Promise<ThreadTokenUsageResponse | null> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/token-usage`,
    {
      method: "GET",
    },
  );

  if (!response.ok) {
    if (response.status === 403 || response.status === 404) {
      return null;
    }
    throw new Error("Failed to load thread token usage.");
  }

  return (await response.json()) as ThreadTokenUsageResponse;
}

/** 从指定消息轮次创建分叉线程。 */
export async function branchThreadFromTurn(
  threadId: string,
  input: BranchThreadFromTurnInput,
): Promise<ThreadBranchResponse> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/branches`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message_id: input.messageId,
        message_ids: input.messageIds ?? [input.messageId],
        ...(input.title ? { title: input.title } : {}),
      }),
    },
  );

  if (!response.ok) {
    throw new Error(
      await readThreadAPIError(response, "Failed to branch conversation."),
    );
  }

  return (await response.json()) as ThreadBranchResponse;
}

/** 请求后端压缩指定线程的旧上下文。 */
export async function compactThreadContext(
  threadId: string,
  options: CompactThreadContextOptions = {},
): Promise<ThreadCompactResponse> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/compact`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        force: true,
        ...(options.agentName ? { agent_name: options.agentName } : {}),
      }),
      signal: options.signal,
    },
  );

  if (!response.ok) {
    throw new Error(
      await readThreadAPIError(response, "Failed to compact context."),
    );
  }

  return (await response.json()) as ThreadCompactResponse;
}
