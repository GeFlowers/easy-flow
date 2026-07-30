import type { Message } from "@langchain/langgraph-sdk";
import { expect, rs, test } from "@rstest/core";
import { InfiniteQueryObserver, QueryClient } from "@tanstack/react-query";

import {
  buildThreadMessagesPageUrl,
  buildVisibleHistoryMessages,
  computeSummarizationTransientMessages,
  flattenThreadHistoryPages,
  getSummarizationMiddlewareMessages,
  getThreadHistoryNextPageParam,
  getVisibleOptimisticMessages,
  mergeTransientHistoryBridge,
  mergeTransientHistoryBridgeOrder,
  mergeMessages,
  pruneConfirmedTransientMessages,
  removeSetItems,
  resolveThreadTransientHistoryBridge,
  resolveTransientHistoryBridge,
  type ThreadMessagesPageResponse,
} from "@/core/threads/hooks";
import type { RunMessage } from "@/core/threads/types";

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 runMessage 的约定。

 */

function runMessage(seq?: number): RunMessage {
  return {
    run_id: "run-1",
    ...(seq === undefined ? {} : { seq }),
    content: {} as Message,
    metadata: { caller: "" },
    created_at: "2026-05-22T00:00:00Z",
  };
}

/**
 * 覆盖“mergeMessages removes duplicate messages already present in history”这一可观察行为，防止相关边界在重构后回归。

 */

test("mergeMessages removes duplicate messages already present in history", () => {
  const human = {
    id: "human-1",
    type: "human",
    content: "Design an agent",
  } as Message;
  const ai = {
    id: "ai-1",
    type: "ai",
    content: "Let's design it.",
  } as Message;

  expect(mergeMessages([human, ai, human, ai], [], [])).toEqual([human, ai]);
});

/**
 * 覆盖“mergeMessages does not collapse an unloaded gap before the first shared anchor”这一可观察行为，防止相关边界在重构后回归。

 */

test("mergeMessages does not collapse an unloaded gap before the first shared anchor", () => {
  const protectedEarly = {
    id: "protected-early",
    type: "human",
    content: "写一个算法PDF",
  } as Message;
  const latestHuman = {
    id: "latest-human",
    type: "human",
    content: "写一本超级小说",
  } as Message;
  const latestAi = {
    id: "latest-ai",
    type: "ai",
    content: "latest answer",
  } as Message;

  expect(
    mergeMessages([latestHuman, latestAi], [protectedEarly, latestHuman], []),
  ).toEqual([latestHuman, latestAi]);
});

/**
 * 覆盖“mergeMessages lets live thread messages replace overlapping history”这一可观察行为，防止相关边界在重构后回归。

 */

test("mergeMessages lets live thread messages replace overlapping history", () => {
  const oldHuman = {
    id: "human-1",
    type: "human",
    content: "old",
  } as Message;
  const liveHuman = {
    id: "human-1",
    type: "human",
    content: "live",
  } as Message;
  const oldAi = {
    id: "ai-1",
    type: "ai",
    content: "old",
  } as Message;
  const liveAi = {
    id: "ai-1",
    type: "ai",
    content: "live",
  } as Message;

  expect(mergeMessages([oldHuman, oldAi], [liveHuman, liveAi], [])).toEqual([
    liveHuman,
    liveAi,
  ]);
});

/**
 * 覆盖“mergeMessages keeps a protected pre-compression input at its canonical position”这一可观察行为，防止相关边界在重构后回归。

 */

test("mergeMessages keeps a protected pre-compression input at its canonical position", () => {
  const canonicalInput = {
    id: "input-1",
    type: "human",
    content: "写一个算法PDF",
  } as Message;
  const checkpointInput = {
    id: "input-1",
    type: "human",
    content: [{ type: "text", text: "写一个算法PDF" }],
  } as Message;
  const clarificationCard = {
    id: "clarification-card",
    type: "tool",
    tool_call_id: "clarification-call",
    content: "Create a new PDF",
  } as Message;
  const directionAnswer = {
    id: "input-3",
    type: "human",
    content: "二叉树相关的即可",
  } as Message;
  const canonicalRetainedTail = {
    id: "retained-ai",
    type: "ai",
    content: "persisted tail",
  } as Message;
  const checkpointRetainedTail = {
    id: "retained-ai",
    type: "ai",
    content: "live tail",
  } as Message;

  expect(
    mergeMessages(
      [
        canonicalInput,
        clarificationCard,
        directionAnswer,
        canonicalRetainedTail,
      ],
      [checkpointInput, checkpointRetainedTail],
      [],
    ),
  ).toEqual([
    checkpointInput,
    clarificationCard,
    directionAnswer,
    checkpointRetainedTail,
  ]);
});

/**
 * 覆盖“mergeMessages keeps source order when history and live tail do not overlap”这一可观察行为，防止相关边界在重构后回归。

 */

