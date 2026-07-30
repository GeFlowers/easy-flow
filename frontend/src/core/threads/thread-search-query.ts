import type { ThreadsClient } from "@langchain/langgraph-sdk/client";

import {
  SIDECAR_METADATA_KEY,
  shouldShowInPrimaryThreadLists,
} from "@/core/sidecar/thread";

import type { AgentThread, AgentThreadState } from "./types";

type ThreadsSearchClient = {
  threads: {
    search: ThreadsClient["search"];
  };
};

/** 线程搜索接口支持的完整查询参数。 */
export type ThreadSearchParams = NonNullable<
  Parameters<ThreadsClient["search"]>[0]
>;

/** 未指定筛选条件时使用的线程搜索参数。 */
export const DEFAULT_THREAD_SEARCH_PARAMS: ThreadSearchParams = {
  limit: 50,
  sortBy: "updated_at",
  sortOrder: "desc",
  select: ["thread_id", "updated_at", "values", "metadata"],
};

/** 线程搜索结果的自动刷新间隔（毫秒）。 */
export const THREAD_SEARCH_REFETCH_INTERVAL_MS = 5000;

type ThreadSearchFilterParams = Pick<ThreadSearchParams, "metadata">;

/** 判断搜索参数是否明确要求包含侧栏线程。 */
export function shouldIncludeSidecarThreads(params: ThreadSearchFilterParams) {
  const metadata = params.metadata;
  return (
    typeof metadata === "object" &&
    metadata !== null &&
    !Array.isArray(metadata) &&
    Reflect.get(metadata, SIDECAR_METADATA_KEY) === true
  );
}

/** 按搜索参数筛除默认不展示的侧栏线程。 */
export function filterThreadSearchResults(
  threads: AgentThread[],
  params: ThreadSearchFilterParams,
) {
  if (shouldIncludeSidecarThreads(params)) {
    return threads;
  }
  return threads.filter(shouldShowInPrimaryThreadLists);
}

/** 构建会自动分页拉取线程搜索结果的查询选项。 */
export function buildThreadsSearchQueryOptions(
  apiClient: ThreadsSearchClient,
  params: ThreadSearchParams = DEFAULT_THREAD_SEARCH_PARAMS,
) {
  return {
    queryKey: ["threads", "search", params],
    queryFn: async () => {
      const maxResults = params.limit;
      const initialOffset = params.offset ?? 0;
      const DEFAULT_PAGE_SIZE = 50;

      // 显式给出非正限制值时保持既有语义：使用原参数只执行一次搜索。
      if (maxResults !== undefined && maxResults <= 0) {
        const response =
          await apiClient.threads.search<AgentThreadState>(params);
        return filterThreadSearchResults(response as AgentThread[], params);
      }

      const pageSize =
        typeof maxResults === "number" && maxResults > 0
          ? Math.min(DEFAULT_PAGE_SIZE, maxResults)
          : DEFAULT_PAGE_SIZE;

      const threads: AgentThread[] = [];
      let offset = initialOffset;

      while (true) {
        if (typeof maxResults === "number" && threads.length >= maxResults) {
          break;
        }

        const currentLimit =
          typeof maxResults === "number"
            ? Math.min(pageSize, maxResults - threads.length)
            : pageSize;

        if (typeof maxResults === "number" && currentLimit <= 0) {
          break;
        }

        const response = (await apiClient.threads.search<AgentThreadState>({
          ...params,
          limit: currentLimit,
          offset,
        })) as AgentThread[];

        threads.push(...filterThreadSearchResults(response, params));

        if (response.length < currentLimit) {
          break;
        }

        offset += response.length;
      }

      return threads;
    },
    refetchInterval: THREAD_SEARCH_REFETCH_INTERVAL_MS,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: false,
  };
}
