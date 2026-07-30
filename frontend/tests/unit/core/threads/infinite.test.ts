import { describe, expect, rs, test } from "@rstest/core";
import {
  QueryClient,
  QueryObserver,
  type InfiniteData,
} from "@tanstack/react-query";

import {
  fetchInfiniteThreadsPage,
  filterInfiniteThreadsCache,
  getInfiniteThreadsNextPageParam,
  INFINITE_THREADS_PAGE_SIZE,
  INFINITE_THREADS_QUERY_KEY_PREFIX,
  invalidateStoppedThreadCaches,
  mapInfiniteThreadsCache,
  STOP_THREAD_FINALIZATION_REFETCH_DELAY_MS,
  stopThreadAndInvalidateCaches,
  upsertThreadInInfiniteCache,
} from "@/core/threads/hooks";
import type { AgentThread } from "@/core/threads/types";

// 问题 #3482：侧边栏和 /workspace/chats 列表曾被限制为 50 个线程，因为
// `useThreads()` 一旦 `threads.length >= params.limit` 就退出。这些纯辅助函数支撑
// `useInfiniteThreads()` 分页逻辑及镜像缓存写入，使重命名/删除/流结束同时与旧数组缓存
// 和新无限缓存保持同步。

/**
 * 构造测试所需的稳定夹具，使调用处能够明确复用 makeThread 的约定。

 */

function makeThread(
  id: string,
  title = `Title ${id}`,
  metadata: Record<string, unknown> = {},
): AgentThread {
  return {
    thread_id: id,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    metadata,
    status: "idle",
    values: { title },
  } as unknown as AgentThread;
}

/**
 * 构造测试所需的稳定夹具，使调用处能够明确复用 makePage 的约定。

 */

function makePage(start: number, size: number): AgentThread[] {
  return Array.from({ length: size }, (_, i) => makeThread(`t-${start + i}`));
}

/**
 * 构造测试所需的稳定夹具，使调用处能够明确复用 makeInfiniteData 的约定。

 */

function makeInfiniteData(pages: AgentThread[][]): InfiniteData<AgentThread[]> {
  return {
    pages,
    pageParams: pages.map((_, i) => i * INFINITE_THREADS_PAGE_SIZE),
  };
}

describe("getInfiniteThreadsNextPageParam", () => {
  /**
   * 覆盖“returns next offset when the last page is full”这一可观察行为，防止相关边界在重构后回归。
   */
  test("returns next offset when the last page is full", () => {
    const page1 = makePage(0, INFINITE_THREADS_PAGE_SIZE);
    expect(getInfiniteThreadsNextPageParam(page1, [page1])).toBe(
      INFINITE_THREADS_PAGE_SIZE,
    );
  });

  /**
   * 覆盖“returns next offset across multiple full pages”这一可观察行为，防止相关边界在重构后回归。

   */

  test("returns next offset across multiple full pages", () => {
    const page1 = makePage(0, INFINITE_THREADS_PAGE_SIZE);
    const page2 = makePage(
      INFINITE_THREADS_PAGE_SIZE,
      INFINITE_THREADS_PAGE_SIZE,
    );
    expect(getInfiniteThreadsNextPageParam(page2, [page1, page2])).toBe(
      INFINITE_THREADS_PAGE_SIZE * 2,
    );
  });

  /**
   * 覆盖“returns undefined when the last page is short (end of list)”这一可观察行为，防止相关边界在重构后回归。

   */

  test("returns undefined when the last page is short (end of list)", () => {
    const page1 = makePage(0, INFINITE_THREADS_PAGE_SIZE);
    const page2 = makePage(INFINITE_THREADS_PAGE_SIZE, 10);
    expect(
      getInfiniteThreadsNextPageParam(page2, [page1, page2]),
    ).toBeUndefined();
  });

  /**
   * 覆盖“returns undefined when the last page is empty”这一可观察行为，防止相关边界在重构后回归。

   */

  test("returns undefined when the last page is empty", () => {
    const page1 = makePage(0, INFINITE_THREADS_PAGE_SIZE);
    expect(getInfiniteThreadsNextPageParam([], [page1, []])).toBeUndefined();
  });

  /**
   * 覆盖“respects a custom page size”这一可观察行为，防止相关边界在重构后回归。

   */

  test("respects a custom page size", () => {
    const page1 = makePage(0, 5);
    expect(getInfiniteThreadsNextPageParam(page1, [page1], 5)).toBe(5);
    expect(getInfiniteThreadsNextPageParam(page1, [page1], 10)).toBeUndefined();
  });
});