test("mergeMessages keeps source order when history and live tail do not overlap", () => {
  const historyAi = {
    id: "history-ai",
    type: "ai",
    content: "persisted",
  } as Message;
  const liveHuman = {
    id: "live-human",
    type: "human",
    content: "live",
  } as Message;

  expect(mergeMessages([historyAi], [liveHuman], [])).toEqual([
    historyAi,
    liveHuman,
  ]);
});

/**
 * 覆盖“mergeMessages appends a trailing live-only segment after newer canonical rows”这一可观察行为，防止相关边界在重构后回归。

 */

test("mergeMessages appends a trailing live-only segment after newer canonical rows", () => {
  /**
   * 封装局部测试或脚本流程中的具名操作，避免调用处重复实现 message 约定的逻辑。
   */
  const message = (id: string) =>
    ({ id, type: "human", content: id }) as Message;
  const [a, b, c, d, y] = ["a", "b", "c", "d", "y"].map(message) as [
    Message,
    Message,
    Message,
    Message,
    Message,
  ];

  expect(mergeMessages([a, b, c, d], [b, y], [])).toEqual([a, b, c, d, y]);
});

/**
 * 覆盖“mergeMessages keeps live-only messages between shared anchors in place”这一可观察行为，防止相关边界在重构后回归。

 */

test("mergeMessages keeps live-only messages between shared anchors in place", () => {
  /**
   * 封装局部测试或脚本流程中的具名操作，避免调用处重复实现 message 约定的逻辑。
   */
  const message = (id: string) =>
    ({ id, type: "human", content: id }) as Message;
  const [a, b, c, d, x, y] = ["a", "b", "c", "d", "x", "y"].map(message) as [
    Message,
    Message,
    Message,
    Message,
    Message,
    Message,
  ];

  expect(mergeMessages([a, b, c, d], [b, x, d, y], [])).toEqual([
    a,
    b,
    c,
    x,
    d,
    y,
  ]);
});

/**
 * 覆盖“mergeMessages deduplicates tool messages by tool_call_id”这一可观察行为，防止相关边界在重构后回归。

 */

test("mergeMessages deduplicates tool messages by tool_call_id", () => {
  const oldTool = {
    id: "tool-message-old",
    type: "tool",
    tool_call_id: "call-1",
    content: "old",
  } as Message;
  const liveTool = {
    id: "tool-message-live",
    type: "tool",
    tool_call_id: "call-1",
    content: "live",
  } as Message;

  expect(mergeMessages([oldTool], [liveTool], [])).toEqual([liveTool]);
});

/**
 * 覆盖“mergeMessages keeps a visible history message when a hidden live message reuses its id”这一可观察行为，防止相关边界在重构后回归。

 */

test("mergeMessages keeps a visible history message when a hidden live message reuses its id", () => {
  const historyHuman = {
    id: "human-1",
    type: "human",
    content: "visible user prompt",
  } as Message;
  const hiddenReminder = {
    id: "human-1",
    type: "human",
    content: "<system-reminder>hidden</system-reminder>",
    additional_kwargs: { hide_from_ui: true },
  } as Message;
  const liveAi = {
    id: "ai-1",
    type: "ai",
    content: "live answer",
  } as Message;

  expect(mergeMessages([historyHuman], [hiddenReminder, liveAi], [])).toEqual([
    historyHuman,
    liveAi,
  ]);
});

/**
 * 覆盖“mergeMessages lets a visible live message replace overlapping hidden history”这一可观察行为，防止相关边界在重构后回归。

 */

test("mergeMessages lets a visible live message replace overlapping hidden history", () => {
  const hiddenHistoryHuman = {
    id: "human-1",
    type: "human",
    content: "<system-reminder>hidden</system-reminder>",
    additional_kwargs: { hide_from_ui: true },
  } as Message;
  const liveHuman = {
    id: "human-1",
    type: "human",
    content: "visible user prompt",
  } as Message;

  expect(mergeMessages([hiddenHistoryHuman], [liveHuman], [])).toEqual([
    liveHuman,
  ]);
});

/**
 * 覆盖“getSummarizationMiddlewareMessages matches DeerFlow summarization update keys”这一可观察行为，防止相关边界在重构后回归。

 */

test("getSummarizationMiddlewareMessages matches DeerFlow summarization update keys", () => {
  const removeAll = {
    id: "__remove_all__",
    type: "remove",
    content: "",
  } as Message;
  const summary = {
    id: "summary-1",
    type: "human",
    name: "summary",
    content: "summary",
  } as Message;

  expect(
    getSummarizationMiddlewareMessages({
      "DeerFlowSummarizationMiddleware.before_model": {
        messages: [removeAll, summary],
      },
    }),
  ).toEqual([removeAll, summary]);
});

/**
 * 覆盖“getSummarizationMiddlewareMessages matches base LangChain summarization update keys”这一可观察行为，防止相关边界在重构后回归。

 */

