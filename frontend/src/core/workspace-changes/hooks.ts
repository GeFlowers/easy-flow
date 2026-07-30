import { useQuery } from "@tanstack/react-query";

import { fetchWorkspaceChanges } from "./api";
import type { WorkspaceChangesResponse } from "./types";

/** 构造运行级工作区变更查询的稳定缓存键。 */
export function workspaceChangesQueryKey(
  threadId: string | undefined,
  runId: string | undefined,
  includeFiles: boolean,
  includeDiff: boolean,
) {
  return [
    "workspace-changes",
    threadId,
    runId,
    includeFiles,
    includeDiff,
  ] as const;
}

/** 查询指定线程和运行产生的工作区文件变更。 */
export function useWorkspaceChanges({
  threadId,
  runId,
  includeFiles = true,
  includeDiff = true,
  enabled = true,
}: {
  threadId?: string;
  runId?: string;
  includeFiles?: boolean;
  includeDiff?: boolean;
  enabled?: boolean;
}) {
  return useQuery<WorkspaceChangesResponse>({
    queryKey: workspaceChangesQueryKey(
      threadId,
      runId,
      includeFiles,
      includeDiff,
    ),
    queryFn: () => {
      if (!threadId || !runId) {
        throw new Error("threadId and runId are required");
      }
      return fetchWorkspaceChanges({
        threadId,
        runId,
        includeFiles,
        includeDiff,
      });
    },
    enabled: enabled && Boolean(threadId) && Boolean(runId),
    retry: false,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
}