describe("fetchInfiniteThreadsPage", () => {
  /**
   * 覆盖“fills a visible page while advancing offsets by raw backend rows”这一可观察行为，防止相关边界在重构后回归。
   */
  test("fills a visible page while advancing offsets by raw backend rows", async () => {
    const search = rs
      .fn()
      .mockResolvedValueOnce([
        makeThread("sidecar-1", "Sidecar", { deerflow_sidecar: true }),
        makeThread("primary-1"),
      ])
      .mockResolvedValueOnce([makeThread("primary-2")]);

    const page = await fetchInfiniteThreadsPage(
      { threads: { search } },
      { sortBy: "updated_at", sortOrder: "desc" },
      0,
      2,
    );

    expect(page.map((thread) => thread.thread_id)).toEqual([
      "primary-1",
      "primary-2",
    ]);
    expect(search).toHaveBeenNthCalledWith(1, {
      sortBy: "updated_at",
      sortOrder: "desc",
      limit: 2,
      offset: 0,
    });
    expect(search).toHaveBeenNthCalledWith(2, {
      sortBy: "updated_at",
      sortOrder: "desc",
      limit: 1,
      offset: 2,
    });
    expect(getInfiniteThreadsNextPageParam(page, [page], 2)).toBe(3);
  });

  /**
   * 覆盖“keeps sidecar rows when the caller explicitly searches for sidecars”这一可观察行为，防止相关边界在重构后回归。

   */

  test("keeps sidecar rows when the caller explicitly searches for sidecars", async () => {
    const search = rs.fn().mockResolvedValueOnce([
      makeThread("sidecar-1", "Sidecar", {
        deerflow_sidecar: true,
        parent_thread_id: "parent-1",
      }),
    ]);

    const page = await fetchInfiniteThreadsPage(
      { threads: { search } },
      {
        sortBy: "updated_at",
        sortOrder: "desc",
        metadata: { deerflow_sidecar: true, parent_thread_id: "parent-1" },
      },
      0,
      2,
    );

    expect(page.map((thread) => thread.thread_id)).toEqual(["sidecar-1"]);
    expect(getInfiniteThreadsNextPageParam(page, [page], 2)).toBeUndefined();
  });
});

describe("mapInfiniteThreadsCache", () => {
  /**
   * 覆盖“returns undefined when oldData is undefined”这一可观察行为，防止相关边界在重构后回归。
   */
  test("returns undefined when oldData is undefined", () => {
    expect(mapInfiniteThreadsCache(undefined, (t) => t)).toBeUndefined();
  });

  /**
   * 覆盖“updates the matching thread across multiple pages”这一可观察行为，防止相关边界在重构后回归。

   */

  test("updates the matching thread across multiple pages", () => {
    const page1 = [makeThread("a"), makeThread("b")];
    const page2 = [makeThread("c"), makeThread("d")];
    const data = makeInfiniteData([page1, page2]);

    const updated = mapInfiniteThreadsCache(data, (t) =>
      t.thread_id === "c"
        ? { ...t, values: { ...t.values, title: "renamed" } }
        : t,
    );

    expect(updated?.pages[0]?.[0]?.values?.title).toBe("Title a");
    expect(updated?.pages[1]?.[0]?.thread_id).toBe("c");
    expect(updated?.pages[1]?.[0]?.values?.title).toBe("renamed");
    expect(updated?.pages[1]?.[1]?.values?.title).toBe("Title d");
  });

  /**
   * 覆盖“preserves pageParams”这一可观察行为，防止相关边界在重构后回归。

   */

  test("preserves pageParams", () => {
    const data = makeInfiniteData([[makeThread("a")]]);
    const updated = mapInfiniteThreadsCache(data, (t) => t);
    expect(updated?.pageParams).toEqual(data.pageParams);
  });
});