test("getSummarizationMiddlewareMessages matches base LangChain summarization update keys", () => {
  const summary = {
    id: "summary-1",
    type: "human",
    name: "summary",
    content: "summary",
  } as Message;

  expect(
    getSummarizationMiddlewareMessages({
      "SummarizationMiddleware.before_model": {
        messages: [summary],
      },
    }),
  ).toEqual([summary]);
});

/**
 * 覆盖“getSummarizationMiddlewareMessages ignores unrelated suffix-sharing update keys”这一可观察行为，防止相关边界在重构后回归。

 */

test("getSummarizationMiddlewareMessages ignores unrelated suffix-sharing update keys", () => {
  const summary = {
    id: "summary-1",
    type: "human",
    name: "summary",
    content: "summary",
  } as Message;

  expect(
    getSummarizationMiddlewareMessages({
      "OtherSummarizationMiddleware.before_model": {
        messages: [summary],
      },
    }),
  ).toBeUndefined();
});

/**
 * 覆盖“getVisibleOptimisticMessages hides optimistic user input after server human arrives”这一可观察行为，防止相关边界在重构后回归。

 */

test("getVisibleOptimisticMessages hides optimistic user input after server human arrives", () => {
  const optimisticHuman = {
    id: "opt-human-1",
    type: "human",
    content: "hello",
  } as Message;

  expect(getVisibleOptimisticMessages([optimisticHuman], 0, 1)).toEqual([]);
});

/**
 * 覆盖“mergeMessages shows server human instead of optimistic duplicate after first response”这一可观察行为，防止相关边界在重构后回归。

 */

test("mergeMessages shows server human instead of optimistic duplicate after first response", () => {
  const serverHuman = {
    id: "server-human-1",
    type: "human",
    content: "hello",
  } as Message;
  const optimisticHuman = {
    id: "opt-human-1",
    type: "human",
    content: "hello",
  } as Message;
  const visibleOptimistic = getVisibleOptimisticMessages(
    [optimisticHuman],
    0,
    1,
  );

  expect(mergeMessages([], [serverHuman], visibleOptimistic)).toEqual([
    serverHuman,
  ]);
});

/**
 * 覆盖“getVisibleOptimisticMessages keeps optimistic user input until server human arrives”这一可观察行为，防止相关边界在重构后回归。

 */

test("getVisibleOptimisticMessages keeps optimistic user input until server human arrives", () => {
  const optimisticHuman = {
    id: "opt-human-1",
    type: "human",
    content: "hello",
  } as Message;

  expect(getVisibleOptimisticMessages([optimisticHuman], 0, 0)).toEqual([
    optimisticHuman,
  ]);
});

/**
 * 覆盖“getVisibleOptimisticMessages keeps non-human optimistic status messages”这一可观察行为，防止相关边界在重构后回归。

 */

test("getVisibleOptimisticMessages keeps non-human optimistic status messages", () => {
  const optimisticAi = {
    id: "opt-ai-1",
    type: "ai",
    content: "Uploading files...",
  } as Message;

  expect(getVisibleOptimisticMessages([optimisticAi], 0, 1)).toEqual([
    optimisticAi,
  ]);
});

/**
 * 覆盖“getVisibleOptimisticMessages hides the upload optimistic pair after server human arrives”这一可观察行为，防止相关边界在重构后回归。

 */

test("getVisibleOptimisticMessages hides the upload optimistic pair after server human arrives", () => {
  const optimisticHuman = {
    id: "opt-human-1",
    type: "human",
    content: "upload this",
  } as Message;
  const optimisticUploadingAi = {
    id: "opt-ai-uploading",
    type: "ai",
    content: "Uploading files...",
  } as Message;

  expect(
    getVisibleOptimisticMessages(
      [optimisticHuman, optimisticUploadingAi],
      0,
      1,
    ),
  ).toEqual([]);
});

/**
 * 覆盖“getVisibleOptimisticMessages hides optimistic user input after later server turns”这一可观察行为，防止相关边界在重构后回归。

 */

test("getVisibleOptimisticMessages hides optimistic user input after later server turns", () => {
  const optimisticHuman = {
    id: "opt-human-2",
    type: "human",
    content: "follow up",
  } as Message;

  expect(getVisibleOptimisticMessages([optimisticHuman], 3, 4)).toEqual([]);
  expect(getVisibleOptimisticMessages([optimisticHuman], 3, 3)).toEqual([
    optimisticHuman,
  ]);
});

/**
 * 覆盖“buildThreadMessagesPageUrl encodes the thread and backward cursor”这一可观察行为，防止相关边界在重构后回归。

 */

test("buildThreadMessagesPageUrl encodes the thread and backward cursor", () => {
  expect(
    buildThreadMessagesPageUrl(
      "https://api.example.test/",
      "thread/with space",
      18,
    ),
  ).toBe(
    "https://api.example.test/api/threads/thread%2Fwith%20space/messages/page?before_seq=18",
  );
});

/**
 * 覆盖“buildThreadMessagesPageUrl omits before_seq for the latest page”这一可观察行为，防止相关边界在重构后回归。

 */

