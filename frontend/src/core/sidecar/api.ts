import { getAPIClient } from "@/core/api";
import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";
import type { AgentThread } from "@/core/threads";

import type { SidecarContext } from "./context";
import {
  SIDECAR_METADATA_KEY,
  buildSidecarThreadMetadata,
  isSidecarThread,
} from "./thread";

/** 查找侧栏线程所需的最小客户端能力，便于在测试中注入替身。 */
type SidecarThreadSearchClient = {
  threads: {
    search: (query: Record<string, unknown>) => Promise<AgentThread[]>;
  };
};

/**
 * 查找后创建是彼此独立的两次请求，后端也没有原子创建或更新能力。双击侧栏提问或同一父线程的两个调用方竞争时，
 * 均可能创建重复线程；此映射将同一父线程的并发创建合并为同一个进行中的承诺，并在完成后清除条目。
 */
const inFlightCreates = new Map<string, Promise<AgentThread>>();

/** 创建关联父线程的侧栏线程；同一父线程的并发请求复用同一次创建。 */
export async function createSidecarThread({
  parentThreadId,
  context,
}: {
  parentThreadId: string;
  context: SidecarContext | SidecarContext[];
}): Promise<AgentThread> {
  const inFlight = inFlightCreates.get(parentThreadId);
  if (inFlight) {
    return inFlight;
  }

  const request = createSidecarThreadRequest({ parentThreadId, context });
  inFlightCreates.set(parentThreadId, request);
  try {
    return await request;
  } finally {
    if (inFlightCreates.get(parentThreadId) === request) {
      inFlightCreates.delete(parentThreadId);
    }
  }
}

/** 调用线程接口创建侧栏线程，并兼容客户端能力差异。 */
async function createSidecarThreadRequest({
  parentThreadId,
  context,
}: {
  parentThreadId: string;
  context: SidecarContext | SidecarContext[];
}): Promise<AgentThread> {
  const response = await fetchWithAuth(`${getBackendBaseURL()}/api/threads`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      metadata: buildSidecarThreadMetadata(parentThreadId, context),
    }),
  });

  if (!response.ok) {
    throw new Error("Failed to create side conversation.");
  }

  return (await response.json()) as AgentThread;
}

/** 查找父线程最近创建的侧栏线程。 */
export async function findLatestSidecarThread({
  parentThreadId,
  isMock,
  apiClient = getAPIClient(isMock) as SidecarThreadSearchClient,
}: {
  parentThreadId: string;
  isMock?: boolean;
  apiClient?: SidecarThreadSearchClient;
}): Promise<AgentThread | null> {
  const response = await apiClient.threads.search({
    metadata: {
      [SIDECAR_METADATA_KEY]: true,
      parent_thread_id: parentThreadId,
    },
    limit: 1,
    offset: 0,
    sortBy: "updated_at",
    sortOrder: "desc",
  });

  return (
    response.find(
      (thread) =>
        isSidecarThread(thread) &&
        thread.metadata?.parent_thread_id === parentThreadId,
    ) ?? null
  );
}