describe("filterInfiniteThreadsCache", () => {
  /**
   * 覆盖“returns undefined when oldData is undefined”这一可观察行为，防止相关边界在重构后回归。
   */
  test("returns undefined when oldData is undefined", () => {
    expect(filterInfiniteThreadsCache(undefined, () => true)).toBeUndefined();
  });

  /**
   * 覆盖“removes matching threads across all pages”这一可观察行为，防止相关边界在重构后回归。

   */

  test("removes matching threads across all pages", () => {
    const page1 = [makeThread("a"), makeThread("b")];
    const page2 = [makeThread("b"), makeThread("c")];
    const data = makeInfiniteData([page1, page2]);

    const filtered = filterInfiniteThreadsCache(
      data,
      (t) => t.thread_id !== "b",
    );

    expect(filtered?.pages[0]?.map((t) => t.thread_id)).toEqual(["a"]);
    expect(filtered?.pages[1]?.map((t) => t.thread_id)).toEqual(["c"]);
  });

  /**
   * 覆盖“keeps an emptied page as an empty array (does not drop the page)”这一可观察行为，防止相关边界在重构后回归。

   */

  test("keeps an emptied page as an empty array (does not drop the page)", () => {
    const page1 = [makeThread("a")];
    const page2 = [makeThread("b")];
    const data = makeInfiniteData([page1, page2]);

    const filtered = filterInfiniteThreadsCache(
      data,
      (t) => t.thread_id !== "a",
    );

    expect(filtered?.pages).toHaveLength(2);
    expect(filtered?.pages[0]).toEqual([]);
    expect(filtered?.pages[1]?.[0]?.thread_id).toBe("b");
  });

  /**
   * 覆盖“does not regress next offset when an earlier page has been shrunk by a delete”这一可观察行为，防止相关边界在重构后回归。

   */

  test("does not regress next offset when an earlier page has been shrunk by a delete", () => {
    // 模拟已加载两个完整页面。
    const page1 = Array.from({ length: 50 }, (_, i) => ({
      thread_id: `a${i}`,
    }));
    const page2 = Array.from({ length: 50 }, (_, i) => ({
      thread_id: `b${i}`,
    }));

    // 获取第 2 页后紧接着的偏移量（这是 TanStack Query 固化到 pageParams 的值）。
    const offsetAfterPage2 = getInfiniteThreadsNextPageParam(
      page2 as unknown as AgentThread[],
      [page1, page2] as unknown as AgentThread[][],
    );
    expect(offsetAfterPage2).toBe(100);

    // 此时删除变更运行 filterInfiniteThreadsCache，将第 1 页从 50 项缩减为 49 项。
    // TanStack 不会在缓存变更时重新调用 getNextPageParam；先前计算的偏移量 (100)
    // 仍是下一次 fetchNextPage() 调用的参数，因此该辅助函数与库使用其返回值的方式一致。
    const shrunkPage1 = page1.slice(0, 49);
    const recomputed = getInfiniteThreadsNextPageParam(
      page2 as unknown as AgentThread[],
      [shrunkPage1, page2] as unknown as AgentThread[][],
    );
    // 为完整起见记录重新计算的值，但实践中 useDeleteThread 会在 onSettled 中使查询失效，
    // 因此页面会从偏移量 0 重新获取，而不是依赖该数值。
    expect(recomputed).toBe(99);
  });
});