test("buildThreadMessagesPageUrl omits before_seq for the latest page", () => {
  expect(
    buildThreadMessagesPageUrl("https://api.example.test", "thread-1"),
  ).toBe("https://api.example.test/api/threads/thread-1/messages/page");
});

/**
 * 覆盖“buildThreadMessagesPageUrl returns a relative URL behind nginx”这一可观察行为，防止相关边界在重构后回归。

 */

test("buildThreadMessagesPageUrl returns a relative URL behind nginx", () => {
  expect(buildThreadMessagesPageUrl("", "thread-1", 42)).toBe(
    "/api/threads/thread-1/messages/page?before_seq=42",
  );
});

/**
 * 覆盖“flattenThreadHistoryPages prepends backward pages in global seq order”这一可观察行为，防止相关边界在重构后回归。

 */

test("flattenThreadHistoryPages prepends backward pages in global seq order", () => {
  expect(
    flattenThreadHistoryPages([
      {
        data: [runMessage(5), runMessage(6)],
        has_more: true,
        next_before_seq: 5,
      },
      {
        data: [runMessage(3), runMessage(4)],
        has_more: true,
        next_before_seq: 3,
      },
      {
        data: [runMessage(1), runMessage(2)],
        has_more: false,
        next_before_seq: null,
      },
    ]).map((message) => message.seq),
  ).toEqual([1, 2, 3, 4, 5, 6]);
});

/**
 * 覆盖“flattenThreadHistoryPages retains backward pages when the latest page refreshes”这一可观察行为，防止相关边界在重构后回归。

 */

test("flattenThreadHistoryPages retains backward pages when the latest page refreshes", () => {
  const olderPage = {
    data: [runMessage(1), runMessage(2)],
    has_more: false,
    next_before_seq: null,
  };

  expect(
    flattenThreadHistoryPages([
      {
        data: [runMessage(3), runMessage(4), runMessage(5)],
        has_more: true,
        next_before_seq: 3,
      },
      olderPage,
    ]).map((message) => message.seq),
  ).toEqual([1, 2, 3, 4, 5]);
});

/**
 * 覆盖“infinite history refetch recalculates older-page cursors from the refreshed newest page”这一可观察行为，防止相关边界在重构后回归。

 */

test("infinite history refetch recalculates older-page cursors from the refreshed newest page", async () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const queryKey = ["thread-messages", "thread-1"] as const;
  const requestedCursors: Array<number | null> = [];
  let availableSeqs = Array.from({ length: 9 }, (_, index) => index + 1);

  const observer = new InfiniteQueryObserver(queryClient, {
    queryKey,
    initialPageParam: null as number | null,
    queryFn: ({ pageParam }): ThreadMessagesPageResponse => {
      requestedCursors.push(pageParam);
      const eligible = availableSeqs.filter(
        (seq) => pageParam === null || seq < pageParam,
      );
      const pageSeqs = eligible.slice(-3);
      return {
        data: pageSeqs.map(runMessage),
        has_more: eligible.length > pageSeqs.length,
        next_before_seq:
          eligible.length > pageSeqs.length ? (pageSeqs[0] ?? null) : null,
      };
    },
    getNextPageParam: getThreadHistoryNextPageParam,
  });
  const unsubscribe = observer.subscribe(() => undefined);

  await observer.refetch();
  await observer.fetchNextPage();
  expect(requestedCursors).toEqual([null, 7]);

  availableSeqs = Array.from({ length: 12 }, (_, index) => index + 1);
  requestedCursors.length = 0;
  await queryClient.invalidateQueries({ queryKey });

  expect(requestedCursors).toEqual([null, 10]);
  expect(
    observer
      .getCurrentResult()
      .data?.pages.map((page) => page.data.map((message) => message.seq)),
  ).toEqual([
    [10, 11, 12],
    [7, 8, 9],
  ]);
  expect(observer.getCurrentResult().data?.pageParams).toEqual([null, 10]);

  unsubscribe();
  queryClient.clear();
});

/**
 * 覆盖“infinite history stops and warns when has_more has no cursor”这一可观察行为，防止相关边界在重构后回归。

 */

test("infinite history stops and warns when has_more has no cursor", async () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const requestedCursors: Array<number | null> = [];
  const warnSpy = rs.spyOn(console, "warn").mockImplementation(() => ({}));
  const observer = new InfiniteQueryObserver(queryClient, {
    queryKey: ["thread-messages", "invalid-cursor"],
    initialPageParam: null as number | null,
    queryFn: ({ pageParam }): ThreadMessagesPageResponse => {
      requestedCursors.push(pageParam);
      return { data: [], has_more: true, next_before_seq: null };
    },
    getNextPageParam: getThreadHistoryNextPageParam,
  });
  const unsubscribe = observer.subscribe(() => undefined);

  try {
    await observer.refetch();
    await observer.fetchNextPage();

    expect(requestedCursors).toEqual([null]);
    expect(observer.getCurrentResult().hasNextPage).toBe(false);
    expect(warnSpy).toHaveBeenCalledWith(
      "Thread history returned has_more without next_before_seq; pagination cannot continue.",
    );
  } finally {
    unsubscribe();
    warnSpy.mockRestore();
    queryClient.clear();
  }
});

/**
 * 覆盖“removeSetItems removes pending superseded ids after submit failure”这一可观察行为，防止相关边界在重构后回归。

 */

test("removeSetItems removes pending superseded ids after submit failure", () => {
  expect(
    removeSetItems(new Set(["run-old", "run-other"]), ["run-old"]),
  ).toEqual(new Set(["run-other"]));
});

/**
 * 覆盖“buildVisibleHistoryMessages filters superseded runs but keeps regenerated run”这一可观察行为，防止相关边界在重构后回归。

 */

test("buildVisibleHistoryMessages filters superseded runs but keeps regenerated run", () => {
  const oldHuman = {
    id: "human-1",
    type: "human",
    content: "question",
  } as Message;
  const oldAi = {
    id: "ai-old",
    type: "ai",
    content: "old answer",
  } as Message;
  const newHuman = {
    id: "human-1",
    type: "human",
    content: "question",
  } as Message;
  const newAi = {
    id: "ai-new",
    type: "ai",
    content: "new answer",
  } as Message;
  const rows: RunMessage[] = [
    {
      run_id: "run-old",
      content: oldHuman,
      metadata: { caller: "lead_agent" },
      created_at: "2026-06-18T00:00:00Z",
    },
    {
      run_id: "run-old",
      content: oldAi,
      metadata: { caller: "lead_agent" },
      created_at: "2026-06-18T00:00:01Z",
    },
    {
      run_id: "run-new",
      content: newHuman,
      metadata: { caller: "lead_agent" },
      created_at: "2026-06-18T00:00:02Z",
    },
    {
      run_id: "run-new",
      content: newAi,
      metadata: { caller: "lead_agent" },
      created_at: "2026-06-18T00:00:03Z",
    },
  ];

  // run_id 被携带到每条内容消息上（#3779），使历史子任务卡片在展开时可获取其
  // 持久化步骤历史。
  expect(buildVisibleHistoryMessages(rows, new Set(["run-old"]))).toEqual([
    { ...newHuman, run_id: "run-new" },
    { ...newAi, run_id: "run-new" },
  ]);
});

/**
 * 覆盖“buildVisibleHistoryMessages attaches run_id to each content message (#3779)”这一可观察行为，防止相关边界在重构后回归。

 */

test("buildVisibleHistoryMessages attaches run_id to each content message (#3779)", () => {
  const rows: RunMessage[] = [
    {
      run_id: "run-1",
      content: { id: "ai-1", type: "ai", content: "answer" } as Message,
      metadata: { caller: "lead_agent" },
      created_at: "2026-06-26T00:00:00Z",
    },
  ];

  const result = buildVisibleHistoryMessages(rows, new Set());

  expect((result[0] as { run_id?: string }).run_id).toBe("run-1");
});

// #3825 的回归覆盖：上下文摘要后，后端发出 RemoveMessage(ALL) + summary + retained，
// onUpdateEvent 会将被移除消息挽救到当前流瞬态桥接层。该桥接层仅填补日志刷新/重新获取的
// 间隙，绝不修改规范历史页面。

const summarizationHuman1 = {
  id: "human-1",
  type: "human",
  content: "round 1 question",
} as Message;
const summarizationAi1 = {
  id: "ai-1",
  type: "ai",
  content: "round 1 answer",
} as Message;
const summarizationHuman2 = {
  id: "human-2",
  type: "human",
  content: "round 2 question",
} as Message;
const summarizationAi2 = {
  id: "ai-2",
  type: "ai",
  content: "round 2 answer (retained)",
} as Message;
const summarizationMovedMessages = [
  summarizationHuman1,
  summarizationAi1,
  summarizationHuman2,
];

/**
 * 覆盖“resolveTransientHistoryBridge keeps rescued messages while history state is stale”这一可观察行为，防止相关边界在重构后回归。

 */

test("resolveTransientHistoryBridge keeps rescued messages while history state is stale", () => {
  const staleHistory: Message[] = [];

  expect(
    resolveTransientHistoryBridge(staleHistory, summarizationMovedMessages),
  ).toEqual(summarizationMovedMessages);
});

/**
 * 覆盖“resolveTransientHistoryBridge appends rescued messages after canonical history”这一可观察行为，防止相关边界在重构后回归。

 */

test("resolveTransientHistoryBridge appends rescued messages after canonical history", () => {
  const olderLoadedHuman = {
    id: "older-human",
    type: "human",
    content: "older loaded turn",
  } as Message;

  expect(
    resolveTransientHistoryBridge(
      [olderLoadedHuman],
      summarizationMovedMessages,
    ),
  ).toEqual([olderLoadedHuman, ...summarizationMovedMessages]);
});

/**
 * 覆盖“resolveTransientHistoryBridge does not collapse an unloaded gap before its first canonical anchor”这一可观察行为，防止相关边界在重构后回归。

 */