describe("upsertThreadInInfiniteCache", () => {
  /**
   * 封装测试或脚本中的可复用操作，使调用处能够明确复用 seedClient 的约定。
   */
  function seedClient(initial?: InfiniteData<AgentThread[]>): QueryClient {
    const client = new QueryClient();
    if (initial) {
      client.setQueryData([...INFINITE_THREADS_QUERY_KEY_PREFIX, {}], initial);
    }
    return client;
  }

  /**
   * 封装测试或脚本中的可复用操作，使调用处能够明确复用 readCache 的约定。

   */

  function readCache(
    client: QueryClient,
  ): InfiniteData<AgentThread[]> | undefined {
    return client.getQueryData([...INFINITE_THREADS_QUERY_KEY_PREFIX, {}]);
  }

  /**
   * 覆盖“no-op when the infinite cache has not been initialised yet”这一可观察行为，防止相关边界在重构后回归。

   */

  test("no-op when the infinite cache has not been initialised yet", () => {
    const client = seedClient();
    upsertThreadInInfiniteCache(client, makeThread("new"));
    expect(readCache(client)).toBeUndefined();
  });

  /**
   * 覆盖“prepends a brand-new thread to the first page”这一可观察行为，防止相关边界在重构后回归。

   */

  test("prepends a brand-new thread to the first page", () => {
    const client = seedClient({
      pages: [[makeThread("a"), makeThread("b")]],
      pageParams: [0],
    });
    upsertThreadInInfiniteCache(client, makeThread("new"));
    const cache = readCache(client);
    expect(cache?.pages[0]?.map((t) => t.thread_id)).toEqual(["new", "a", "b"]);
  });

  /**
   * 覆盖“merges into the existing entry instead of duplicating it”这一可观察行为，防止相关边界在重构后回归。

   */

  test("merges into the existing entry instead of duplicating it", () => {
    const existing = makeThread("a", "Old title");
    const client = seedClient({
      pages: [[existing, makeThread("b")]],
      pageParams: [0],
    });
    // 模拟 onCreated upsert 与缓存中已有线程发生竞争：缓存副本应在标题/元数据上获胜
    // （它代表较晚状态），但不应出现重复行。
    upsertThreadInInfiniteCache(client, {
      ...makeThread("a", "New title"),
      status: "busy",
    });
    const cache = readCache(client);
    const ids = cache?.pages[0]?.map((t) => t.thread_id);
    expect(ids).toEqual(["a", "b"]);
    expect(cache?.pages[0]?.[0]?.values.title).toBe("Old title");
  });
});