test("resolveTransientHistoryBridge does not collapse an unloaded gap before its first canonical anchor", () => {
  // 来自线程 4e81444d-c6ce-471e-93fd-b6ddb18dc938 的真实回归形状：默认历史页面从
  // event seq=35 开始，而澄清对话位于 seq=2..14。上下文压缩同时捕获旧回合和一条与
  // 规范页面重叠的较晚消息。旧回合必须保持抑制，直至其规范页面加载；否则未加载的
  // seq=15..34 间隙会在页面锚点前被视觉上折叠。
  const clarificationRequest = {
    id: "clarification-request",
    type: "ai",
    content: "Which PDF should I create?",
  } as Message;
  const clarificationCard = {
    id: "clarification-card",
    tool_call_id: "clarification-call",
    type: "tool",
    content: "Create a new algorithm PDF",
  } as Message;
  const clarificationAnswer = {
    id: "clarification-answer",
    type: "human",
    content: "Create a new algorithm PDF",
  } as Message;
  const directionQuestion = {
    id: "direction-question",
    type: "ai",
    content: "Which topic?",
  } as Message;
  const directionAnswer = {
    id: "direction-answer",
    type: "human",
    content: "Binary trees",
  } as Message;
  const pageAnchor = {
    id: "event-seq-35",
    type: "tool",
    tool_call_id: "event-seq-35-call",
    content: "first message on the latest history page",
  } as Message;
  const latestAnswer = {
    id: "event-seq-88",
    type: "ai",
    content: "latest answer",
  } as Message;
  const captured = [
    summarizationHuman1,
    clarificationRequest,
    clarificationCard,
    clarificationAnswer,
    directionQuestion,
    directionAnswer,
    pageAnchor,
  ];
  const canonical = [pageAnchor, latestAnswer];
  const missingAfterCanonicalRefetch = pruneConfirmedTransientMessages(
    captured,
    canonical,
  );
  const bridgeOrder = mergeTransientHistoryBridgeOrder([], captured);

  expect(
    resolveTransientHistoryBridge(
      canonical,
      missingAfterCanonicalRefetch,
      bridgeOrder,
    ).map((message) => message.id),
  ).toEqual(["event-seq-35", "event-seq-88"]);
});

/**
 * 覆盖“resolveTransientHistoryBridge does not duplicate once canonical history catches up”这一可观察行为，防止相关边界在重构后回归。

 */

test("resolveTransientHistoryBridge does not duplicate once canonical history catches up", () => {
  expect(
    resolveTransientHistoryBridge(
      summarizationMovedMessages,
      summarizationMovedMessages,
    ),
  ).toEqual(summarizationMovedMessages);
});

/**
 * 覆盖“resolveTransientHistoryBridge returns history unchanged when the bridge is empty”这一可观察行为，防止相关边界在重构后回归。

 */

test("resolveTransientHistoryBridge returns history unchanged when the bridge is empty", () => {
  const history = [summarizationHuman1, summarizationAi1];
  expect(resolveTransientHistoryBridge(history, [])).toBe(history);
});

/**
 * 覆盖“resolveThreadTransientHistoryBridge never leaks a bridge across threads”这一可观察行为，防止相关边界在重构后回归。

 */

test("resolveThreadTransientHistoryBridge never leaks a bridge across threads", () => {
  const canonical = [
    { id: "older-human", type: "human", content: "older" } as Message,
  ];
  expect(
    resolveThreadTransientHistoryBridge(
      canonical,
      summarizationMovedMessages,
      "thread-a",
      "thread-b",
    ),
  ).toBe(canonical);
  expect(
    resolveThreadTransientHistoryBridge(
      canonical,
      summarizationMovedMessages,
      null,
      null,
    ),
  ).toBe(canonical);
  expect(
    resolveThreadTransientHistoryBridge(
      canonical,
      summarizationMovedMessages,
      "thread-a",
      "thread-a",
    ),
  ).toEqual([canonical[0], ...summarizationMovedMessages]);
});

/**
 * 覆盖“mergeTransientHistoryBridge preserves chronology across repeated compression”这一可观察行为，防止相关边界在重构后回归。

 */

test("mergeTransientHistoryBridge preserves chronology across repeated compression", () => {
  const human3 = {
    id: "human-3",
    type: "human",
    content: "round 3 question",
  } as Message;
  const firstBridge = mergeTransientHistoryBridge(
    [],
    [summarizationHuman1, summarizationAi1],
  );
  const secondBridge = mergeTransientHistoryBridge(firstBridge, [
    summarizationAi1,
    summarizationHuman2,
    human3,
  ]);

  expect(secondBridge.map((message) => message.id)).toEqual([
    "human-1",
    "ai-1",
    "human-2",
    "human-3",
  ]);
});

/**
 * 覆盖“mergeTransientHistoryBridge does not move a protected input recaptured by later compression”这一可观察行为，防止相关边界在重构后回归。

 */

test("mergeTransientHistoryBridge does not move a protected input recaptured by later compression", () => {
  const protectedInput = {
    id: "protected-input",
    type: "human",
    content: "写一个算法PDF",
  } as Message;
  const clarification = {
    id: "clarification",
    type: "ai",
    content: "Which kind?",
  } as Message;
  const laterTail = {
    id: "later-tail",
    type: "ai",
    content: "Working on the PDF",
  } as Message;

  const firstBridge = mergeTransientHistoryBridge(
    [],
    [protectedInput, clarification],
  );
  const secondBridge = mergeTransientHistoryBridge(firstBridge, [
    { ...protectedInput, content: [{ type: "text", text: "写一个算法PDF" }] },
    laterTail,
  ]);

  expect(secondBridge.map((message) => message.id)).toEqual([
    "protected-input",
    "clarification",
    "later-tail",
  ]);
  expect(secondBridge[0]?.content).toEqual([
    { type: "text", text: "写一个算法PDF" },
  ]);
});

/**
 * 覆盖“mergeTransientHistoryBridgeOrder retains confirmed overlap as a non-rendering anchor”这一可观察行为，防止相关边界在重构后回归。

 */

test("mergeTransientHistoryBridgeOrder retains confirmed overlap as a non-rendering anchor", () => {
  const firstOrder = mergeTransientHistoryBridgeOrder(
    [],
    [summarizationHuman1, summarizationAi1, summarizationHuman2],
  );
  const secondOrder = mergeTransientHistoryBridgeOrder(firstOrder, [
    summarizationHuman2,
    summarizationAi2,
  ]);

  expect(secondOrder).toEqual([
    "message:human-1",
    "message:ai-1",
    "message:human-2",
    "message:ai-2",
  ]);
});

/**
 * 覆盖“mergeTransientHistoryBridgeOrder keeps a recaptured protected prefix in place”这一可观察行为，防止相关边界在重构后回归。

 */

test("mergeTransientHistoryBridgeOrder keeps a recaptured protected prefix in place", () => {
  const protectedInput = {
    id: "protected-input",
    type: "human",
    content: "first",
  } as Message;
  const oldTail = {
    id: "old-tail",
    type: "ai",
    content: "old",
  } as Message;
  const newTail = {
    id: "new-tail",
    type: "ai",
    content: "new",
  } as Message;

  const firstOrder = mergeTransientHistoryBridgeOrder(
    [],
    [protectedInput, oldTail],
  );
  const secondOrder = mergeTransientHistoryBridgeOrder(firstOrder, [
    protectedInput,
    newTail,
  ]);

  expect(secondOrder).toEqual([
    "message:protected-input",
    "message:old-tail",
    "message:new-tail",
  ]);
});

/**
 * 覆盖“merge keeps the full conversation across summarization even when visibleHistory lags (regression for #3825)”这一可观察行为，防止相关边界在重构后回归。

 */

test("merge keeps the full conversation across summarization even when visibleHistory lags (regression for #3825)", () => {
  // RemoveMessage(ALL) 后，活动线程仅携带隐藏摘要（name === "summary"）和保留的
  // 最新回答。
  const hiddenSummary = {
    id: "summary-1",
    type: "human",
    name: "summary",
    content: "conversation summary",
  } as Message;
  const postSummaryThread = [hiddenSummary, summarizationAi2];

  // 错误渲染：visibleHistory 仍为空，因此若没有缓冲区，被挽救的第 1/2 轮消息不在
  // 任一合并输入中，因而丢失。
  const effectiveHistory = resolveTransientHistoryBridge(
    [],
    summarizationMovedMessages,
  );
  const merged = mergeMessages(effectiveHistory, postSummaryThread, []);

  expect(merged.map((m) => m.id)).toEqual([
    "human-1",
    "ai-1",
    "human-2",
    "summary-1",
    "ai-2",
  ]);
});

/**
 * 覆盖“pruneConfirmedTransientMessages drops canonical identities but keeps the rest”这一可观察行为，防止相关边界在重构后回归。

 */

test("pruneConfirmedTransientMessages drops canonical identities but keeps the rest", () => {
  // 历史仅追赶上前两条被挽救的消息。
  expect(
    pruneConfirmedTransientMessages(summarizationMovedMessages, [
      summarizationHuman1,
      summarizationAi1,
    ]),
  ).toEqual([summarizationHuman2]);
});

/**
 * 覆盖“pruneConfirmedTransientMessages keeps entries while canonical history is stale”这一可观察行为，防止相关边界在重构后回归。

 */

test("pruneConfirmedTransientMessages keeps entries while canonical history is stale", () => {
  expect(
    pruneConfirmedTransientMessages(summarizationMovedMessages, []),
  ).toEqual(summarizationMovedMessages);
});

/**
 * 覆盖“resolveTransientHistoryBridge prefers canonical copy over stale transient copy”这一可观察行为，防止相关边界在重构后回归。

 */