describe("invalidateStoppedThreadCaches", () => {
  /**
   * 封装测试或脚本中的可复用操作，使调用处能够明确复用 invalidatedQueryKeys 的约定。
   */
  function invalidatedQueryKeys(client: QueryClient) {
    const invalidate = rs.spyOn(client, "invalidateQueries");
    return {
      invalidate,
      queryKeys: () =>
        invalidate.mock.calls.map(([filters]) => filters?.queryKey),
    };
  }

  /**
   * 覆盖“refreshes current thread and sidebar caches after fire-and-forget stop”这一可观察行为，防止相关边界在重构后回归。

   */

  test("refreshes current thread and sidebar caches after fire-and-forget stop", () => {
    const client = new QueryClient();
    const { queryKeys } = invalidatedQueryKeys(client);

    invalidateStoppedThreadCaches(client, "thread-1", false);

    expect(queryKeys()).toContainEqual(["threads", "search"]);
    expect(queryKeys()).toContainEqual(INFINITE_THREADS_QUERY_KEY_PREFIX);
    expect(queryKeys()).toContainEqual(["thread", "thread-1"]);
    expect(queryKeys()).toContainEqual([
      "thread",
      "metadata",
      "thread-1",
      false,
    ]);
    expect(queryKeys()).toContainEqual(["thread-token-usage", "thread-1"]);
  });

  /**
   * 覆盖“preserves loaded history pages while invalidating”这一可观察行为，防止相关边界在重构后回归。

   */

  test("preserves loaded history pages while invalidating", () => {
    const client = new QueryClient();
    const key = ["thread-messages", "thread-1"] as const;
    const latest = { data: [], has_more: true, next_before_seq: 20 };
    const older = { data: [], has_more: false, next_before_seq: null };
    client.setQueryData(key, {
      pages: [latest, older],
      pageParams: [null, 20],
    });

    invalidateStoppedThreadCaches(client, "thread-1", false);

    expect(client.getQueryData(key)).toEqual({
      pages: [latest, older],
      pageParams: [null, 20],
    });
  });

  /**
   * 覆盖“does not refresh per-thread API caches for mock threads”这一可观察行为，防止相关边界在重构后回归。

   */

  test("does not refresh per-thread API caches for mock threads", () => {
    const client = new QueryClient();
    const { queryKeys } = invalidatedQueryKeys(client);

    invalidateStoppedThreadCaches(client, "thread-1", true);

    expect(queryKeys()).toContainEqual(["threads", "search"]);
    expect(queryKeys()).toContainEqual(INFINITE_THREADS_QUERY_KEY_PREFIX);
    expect(queryKeys()).not.toContainEqual(["thread", "thread-1"]);
    expect(queryKeys()).not.toContainEqual([
      "thread",
      "metadata",
      "thread-1",
      true,
    ]);
    expect(queryKeys()).not.toContainEqual(["thread-token-usage", "thread-1"]);
  });

  /**
   * 覆盖“wraps SDK stop and refreshes caches after it resolves”这一可观察行为，防止相关边界在重构后回归。

   */

  test("wraps SDK stop and refreshes caches after it resolves", async () => {
    const client = new QueryClient();
    const stop = rs.fn(() => Promise.resolve());
    const { queryKeys } = invalidatedQueryKeys(client);

    await stopThreadAndInvalidateCaches(client, stop, "thread-1", false);

    expect(stop).toHaveBeenCalledTimes(1);
    expect(queryKeys()).toContainEqual([
      "thread",
      "metadata",
      "thread-1",
      false,
    ]);
  });

  /**
   * 覆盖“still refreshes caches when SDK stop rejects”这一可观察行为，防止相关边界在重构后回归。

   */

  test("still refreshes caches when SDK stop rejects", async () => {
    const client = new QueryClient();
    const stop = rs.fn(async () => {
      throw new Error("cancel failed");
    });
    const { queryKeys } = invalidatedQueryKeys(client);

    await expect(
      stopThreadAndInvalidateCaches(client, stop, "thread-1", false),
    ).rejects.toThrow("cancel failed");

    expect(queryKeys()).toContainEqual(["threads", "search"]);
    expect(queryKeys()).toContainEqual([
      "thread",
      "metadata",
      "thread-1",
      false,
    ]);
  });

  /**
   * 覆盖“schedules sidebar refetch even if stopped thread id is not known”这一可观察行为，防止相关边界在重构后回归。

   */

  test("schedules sidebar refetch even if stopped thread id is not known", async () => {
    rs.useFakeTimers();

    const client = new QueryClient();
    const { queryKeys } = invalidatedQueryKeys(client);

    try {
      await stopThreadAndInvalidateCaches(
        client,
        () => Promise.resolve(),
        null,
        false,
      );

      /**
       * 封装局部测试或脚本流程中的具名操作，避免调用处重复实现 countSearchInvalidations 约定的逻辑。

       */

      const countSearchInvalidations = () =>
        queryKeys().filter(
          (queryKey) =>
            queryKey?.length === 2 &&
            queryKey[0] === "threads" &&
            queryKey[1] === "search",
        ).length;

      expect(countSearchInvalidations()).toBe(1);

      await rs.advanceTimersByTimeAsync(
        STOP_THREAD_FINALIZATION_REFETCH_DELAY_MS,
      );

      expect(countSearchInvalidations()).toBe(2);
      expect(queryKeys()).not.toContainEqual(["thread", null]);
    } finally {
      client.clear();
      rs.useRealTimers();
    }
  });

  /**
   * 覆盖“scheduled refetch lets sidebar receive delayed backend title finalization”这一可观察行为，防止相关边界在重构后回归。

   */

  test("scheduled refetch lets sidebar receive delayed backend title finalization", async () => {
    rs.useFakeTimers();

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    let finalized = false;
    let fetchCount = 0;
    const observer = new QueryObserver<AgentThread[]>(client, {
      queryKey: ["threads", "search"],
      queryFn: async () => {
        fetchCount += 1;
        return [
          makeThread(
            "thread-1",
            finalized ? "Generated Title" : "New Conversation",
          ),
        ];
      },
    });
    const unsubscribe = observer.subscribe((result) => {
      void result.status;
    });

    try {
      await observer.refetch();
      expect(
        client.getQueryData<AgentThread[]>(["threads", "search"])?.[0]?.values
          ?.title,
      ).toBe("New Conversation");

      await stopThreadAndInvalidateCaches(
        client,
        () => Promise.resolve(),
        "thread-1",
        false,
      );
      await Promise.resolve();

      expect(
        client.getQueryData<AgentThread[]>(["threads", "search"])?.[0]?.values
          ?.title,
      ).toBe("New Conversation");

      finalized = true;
      await rs.advanceTimersByTimeAsync(
        STOP_THREAD_FINALIZATION_REFETCH_DELAY_MS,
      );

      expect(
        client.getQueryData<AgentThread[]>(["threads", "search"])?.[0]?.values
          ?.title,
      ).toBe("Generated Title");
      expect(fetchCount).toBeGreaterThanOrEqual(3);
    } finally {
      unsubscribe();
      client.clear();
      rs.useRealTimers();
    }
  });
});