test("resolveTransientHistoryBridge prefers canonical copy over stale transient copy", () => {
  // 身份相同，但缓冲副本是较旧快照。活动历史副本（例如最终回答）必须优先——缓冲区
  // 仅填补间隙，绝不能覆盖历史已展示的消息。
  const staleBuffered = {
    id: "ai-1",
    type: "ai",
    content: "streaming partial",
  } as Message;
  const liveFinal = {
    id: "ai-1",
    type: "ai",
    content: "finalized answer",
  } as Message;

  expect(resolveTransientHistoryBridge([liveFinal], [staleBuffered])).toEqual([
    liveFinal,
  ]);
});

/**
 * 覆盖“computeSummarizationTransientMessages captures live turns dropped before the retained boundary”这一可观察行为，防止相关边界在重构后回归。

 */

test("computeSummarizationTransientMessages captures live turns dropped before the retained boundary", () => {
  const removeAll = {
    id: "__remove_all__",
    type: "remove",
    content: "",
  } as Message;
  const hiddenSummary = {
    id: "summary-1",
    type: "human",
    name: "summary",
    content: "conversation summary",
  } as Message;
  const liveThreadBeforeSummary = [
    summarizationHuman1,
    summarizationAi1,
    summarizationHuman2,
    summarizationAi2,
  ];
  // 摘要会发出 RemoveMessage(ALL) + 隐藏摘要 + 保留回答。
  const summarizationMessages = [removeAll, hiddenSummary, summarizationAi2];

  expect(
    computeSummarizationTransientMessages(
      liveThreadBeforeSummary,
      summarizationMessages,
      new Set([hiddenSummary.id!]),
    ),
  ).toEqual([summarizationHuman1, summarizationAi1, summarizationHuman2]);
});

/**
 * 覆盖“computeSummarizationTransientMessages excludes already-summarized control messages”这一可观察行为，防止相关边界在重构后回归。

 */

test("computeSummarizationTransientMessages excludes already-summarized control messages", () => {
  const priorSummary = {
    id: "summary-0",
    type: "human",
    name: "summary",
    content: "earlier summary",
  } as Message;
  const liveThreadBeforeSummary = [
    priorSummary,
    summarizationHuman1,
    summarizationAi1,
    summarizationAi2,
  ];
  const summarizationMessages = [
    { id: "__remove_all__", type: "remove", content: "" } as Message,
    {
      id: "summary-1",
      type: "human",
      name: "summary",
      content: "new summary",
    } as Message,
    summarizationAi2,
  ];

  // priorSummary 位于已摘要集合中，因此不得进入桥接层。
  expect(
    computeSummarizationTransientMessages(
      liveThreadBeforeSummary,
      summarizationMessages,
      new Set([priorSummary.id!, "summary-1"]),
    ),
  ).toEqual([summarizationHuman1, summarizationAi1]);
});

/**
 * 覆盖“full summarization rescue pipeline keeps the conversation when history state lags (regression for #3825)”这一可观察行为，防止相关边界在重构后回归。

 */

test("full summarization rescue pipeline keeps the conversation when history state lags (regression for #3825)", () => {
  // 演练 hook 运行的完整挽救算法：推导被移动的消息、将其缓冲，然后在规范运行事件页
  // 仍处于过期（为空）状态时，与摘要后的线程合并。
  const removeAll = {
    id: "__remove_all__",
    type: "remove",
    content: "",
  } as Message;
  const hiddenSummary = {
    id: "summary-1",
    type: "human",
    name: "summary",
    content: "conversation summary",
  } as Message;
  const liveThreadBeforeSummary = [
    summarizationHuman1,
    summarizationAi1,
    summarizationHuman2,
    summarizationAi2,
  ];
  const summarizationMessages = [removeAll, hiddenSummary, summarizationAi2];

  const moved = computeSummarizationTransientMessages(
    liveThreadBeforeSummary,
    summarizationMessages,
    new Set([hiddenSummary.id!]),
  );
  const staleHistory: Message[] = [];
  const postSummaryThread = [hiddenSummary, summarizationAi2];

  const merged = mergeMessages(
    resolveTransientHistoryBridge(staleHistory, moved),
    postSummaryThread,
    [],
  );

  expect(merged.map((m) => m.id)).toEqual([
    "human-1",
    "ai-1",
    "human-2",
    "summary-1",
    "ai-2",
  ]);
});

/**
 * 覆盖“refresh reconstructs the same 1-to-6 order from run events without a bridge”这一可观察行为，防止相关边界在重构后回归。

 */

test("refresh reconstructs the same 1-to-6 order from run events without a bridge", () => {
  const canonical = Array.from({ length: 6 }, (_, index) => ({
    id: `message-${index + 1}`,
    type: index % 2 === 0 ? "human" : "ai",
    content: String(index + 1),
  })) as Message[];
  const checkpointTail = canonical.slice(4);

  expect(
    mergeMessages(canonical, checkpointTail, []).map(
      (message) => message.content,
    ),
  ).toEqual(["1", "2", "3", "4", "5", "6"]);
});
