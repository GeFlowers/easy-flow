import type { AIMessage, Message, Run } from "@langchain/langgraph-sdk";
import type { ThreadsClient } from "@langchain/langgraph-sdk/client";
import { useStream } from "@langchain/langgraph-sdk/react";
import {
  type QueryClient,
  type InfiniteData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";

import { getAPIClient } from "../api";
import { fetch } from "../api/fetcher";
import { getBackendBaseURL } from "../config";
import { useI18n } from "../i18n/hooks";
import { isHiddenFromUIMessage } from "../messages/utils";
import type { FileInMessage } from "../messages/utils";
import type { LocalSettings } from "../settings";
import { isSidecarThread, SIDECAR_METADATA_KEY } from "../sidecar/thread";
import { useUpdateSubtask } from "../tasks/context";
import { taskEventToSubtaskUpdate } from "../tasks/lifecycle";
import { messageToStep } from "../tasks/steps";
import type { UploadedFileInfo } from "../uploads";
import { promptInputFilePartToFile, uploadFiles } from "../uploads";

import { branchThreadFromTurn, fetchThreadTokenUsage } from "./api";
import {
  buildThreadsSearchQueryOptions,
  DEFAULT_THREAD_SEARCH_PARAMS,
  filterThreadSearchResults,
  type ThreadSearchParams,
} from "./thread-search-query";
import { threadTokenUsageQueryKey } from "./token-usage";
import type {
  AgentThread,
  AgentThreadState,
  RunMessage,
  ThreadTokenUsageResponse,
} from "./types";

/** 工具执行结束时通知监听器的事件数据。 */
export type ToolEndEvent = {
  name: string;
  data: unknown;
};

/** 配置线程流 Hook 的运行上下文、监听器与提交行为。 */
export type ThreadStreamOptions = {
  threadId?: string | null | undefined;
  displayThreadId?: string | null | undefined;
  context: LocalSettings["context"];
  onSend?: (threadId: string) => void;
  onStart?: (threadId: string, runId: string) => void;
  onFinish?: (state: AgentThreadState) => void;
  onToolEnd?: (event: ToolEndEvent) => void;
};

type SendMessageOptions = {
  additionalKwargs?: Record<string, unknown>;
  additionalInputMessages?: Message[];
  /**
   * 仅在发送通过进行中保护并实际派发时调用一次。提前返回路径绝不触发，因此调用方可安全执行一次性清理
   * （例如清空引用内容），且并发发送被丢弃时不会丢失状态。
   */
  onSent?: () => void;
};

type ThreadDeleteClient = {
  threads: {
    delete: (threadId: string) => Promise<unknown>;
    search: (query: Record<string, unknown>) => Promise<AgentThread[]>;
  };
};

type ThreadSidecarSearchClient = {
  threads: {
    search: (query: Record<string, unknown>) => Promise<AgentThread[]>;
  };
};

type RegeneratePrepareResponse = {
  input: Partial<AgentThreadState>;
  checkpoint: {
    checkpoint_ns: string;
    checkpoint_id: string;
    checkpoint_map: Record<string, unknown> | null;
  };
  metadata: Record<string, unknown>;
  target_run_id: string;
};

/** 构造发送到线程运行接口的用户消息列表。 */
export function buildThreadSubmitMessages({
  text,
  additionalKwargs,
  additionalInputMessages = [],
  filesForSubmit = [],
}: {
  text: string;
  additionalKwargs?: Record<string, unknown>;
  additionalInputMessages?: Message[];
  filesForSubmit?: FileInMessage[];
}): Message[] {
  return [
    ...additionalInputMessages,
    {
      type: "human",
      content: [
        {
          type: "text",
          text,
        },
      ],
      additional_kwargs: {
        ...additionalKwargs,
        ...(filesForSubmit.length > 0 ? { files: filesForSubmit } : {}),
      },
    } as Message,
  ];
}

const EMPTY_THREAD_VALUES: AgentThreadState = {
  title: "",
  messages: [],
  artifacts: [],
  todos: [],
};

/** 判断可选字符串是否为非空字符串。 */
function isNonEmptyString(value: string | undefined): value is string {
  return typeof value === "string" && value.length > 0;
}

const SUMMARIZATION_MIDDLEWARE_UPDATE_KEYS = new Set([
  "SummarizationMiddleware.before_model",
  "DeerFlowSummarizationMiddleware.before_model",
]);

/** 提取可跨历史、实时流和乐观消息稳定匹配的消息标识。 */
function messageIdentity(message: Message): string | undefined {
  if (
    "tool_call_id" in message &&
    typeof message.tool_call_id === "string" &&
    message.tool_call_id.length > 0
  ) {
    return `tool:${message.tool_call_id}`;
  }
  if (typeof message.id === "string" && message.id.length > 0) {
    return `message:${message.id}`;
  }
  return undefined;
}

/** 按消息标识去重，并优先保留适合界面展示的最新副本。 */
function dedupeMessagesByIdentity(messages: Message[]): Message[] {
  const lastIndexByIdentity = new Map<string, number>();
  const lastVisibleIndexByIdentity = new Map<string, number>();

  // 这是 UI 展示去重规则，不是通用 LangChain 消息流契约。与可见消息共享标识的隐藏消息在此合并视图中
  // 视为控制消息；携带独立追踪／任务语义的隐藏消息应使用不同 id 或自定义流／状态通道，不能依赖消息去重保留。
  const preservedTurnDurations = new Map<string, number>();
  messages.forEach((message, index) => {
    const identity = messageIdentity(message);
    if (identity) {
      lastIndexByIdentity.set(identity, index);
      if (!isHiddenFromUIMessage(message)) {
        lastVisibleIndexByIdentity.set(identity, index);
      }
      if (message.additional_kwargs?.turn_duration !== undefined) {
        preservedTurnDurations.set(
          identity,
          message.additional_kwargs.turn_duration as number,
        );
      }
    }
  });

  return messages
    .filter((message, index) => {
      const identity = messageIdentity(message);
      if (!identity) {
        return true;
      }
      const visibleIndex = lastVisibleIndexByIdentity.get(identity);
      if (visibleIndex !== undefined) {
        return visibleIndex === index;
      }
      return lastIndexByIdentity.get(identity) === index;
    })
    .map((message) => {
      const identity = messageIdentity(message);
      if (
        identity &&
        preservedTurnDurations.has(identity) &&
        message.additional_kwargs?.turn_duration === undefined
      ) {
        return {
          ...message,
          additional_kwargs: {
            ...message.additional_kwargs,
            turn_duration: preservedTurnDurations.get(identity),
          },
        } as Message;
      }
      return message;
    });
}

/** 按运行与消息标识对持久化消息行去重。 */
function dedupeRunMessagesByIdentity(messages: RunMessage[]): RunMessage[] {
  const lastIndexByIdentity = new Map<string, number>();
  messages.forEach((message, index) => {
    const identity = messageIdentity(message.content);
    if (identity) {
      lastIndexByIdentity.set(`${message.run_id}:${identity}`, index);
    }
  });

  return messages.filter((message, index) => {
    const identity = messageIdentity(message.content);
    if (!identity) {
      return true;
    }
    return lastIndexByIdentity.get(`${message.run_id}:${identity}`) === index;
  });
}

/** 返回移除指定元素后的集合副本。 */
export function removeSetItems<T>(
  values: ReadonlySet<T>,
  itemsToRemove: Iterable<T>,
) {
  const next = new Set(values);
  for (const item of itemsToRemove) {
    next.delete(item);
  }
  return next;
}

/** 过滤已替代运行，并生成可展示的历史消息。 */
export function buildVisibleHistoryMessages(
  messageRows: RunMessage[],
  supersededRunIds: ReadonlySet<string>,
) {
  const visibleRows = messageRows.filter(
    (message) => !supersededRunIds.has(message.run_id),
  );
  return dedupeMessagesByIdentity([
    // 将所属 run_id 带到内容消息上，使历史子任务卡片展开时能拉取持久化步骤历史（#3779）。run_id 位于
    // RunMessage 包装层，否则会在此处丢失。
    ...visibleRows.map((message) => ({
      ...message.content,
      run_id: message.run_id,
    })),
  ]);
}

/** 线程消息历史分页接口返回的数据。 */
export type ThreadMessagesPageResponse = {
  data: RunMessage[];
  has_more: boolean;
  next_before_seq: number | null;
};

/** 从历史页响应提取下一页游标。 */
export function getThreadHistoryNextPageParam(
  lastPage: ThreadMessagesPageResponse,
): number | undefined {
  if (!lastPage.has_more) {
    return undefined;
  }
  if (lastPage.next_before_seq === null) {
    console.warn(
      "Thread history returned has_more without next_before_seq; pagination cannot continue.",
    );
    return undefined;
  }
  return lastPage.next_before_seq;
}

/** 生成线程历史无限查询的缓存键。 */
export const threadHistoryQueryKey = (threadId: string) =>
  ["thread-messages", threadId] as const;

/** 生成带可选序列游标的线程历史分页地址。 */
export function buildThreadMessagesPageUrl(
  baseUrl: string,
  threadId: string,
  beforeSeq?: number,
) {
  const normalizedBaseUrl = baseUrl.replace(/\/$/, "");
  const path = `/api/threads/${encodeURIComponent(threadId)}/messages/page`;
  const url = new URL(
    `${normalizedBaseUrl}${path}`,
    typeof window !== "undefined" ? window.location.origin : "http://localhost",
  );
  if (beforeSeq !== undefined) {
    url.searchParams.set("before_seq", String(beforeSeq));
  }
  return normalizedBaseUrl ? url.toString() : `${url.pathname}${url.search}`;
}

/** 按正向时间顺序拍平历史分页并去重。 */
export function flattenThreadHistoryPages(
  pages: ThreadMessagesPageResponse[],
): RunMessage[] {
  return dedupeRunMessagesByIdentity(
    pages
      .slice()
      .reverse()
      .flatMap((page) => page.data),
  );
}

/** 合并持久化、实时与乐观消息，并保持历史锚点顺序。 */
export function mergeMessages(
  historyMessages: Message[],
  threadMessages: Message[],
  optimisticMessages: Message[],
): Message[] {
  const savedTurnDurations = new Map<string, number>();
  for (const msg of historyMessages) {
    const identity = messageIdentity(msg);
    if (identity && msg.additional_kwargs?.turn_duration !== undefined) {
      savedTurnDurations.set(
        identity,
        msg.additional_kwargs.turn_duration as number,
      );
    }
  }

  const canonical = dedupeMessagesByIdentity(historyMessages);
  const live = dedupeMessagesByIdentity(threadMessages);
  const canonicalByIdentity = new Map(
    canonical.flatMap((message) => {
      const identity = messageIdentity(message);
      return identity ? [[identity, message] as const] : [];
    }),
  );
  const replacementByIdentity = new Map<string, Message>();
  // 此处采用与 resolveTransientHistoryBridge 相同的标识锚点编织方式，但有意保持独立：实时消息可替换
  // 规范副本，且无标识条目必须保留。
  const beforeAnchor = new Map<string, Message[]>();
  let pending: Message[] = [];
  let lastAnchorIdentity: string | undefined;
  let hasSharedAnchor = false;

  // 摘要化检查点不一定是连续历史后缀：中间件可在前方保留受保护的提示／输入消息，并在后方保留近期尾部。
  // 每个共享标识都是排序锚点，原位替换规范副本。新的实时消息编织到下一个共享锚点之前（或最后一个之后），
  // 从而全局“最后副本”去重永远不会把受保护的早期输入移到尾部。
  for (const message of live) {
    const identity = messageIdentity(message);
    const canonicalMessage = identity
      ? canonicalByIdentity.get(identity)
      : undefined;
    if (!identity || !canonicalMessage) {
      pending.push(message);
      continue;
    }

    if (pending.length > 0 && hasSharedAnchor) {
      beforeAnchor.set(identity, [
        ...(beforeAnchor.get(identity) ?? []),
        ...pending,
      ]);
    }
    // 摘要化检查点可从受保护消息开始，其真实规范位置与此锚点之间可能隔着尚未加载的页面。应抑制该不确定前缀，
    // 而非在视觉上折叠未知间隙。
    pending = [];
    hasSharedAnchor = true;
    lastAnchorIdentity = identity;

    // 隐藏检查点控制消息不得替换恰巧复用其标识的可见规范用户轮次。其余情况下实时检查点副本更新，应替换历史
    // 但不改变其位置。
    if (
      !isHiddenFromUIMessage(message) ||
      isHiddenFromUIMessage(canonicalMessage)
    ) {
      replacementByIdentity.set(identity, message);
    }
  }

  let canonicalAndLive: Message[];
  if (!lastAnchorIdentity) {
    canonicalAndLive = [...canonical, ...live];
  } else {
    canonicalAndLive = [];
    for (const message of canonical) {
      const identity = messageIdentity(message);
      if (identity) {
        canonicalAndLive.push(...(beforeAnchor.get(identity) ?? []));
      }
      const replacement = identity
        ? replacementByIdentity.get(identity)
        : undefined;
      canonicalAndLive.push(replacement ?? message);
    }
    // 仅实时的尾段确定在最后共享锚点之后，但该锚点未必是规范历史末尾（例如其他客户端已持久化较新记录）。
    // 追加实时尾部前必须保留规范来源顺序。
    canonicalAndLive.push(...pending);
  }

  const merged = dedupeMessagesByIdentity([
    ...canonicalAndLive,
    ...optimisticMessages,
  ]);

  return merged.map((message) => {
    const identity = messageIdentity(message);
    if (
      identity &&
      savedTurnDurations.has(identity) &&
      message.additional_kwargs?.turn_duration === undefined
    ) {
      return {
        ...message,
        additional_kwargs: {
          ...message.additional_kwargs,
          turn_duration: savedTurnDurations.get(identity),
        },
      } as Message;
    }
    return message;
  });
}

/**
 * 推导上下文摘要即将删除的实时轮次；在运行事件历史追上前，这些轮次需要短暂的视觉桥接。
 *
 * 摘要会发出 `RemoveMessage(ALL)`、隐藏摘要及保留尾部。当前实时线程中第一个保留可见消息之前的内容均将
 * 被移除；保留它们（去除已跟踪的摘要控制消息）以使 UI 仍显示完整会话（#3825）。
 */
/** 计算压缩检查点中暂未写入历史页的消息桥接缓存。 */
export function computeSummarizationTransientMessages(
  currentMessages: Message[],
  summarizationMessages: Message[],
  summarizedMessageIds: ReadonlySet<string>,
): Message[] {
  const firstRetainedVisibleIdentity = summarizationMessages
    .filter((message) => message.type !== "remove")
    .filter((message) => !isHiddenFromUIMessage(message))
    .map(messageIdentity)
    .find(isNonEmptyString);

  const moved: Message[] = [];
  for (const message of currentMessages) {
    if (
      firstRetainedVisibleIdentity &&
      messageIdentity(message) === firstRetainedVisibleIdentity
    ) {
      break;
    }
    if (!summarizedMessageIds.has(message.id ?? "")) {
      moved.push(message);
    }
  }
  return moved;
}

/**
 * 将从上下文摘要中救回的消息叠加到（可能过时的）可见历史上，确保合并视图绝不丢失它们。
 *
 * 背景（#3825）：摘要后后端删除所有实时消息（`RemoveMessage(ALL)`），规范运行事件可能仍在等待日志
 * 刷新／重新拉取。该间隙中从同步临时缓冲读取已捕获轮次，可保持合并正确。
 *
 * 规范历史按游标从新到旧分页。因此同一压缩前检查点的救回轮次可能早于当前已加载页第一行。
 * ``bridgeOrder`` 保留规范历史已确认的标识，使缺失的救回轮次插入重叠锚点旁，而不是盲目追加到最新页后；
 * 始终以规范副本为准。
 */
/** 将暂存消息桥接到已加载历史的可靠位置。 */
export function resolveTransientHistoryBridge(
  visibleHistory: Message[],
  transientMessages: Message[],
  bridgeOrder: readonly string[] = transientMessages
    .map(messageIdentity)
    .filter(isNonEmptyString),
): Message[] {
  if (transientMessages.length === 0) {
    return visibleHistory;
  }
  const presentIdentities = new Set(
    visibleHistory.map(messageIdentity).filter(isNonEmptyString),
  );
  const missing = transientMessages.filter((message) => {
    const identity = messageIdentity(message);
    // 有意跳过无标识消息：缺少稳定标识就无法与历史匹配、释放或去重，叠加会产生永久重复；规范历史会在运行日志
    // 刷新并重新拉取页面后呈现它们。
    return identity !== undefined && !presentIdentities.has(identity);
  });
  if (missing.length === 0) {
    return visibleHistory;
  }

  const missingByIdentity = new Map(
    missing.flatMap((message) => {
      const identity = messageIdentity(message);
      return identity ? [[identity, message] as const] : [];
    }),
  );
  // 此处镜像 mergeMessages 的标识锚点编织方式，但临时消息绝不替换规范副本，并有意排除无标识条目以免永久重复。
  const beforeAnchor = new Map<string, Message[]>();
  const emittedMissingIdentities = new Set<string>();
  let pending: Message[] = [];
  let lastAnchorIdentity: string | undefined;
  let hasCanonicalAnchor = false;

  for (const identity of bridgeOrder) {
    if (presentIdentities.has(identity)) {
      if (pending.length > 0 && hasCanonicalAnchor) {
        beforeAnchor.set(identity, [
          ...(beforeAnchor.get(identity) ?? []),
          ...pending,
        ]);
      }
      // 第一个已加载锚点之前的前缀没有可信位置：包含其中间历史的游标页可能尚未加载。
      pending = [];
      hasCanonicalAnchor = true;
      lastAnchorIdentity = identity;
      continue;
    }
    const message = missingByIdentity.get(identity);
    if (message && !emittedMissingIdentities.has(identity)) {
      pending.push(message);
      emittedMissingIdentities.add(identity);
    }
  }

  // 没有桥接标识与规范历史重叠。这是原始持久化间隙场景：已加载历史较旧，救回的实时轮次属于其后。
  if (!lastAnchorIdentity) {
    return [...visibleHistory, ...missing];
  }

  // 在排序快照前新增的候选项（或携带快照中不存在的标识）无法锚定。应按捕获顺序保留在已锚定桥接的尾缘，不能丢弃。
  for (const message of missing) {
    const identity = messageIdentity(message);
    if (identity && !emittedMissingIdentities.has(identity)) {
      pending.push(message);
      emittedMissingIdentities.add(identity);
    }
  }

  const resolved: Message[] = [];
  for (const message of visibleHistory) {
    const identity = messageIdentity(message);
    if (identity) {
      resolved.push(...(beforeAnchor.get(identity) ?? []));
    }
    resolved.push(message);
    if (identity === lastAnchorIdentity) {
      resolved.push(...pending);
    }
  }
  return resolved;
}

/** 合并新旧暂存桥接消息，保留最早捕获的顺序。 */
export function mergeTransientHistoryBridge(
  currentBridge: Message[],
  capturedMessages: Message[],
): Message[] {
  const merged = dedupeMessagesByIdentity(currentBridge);
  const indexByIdentity = new Map<string, number>();
  merged.forEach((message, index) => {
    const identity = messageIdentity(message);
    if (identity) {
      indexByIdentity.set(identity, index);
    }
  });

  for (const captured of dedupeMessagesByIdentity(capturedMessages)) {
    const identity = messageIdentity(captured);
    const existingIndex = identity ? indexByIdentity.get(identity) : undefined;
    if (existingIndex === undefined) {
      if (identity) {
        indexByIdentity.set(identity, merged.length);
      }
      merged.push(captured);
      continue;
    }

    const existing = merged[existingIndex];
    if (
      existing &&
      (!isHiddenFromUIMessage(captured) || isHiddenFromUIMessage(existing))
    ) {
      // 刷新缓冲快照而不移动其首次已知的时间顺序位置；重复压缩可在较新尾部前再次捕获受保护前缀消息。
      merged[existingIndex] = captured;
    }
  }
  return merged;
}

/**
 * 独立于桥接候选项保存完整的检查点相对标识顺序。已确认候选项会从渲染缓冲裁剪，但其标识仍作为非渲染分页锚点。
 */
/** 合并暂存桥接的身份顺序快照。 */
export function mergeTransientHistoryBridgeOrder(
  currentOrder: readonly string[],
  capturedMessages: Message[],
): string[] {
  const capturedOrder = dedupeMessagesByIdentity(capturedMessages)
    .map(messageIdentity)
    .filter(isNonEmptyString);
  const merged = [...currentOrder];
  const seen = new Set(currentOrder);
  for (const identity of capturedOrder) {
    if (!seen.has(identity)) {
      seen.add(identity);
      merged.push(identity);
    }
  }
  return merged;
}

/** 为线程消息解析当前可渲染的暂存历史桥接。 */
export function resolveThreadTransientHistoryBridge(
  visibleHistory: Message[],
  transientMessages: Message[],
  bridgeThreadId: string | null,
  currentThreadId: string | null | undefined,
  bridgeOrder?: readonly string[],
): Message[] {
  if (!bridgeThreadId || bridgeThreadId !== currentThreadId) {
    return visibleHistory;
  }
  return resolveTransientHistoryBridge(
    visibleHistory,
    transientMessages,
    bridgeOrder,
  );
}

/**
 * 删除规范历史已吸收的临时缓冲条目，使缓冲仅作为跨越异步间隙的临时桥接而非第二个长期事实来源；否则过时副本
 * 可能复活历史随后过滤的消息（如被替换或重新生成的运行）。
 */
/** 移除已被持久化历史确认的暂存消息。 */
export function pruneConfirmedTransientMessages(
  transientMessages: Message[],
  visibleHistory: Message[],
): Message[] {
  if (transientMessages.length === 0) {
    return transientMessages;
  }
  const confirmedIdentities = new Set(
    visibleHistory.map(messageIdentity).filter(isNonEmptyString),
  );
  return transientMessages.filter((message) => {
    const identity = messageIdentity(message);
    return !identity || !confirmedIdentities.has(identity);
  });
}

/** 提取相对流开始基线新增的消息。 */
function getMessagesAfterBaseline(
  messages: Message[],
  baselineMessageIds: ReadonlySet<string>,
): Message[] {
  return messages.filter((message) => {
    const id = messageIdentity(message);
    return !id || !baselineMessageIds.has(id);
  });
}

/** 筛选尚未被服务端消息确认的乐观消息。 */
export function getVisibleOptimisticMessages(
  optimisticMessages: Message[],
  previousHumanMessageCount: number,
  currentHumanMessageCount: number,
): Message[] {
  if (
    optimisticMessages.some((message) => message.type === "human") &&
    currentHumanMessageCount > previousHumanMessageCount
  ) {
    return [];
  }
  return optimisticMessages;
}

/** 从流事件中识别摘要中间件写入的消息。 */
export function getSummarizationMiddlewareMessages(
  data: unknown,
): Message[] | undefined {
  if (typeof data !== "object" || data === null) {
    return undefined;
  }

  for (const [key, update] of Object.entries(data)) {
    if (!SUMMARIZATION_MIDDLEWARE_UPDATE_KEYS.has(key)) {
      continue;
    }
    if (typeof update !== "object" || update === null) {
      continue;
    }

    const messages = Reflect.get(update, "messages");
    if (Array.isArray(messages)) {
      return [...messages] as Message[];
    }
  }

  return undefined;
}

/** 在普通线程搜索缓存中插入或更新线程。 */
export function upsertThreadInSearchCache(
  queryClient: QueryClient,
  thread: AgentThread,
) {
  queryClient.setQueriesData(
    {
      queryKey: ["threads", "search"],
      exact: false,
    },
    (oldData: Array<AgentThread> | undefined) => {
      if (!oldData) {
        return [thread];
      }

      const existingIndex = oldData.findIndex(
        (t) => t.thread_id === thread.thread_id,
      );
      if (existingIndex === -1) {
        return [thread, ...oldData];
      }

      return oldData.map((t, index) => {
        if (index !== existingIndex) {
          return t;
        }
        return {
          ...thread,
          ...t,
          metadata: {
            ...(thread.metadata ?? {}),
            ...(t.metadata ?? {}),
          },
          values: {
            ...thread.values,
            ...t.values,
          },
        };
      });
    },
  );
}

/** 在无限分页线程缓存中插入或更新线程。 */
export function upsertThreadInInfiniteCache(
  queryClient: QueryClient,
  thread: AgentThread,
) {
  queryClient.setQueriesData(
    {
      queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
      exact: false,
    },
    (oldData: InfiniteData<AgentThread[]> | undefined) => {
      if (!oldData) {
        return oldData;
      }

      const merged = oldData.pages.map((page) =>
        page.map((t) =>
          t.thread_id === thread.thread_id
            ? {
                ...thread,
                ...t,
                metadata: {
                  ...(thread.metadata ?? {}),
                  ...(t.metadata ?? {}),
                },
                values: {
                  ...thread.values,
                  ...t.values,
                },
              }
            : t,
        ),
      );

      const exists = merged.some((page) =>
        page.some((t) => t.thread_id === thread.thread_id),
      );
      if (exists) {
        return { ...oldData, pages: merged };
      }

      const firstPage = merged[0] ?? [];
      const restPages = merged.slice(1);
      return {
        ...oldData,
        pages: [[thread, ...firstPage], ...restPages],
      };
    },
  );
}

/** 使停止运行后可能陈旧的线程相关缓存失效。 */
export function invalidateStoppedThreadCaches(
  queryClient: QueryClient,
  threadId: string | null | undefined,
) {
  void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
  void queryClient.invalidateQueries({
    queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
  });

  if (!threadId) {
    return;
  }

  void queryClient.invalidateQueries({ queryKey: ["thread", threadId] });
  void queryClient.invalidateQueries({
    queryKey: threadHistoryQueryKey(threadId),
  });
  void queryClient.invalidateQueries({
    queryKey: ["thread", "metadata", threadId],
  });
  void queryClient.invalidateQueries({
    queryKey: threadTokenUsageQueryKey(threadId),
  });
}

/** 停止运行后补充刷新最终状态前的等待时长（毫秒）。 */
export const STOP_THREAD_FINALIZATION_REFETCH_DELAY_MS = 1500;

/** 延后补充刷新停止运行可能尚未落库的最终状态。 */
function scheduleStoppedThreadFinalizationRefetch(
  queryClient: QueryClient,
  threadId: string | null | undefined,
) {
  globalThis.setTimeout(() => {
    invalidateStoppedThreadCaches(queryClient, threadId);
  }, STOP_THREAD_FINALIZATION_REFETCH_DELAY_MS);
}

/** 停止线程运行，并刷新关联的客户端缓存。 */
export async function stopThreadAndInvalidateCaches(
  queryClient: QueryClient,
  stop: () => Promise<void> | void,
  threadId: string | null | undefined,
) {
  try {
    await stop();
  } finally {
    invalidateStoppedThreadCaches(queryClient, threadId);
    scheduleStoppedThreadFinalizationRefetch(queryClient, threadId);
  }
}

/** 将流异常转换为用户可读的错误消息。 */
function getStreamErrorMessage(error: unknown): string {
  if (typeof error === "string" && error.trim()) {
    return error;
  }
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  if (typeof error === "object" && error !== null) {
    const message = Reflect.get(error, "message");
    if (typeof message === "string" && message.trim()) {
      return message;
    }
    const nestedError = Reflect.get(error, "error");
    if (nestedError instanceof Error && nestedError.message.trim()) {
      return nestedError.message;
    }
    if (typeof nestedError === "string" && nestedError.trim()) {
      return nestedError;
    }
  }
  return "Request failed.";
}

/** 从失败 HTTP 响应中读取错误消息。 */
async function readResponseErrorMessage(
  response: Response,
  fallback = "Request failed.",
) {
  try {
    const data = await response.json();
    if (typeof data?.detail === "string" && data.detail.trim()) {
      return data.detail;
    }
  } catch {
    // 响应体不是 JSON 时使用下方回退值。
  }
  return response.statusText || fallback;
}

/** 尝试从未知异常对象提取 HTTP 状态码。 */
function getHttpStatus(error: unknown): number | undefined {
  if (typeof error !== "object" || error === null) {
    return undefined;
  }

  const status = Reflect.get(error, "status");
  if (typeof status === "number") {
    return status;
  }

  const response = Reflect.get(error, "response");
  if (typeof response === "object" && response !== null) {
    const responseStatus = Reflect.get(response, "status");
    if (typeof responseStatus === "number") {
      return responseStatus;
    }
  }

  return undefined;
}

/** 判断异常是否表示线程不存在或当前用户无权访问。 */
function isThreadMissingError(error: unknown): boolean {
  const status = getHttpStatus(error);
  // 此处将 403 等同 404，避免泄露无权访问的线程是否存在；调用方会把过时／不可访问 URL 重定向到空白聊天。
  return status === 403 || status === 404;
}

/** 管理线程运行的流式状态、乐观消息和缓存同步。 */
export function useThreadStream({
  threadId,
  displayThreadId,
  context,
  onSend,
  onStart,
  onFinish,
  onToolEnd,
}: ThreadStreamOptions) {
  const { t } = useI18n();
  const currentViewThreadId = displayThreadId ?? threadId ?? null;
  const currentViewThreadIdRef = useRef(currentViewThreadId);
  currentViewThreadIdRef.current = currentViewThreadId;
  // 服务端流响应前展示的乐观消息。
  const [optimisticMessages, setOptimisticMessages] = useState<Message[]>([]);
  const [optimisticThreadId, setOptimisticThreadId] = useState<string | null>(
    null,
  );
  const [liveMessagesThreadId, setLiveMessagesThreadId] = useState<
    string | null
  >(null);
  const [pendingSupersededRunIds, setPendingSupersededRunIds] = useState<
    ReadonlySet<string>
  >(() => new Set());
  const [pendingSupersededMessageIds, setPendingSupersededMessageIds] =
    useState<ReadonlySet<string>>(() => new Set());
  const [isUploading, setIsUploading] = useState(false);
  // 跟踪当前流式线程 ID，以处理流式期间的线程切换。
  const [onStreamThreadId, setOnStreamThreadId] = useState(() => threadId);
  // 此引用可跨异步回调跟踪当前线程 ID 而不触发重渲染，并让 onUpdateEvent 读取当前线程 ID。
  const threadIdRef = useRef<string | null>(threadId ?? null);
  const startedRef = useRef(false);
  const pendingUsageBaselineMessageIdsRef = useRef<Set<string>>(new Set());
  const listeners = useRef({
    onSend,
    onStart,
    onFinish,
    onToolEnd,
  });

  const {
    messages: history,
    hasMore: hasMoreHistory,
    loadMore: loadMoreHistory,
    loading: isHistoryLoading,
  } = useThreadHistory(onStreamThreadId ?? "", {
    pendingSupersededRunIds,
  });

  // 使监听器引用始终指向最新回调。
  useEffect(() => {
    listeners.current = { onSend, onStart, onFinish, onToolEnd };
  }, [onSend, onStart, onFinish, onToolEnd]);

  useEffect(() => {
    const normalizedThreadId = threadId ?? null;
    if (!normalizedThreadId) {
      // UI 切回全新的未保存线程时重置。
      startedRef.current = false;
      setOnStreamThreadId(normalizedThreadId);
    } else {
      setOnStreamThreadId(normalizedThreadId);
    }
    threadIdRef.current = normalizedThreadId;
  }, [threadId]);

  /** 记录流对应的线程，并仅在本轮首次启动时通知外部监听器。 */
  const handleStreamStart = useCallback((_threadId: string, _runId: string) => {
    threadIdRef.current = _threadId;
    setOptimisticThreadId((currentOptimisticThreadId) => {
      const currentView = currentViewThreadIdRef.current;
      if (
        currentOptimisticThreadId &&
        (currentOptimisticThreadId === currentView ||
          currentOptimisticThreadId === _threadId)
      ) {
        return _threadId;
      }
      return currentOptimisticThreadId;
    });
    setLiveMessagesThreadId((currentLiveMessagesThreadId) => {
      const currentView = currentViewThreadIdRef.current;
      if (
        currentLiveMessagesThreadId &&
        (currentLiveMessagesThreadId === currentView ||
          currentLiveMessagesThreadId === _threadId)
      ) {
        return _threadId;
      }
      return currentLiveMessagesThreadId;
    });
    if (!startedRef.current) {
      listeners.current.onStart?.(_threadId, _runId);
      startedRef.current = true;
    }
    setOnStreamThreadId(_threadId);
  }, []);

  const queryClient = useQueryClient();
  const updateSubtask = useUpdateSubtask();

  const thread = useStream<AgentThreadState>({
    client: getAPIClient(),
    assistantId: "lead_agent",
    threadId: onStreamThreadId,
    reconnectOnMount: true,
    fetchStateHistory: { limit: 1 },
    /** 新线程创建后立即补入两个线程列表缓存，并保存所选代理信息。 */
    onCreated(meta) {
      handleStreamStart(meta.thread_id, meta.run_id);
      const now = new Date().toISOString();
      upsertThreadInSearchCache(queryClient, {
        thread_id: meta.thread_id,
        created_at: now,
        updated_at: now,
        metadata: context.agent_name ? { agent_name: context.agent_name } : {},
        status: "busy",
        values: {
          title: t.pages.newChat,
          messages: [],
          artifacts: [],
        },
        interrupts: {},
      });
      upsertThreadInInfiniteCache(queryClient, {
        thread_id: meta.thread_id,
        created_at: now,
        updated_at: now,
        metadata: context.agent_name ? { agent_name: context.agent_name } : {},
        status: "busy",
        values: {
          title: t.pages.newChat,
          messages: [],
          artifacts: [],
        },
        interrupts: {},
      });
      if (context.agent_name) {
        void getAPIClient()
          .threads.update(meta.thread_id, {
            metadata: { agent_name: context.agent_name },
          })
          .catch(() => ({}));
      }
    },
    /** 转发工具调用结束事件，供聊天界面执行后续展示或联动。 */
    onLangChainEvent(event) {
      if (event.event === "on_tool_end") {
        listeners.current.onToolEnd?.({
          name: event.name,
          data: event.data,
        });
      }
    },
    /** 合并流式状态更新，处理摘要过渡消息并同步线程标题缓存。 */
    onUpdateEvent(data) {
      const _messages = getSummarizationMiddlewareMessages(data);
      if (_messages && _messages.length >= 2) {
        for (const m of _messages) {
          // 向后兼容：PR2 之前的线程可能仍携带旧摘要路径生成的
          // HumanMessage(name="summary")。新线程改为将摘要保存在
          // ThreadState.summary_text 中。
          if (m.name === "summary" && m.type === "human") {
            summarizedRef.current?.add(m.id ?? "");
          }
        }
        const transientMessages = computeSummarizationTransientMessages(
          messagesRef.current,
          _messages,
          summarizedRef.current ?? new Set<string>(),
        );
        transientHistoryOrderRef.current = mergeTransientHistoryBridgeOrder(
          transientHistoryOrderRef.current,
          transientMessages,
        );
        transientHistoryBridgeRef.current = mergeTransientHistoryBridge(
          transientHistoryBridgeRef.current,
          transientMessages,
        );
        transientHistoryThreadIdRef.current = threadIdRef.current;
        messagesRef.current = [];
      }

      const updates: Array<Partial<AgentThreadState> | null> = Object.values(
        data || {},
      );
      for (const update of updates) {
        if (update && "title" in update && update.title) {
          void queryClient.setQueriesData(
            {
              queryKey: ["threads", "search"],
              exact: false,
            },
            (oldData: Array<AgentThread> | undefined) => {
              return oldData?.map((t) => {
                if (t.thread_id === threadIdRef.current) {
                  return {
                    ...t,
                    values: {
                      ...t.values,
                      title: update.title,
                    },
                  };
                }
                return t;
              });
            },
          );
          const nextTitle: string = update.title;
          void queryClient.setQueriesData(
            {
              queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
              exact: false,
            },
            (oldData: InfiniteData<AgentThread[]> | undefined) =>
              mapInfiniteThreadsCache(
                oldData,
                (t): AgentThread =>
                  t.thread_id === threadIdRef.current
                    ? {
                        ...t,
                        values: {
                          ...t.values,
                          title: nextTitle,
                        },
                      }
                    : t,
              ),
          );
        }
      }
    },
    /** 解析任务和重试事件，更新子代理步骤或向用户提示重试信息。 */
    onCustomEvent(event: unknown) {
      // 仅收窄一次 `event.type`；taskEventToSubtaskUpdate 已验证 task_* 事件，
      // 因此下方各分支从这一唯一事实来源读取，避免每次都重新检查对象结构。
      const eventType =
        typeof event === "object" && event !== null && "type" in event
          ? (event as { type: unknown }).type
          : undefined;

      const taskUpdate = taskEventToSubtaskUpdate(event);
      if (taskUpdate) {
        updateSubtask(taskUpdate);
      }

      if (eventType === "task_running") {
        const e = event as {
          type: "task_running";
          task_id: string;
          message: AIMessage;
          message_index?: number;
        };
        // 累积完整步骤历史而非覆盖（#3779）：保留 latestMessage 供折叠标题显示
        // 工具调用提示，并将规范化步骤（助手轮次或工具输出）追加到时间线。
        updateSubtask({
          id: e.task_id,
          latestMessage: e.message,
          steps: [messageToStep(e.message, e.message_index ?? 0)],
        });
        return;
      }

      if (eventType === "llm_retry") {
        const e = event as { type: "llm_retry"; message?: unknown };
        if (typeof e.message === "string" && e.message.trim()) {
          toast(e.message);
        }
      }
    },
    /** 清除本次运行的临时消息状态并刷新受影响的历史和用量缓存。 */
    onError(error) {
      setOptimisticMessages([]);
      setOptimisticThreadId(null);
      setLiveMessagesThreadId(null);
      setPendingSupersededRunIds(new Set());
      setPendingSupersededMessageIds(new Set());
      toast.error(getStreamErrorMessage(error));
      pendingUsageBaselineMessageIdsRef.current = new Set(
        messagesRef.current
          .map(messageIdentity)
          .filter((id): id is string => Boolean(id)),
      );
      if (threadIdRef.current) {
        void queryClient.invalidateQueries({
          queryKey: threadHistoryQueryKey(threadIdRef.current),
        });
        void queryClient.invalidateQueries({
          queryKey: threadTokenUsageQueryKey(threadIdRef.current),
        });
      }
    },
    /** 通知调用方运行完成，并刷新线程、历史记录和用量相关缓存。 */
    onFinish(state) {
      listeners.current.onFinish?.(state.values);
      pendingUsageBaselineMessageIdsRef.current = new Set(
        messagesRef.current
          .map(messageIdentity)
          .filter((id): id is string => Boolean(id)),
      );
      invalidateStoppedThreadCaches(queryClient, threadIdRef.current);
    },
  });

  /** 停止当前运行，并同步刷新相关线程缓存与运行状态。 */
  const stopThread = useCallback(async () => {
    const stoppedThreadId =
      threadIdRef.current ?? displayThreadId ?? threadId ?? null;
    await stopThreadAndInvalidateCaches(
      queryClient,
      () => thread.stop(),
      stoppedThreadId,
    );
  }, [displayThreadId, queryClient, thread, threadId]);

  const hasVisibleStreamState =
    Boolean(threadId) || liveMessagesThreadId === currentViewThreadId;
  const persistedMessages = useMemo(
    () =>
      hasVisibleStreamState
        ? thread.messages.filter(
            (message) =>
              !message.id || !pendingSupersededMessageIds.has(message.id),
          )
        : [],
    [hasVisibleStreamState, pendingSupersededMessageIds, thread.messages],
  );
  const visibleHistory = useMemo(
    () => (threadId ? history : []),
    [history, threadId],
  );
  const humanMessageCount = persistedMessages.filter(
    (m) => m.type === "human",
  ).length;
  const latestMessageCountsRef = useRef({ humanMessageCount });
  const sendInFlightRef = useRef(false);
  const messagesRef = useRef<Message[]>([]);
  // 当前流的生命周期桥接：检查点尾部删除消息后，到规范运行事件页重新获取并观察到
  // 日志刷写之前暂存这些消息；它绝不会追加到 useThreadHistory 的持久化分页中。
  const transientHistoryBridgeRef = useRef<Message[]>([]);
  // 每个已捕获检查点的完整标识顺序。已确认的桥接条目会从消息缓冲中裁剪，但仍在此处
  // 作为非渲染锚点保留，以便将较早的救回消息置于按最新优先排序的页面之前。
  const transientHistoryOrderRef = useRef<string[]>([]);
  const transientHistoryThreadIdRef = useRef<string | null>(null);
  const summarizedRef = useRef<Set<string>>(null);
  // 发送前记录人工消息数量，防止服务端人工消息尚未到达就清除乐观消息（例如
  // "messages-tuple" 事件中的 AI 消息早于 "values" 事件中的输入人工消息到达时）。
  const prevHumanMsgCountRef = useRef(humanMessageCount);

  latestMessageCountsRef.current = { humanMessageCount };
  summarizedRef.current ??= new Set<string>();

  // 在线程间切换时重置线程本地的待处理 UI 状态，避免乐观消息与发送中守卫泄漏到
  // 其他聊天视图。
  useEffect(() => {
    startedRef.current = false;
    sendInFlightRef.current = false;
    messagesRef.current = [];
    transientHistoryBridgeRef.current = [];
    transientHistoryOrderRef.current = [];
    transientHistoryThreadIdRef.current = null;
    summarizedRef.current = new Set<string>();
    pendingUsageBaselineMessageIdsRef.current = new Set();
    setPendingSupersededRunIds(new Set());
    setPendingSupersededMessageIds(new Set());
    prevHumanMsgCountRef.current =
      latestMessageCountsRef.current.humanMessageCount;
  }, [threadId]);

  // 规范历史确认稳定标识后逐条释放条目。在当前页面生命周期内跨失败／重新获取保留
  // 未确认条目，避免暂时的持久化间隙隐藏某个对话轮次。
  useEffect(() => {
    transientHistoryBridgeRef.current = pruneConfirmedTransientMessages(
      transientHistoryBridgeRef.current,
      visibleHistory,
    );
    if (transientHistoryBridgeRef.current.length === 0) {
      transientHistoryOrderRef.current = [];
      transientHistoryThreadIdRef.current = null;
    }
  }, [visibleHistory]);

  useEffect(() => {
    if (optimisticThreadId && optimisticThreadId !== currentViewThreadId) {
      setOptimisticMessages([]);
      setOptimisticThreadId(null);
    }
    if (liveMessagesThreadId && liveMessagesThreadId !== currentViewThreadId) {
      setLiveMessagesThreadId(null);
    }
  }, [currentViewThreadId, liveMessagesThreadId, optimisticThreadId]);

  // 流式传输在没有基线时开始（例如重连、另一客户端启动运行，或流式期间页面重载），
  // 则快照当前消息，使令牌用量仅将*新增*消息视为“待处理”。
  useEffect(() => {
    if (
      thread.isLoading &&
      pendingUsageBaselineMessageIdsRef.current.size === 0
    ) {
      pendingUsageBaselineMessageIdsRef.current = new Set(
        persistedMessages
          .map(messageIdentity)
          .filter((id): id is string => Boolean(id)),
      );
    }
  }, [persistedMessages, thread.isLoading]);

  // 服务端消息到达后清除乐观消息。
  // 若包含人工乐观消息，须等待服务端的人工消息到达，避免输入消息尚未出现在流中就
  // 清除（输入消息可能在 AI 消息的单独 "messages-tuple" 事件之后，才通过
  // "values" 事件到达）。
  const optimisticMessageCount = optimisticMessages.length;
  const hasHumanOptimistic = optimisticMessages.some((m) => m.type === "human");
  useEffect(() => {
    if (optimisticMessageCount === 0) return;

    const newHumanMsgArrived = humanMessageCount > prevHumanMsgCountRef.current;

    if (!hasHumanOptimistic || newHumanMsgArrived) {
      setOptimisticMessages([]);
      setOptimisticThreadId(null);
    }
  }, [hasHumanOptimistic, humanMessageCount, optimisticMessageCount]);

  /** 添加乐观消息、上传附件并提交新消息，同时处理失败回滚和状态通知。 */
  const sendMessage = useCallback(
    async (
      threadId: string,
      message: PromptInputMessage,
      extraContext?: Record<string, unknown>,
      options?: SendMessageOptions,
    ) => {
      if (sendInFlightRef.current) {
        return;
      }
      sendInFlightRef.current = true;

      // 发送确实已越过发送中守卫，调用方现在可以执行一次性清理；被丢弃路径不得触发它。
      options?.onSent?.();

      const text = message.text.trim();

      // 展示乐观消息前捕获当前人工消息数量，以便等待服务端写入的用户输入副本。
      prevHumanMsgCountRef.current = humanMessageCount;
      pendingUsageBaselineMessageIdsRef.current = new Set(
        persistedMessages
          .map(messageIdentity)
          .filter((id): id is string => Boolean(id)),
      );

      // 构建状态为上传中的乐观文件列表。
      const optimisticFiles: FileInMessage[] = (message.files ?? []).map(
        (f) => ({
          filename: f.filename ?? "",
          size: 0,
          status: "uploading" as const,
        }),
      );

      const hideFromUI = options?.additionalKwargs?.hide_from_ui === true;
      const optimisticAdditionalKwargs = {
        ...options?.additionalKwargs,
        ...(optimisticFiles.length > 0 ? { files: optimisticFiles } : {}),
      };

      const newOptimistic: Message[] = [];
      if (!hideFromUI) {
        newOptimistic.push({
          type: "human",
          id: `opt-human-${Date.now()}`,
          content: text ? [{ type: "text", text }] : "",
          additional_kwargs: optimisticAdditionalKwargs,
        });
      }

      if (optimisticFiles.length > 0 && !hideFromUI) {
        // 文件上传期间显示模拟的 AI 消息。
        newOptimistic.push({
          type: "ai",
          id: `opt-ai-${Date.now()}`,
          content: t.uploads.uploadingFiles,
          additional_kwargs: { element: "task" },
        });
      }
      setOptimisticThreadId(threadId);
      setLiveMessagesThreadId(threadId);
      setOptimisticMessages(newOptimistic);

      listeners.current.onSend?.(threadId);

      let uploadedFileInfo: UploadedFileInfo[] = [];

      try {
        // 若有文件，先完成上传。
        if (message.files && message.files.length > 0) {
          setIsUploading(true);
          try {
            const filePromises = message.files.map((fileUIPart) =>
              promptInputFilePartToFile(fileUIPart),
            );

            const conversionResults = await Promise.all(filePromises);
            const files = conversionResults.filter(
              (file): file is File => file !== null,
            );
            const failedConversions = conversionResults.length - files.length;

            if (failedConversions > 0) {
              throw new Error(
                `Failed to prepare ${failedConversions} attachment(s) for upload. Please retry.`,
              );
            }

            if (!threadId) {
              throw new Error("Thread is not ready for file upload.");
            }

            if (files.length > 0) {
              const uploadResponse = await uploadFiles(threadId, files);
              uploadedFileInfo = uploadResponse.files;

              // 用已上传状态与路径更新乐观人工消息。
              const uploadedFiles: FileInMessage[] = uploadedFileInfo.map(
                (info) => ({
                  filename: info.filename,
                  size: info.size,
                  path: info.virtual_path,
                  status: "uploaded" as const,
                }),
              );
              setOptimisticMessages((messages) => {
                if (messages.length > 1 && messages[0]) {
                  const humanMessage: Message = messages[0];
                  return [
                    {
                      ...humanMessage,
                      additional_kwargs: { files: uploadedFiles },
                    },
                    ...messages.slice(1),
                  ];
                }
                return messages;
              });
            }
          } catch (error) {
            const errorMessage =
              error instanceof Error
                ? error.message
                : "Failed to upload files.";
            toast.error(errorMessage);
            setOptimisticMessages([]);
            setOptimisticThreadId(null);
            setLiveMessagesThreadId(null);
            throw error;
          } finally {
            setIsUploading(false);
          }
        }

        // 构建提交所需的文件元数据（放入 additional_kwargs）。
        const filesForSubmit: FileInMessage[] = uploadedFileInfo.map(
          (info) => ({
            filename: info.filename,
            size: info.size,
            path: info.virtual_path,
            status: "uploaded" as const,
          }),
        );

        await thread.submit(
          {
            messages: buildThreadSubmitMessages({
              text,
              additionalKwargs: options?.additionalKwargs,
              additionalInputMessages: options?.additionalInputMessages,
              filesForSubmit,
            }),
          },
          {
            threadId: threadId,
            streamSubgraphs: true,
            streamResumable: true,
            config: {
              recursion_limit: 1000,
            },
            context: {
              ...extraContext,
              ...context,
              thinking_enabled: context.mode !== "flash",
              is_plan_mode: context.mode === "pro" || context.mode === "ultra",
              subagent_enabled: context.mode === "ultra",
              reasoning_effort:
                context.reasoning_effort ??
                (context.mode === "ultra"
                  ? "high"
                  : context.mode === "pro"
                    ? "medium"
                    : context.mode === "thinking"
                      ? "low"
                      : undefined),
              thread_id: threadId,
            },
          },
        );
        void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
        void queryClient.invalidateQueries({
          queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
        });
      } catch (error) {
        setOptimisticMessages([]);
        setOptimisticThreadId(null);
        setLiveMessagesThreadId(null);
        setIsUploading(false);
        throw error;
      } finally {
        sendInFlightRef.current = false;
      }
    },
    [
      thread,
      t.uploads.uploadingFiles,
      context,
      queryClient,
      humanMessageCount,
      persistedMessages,
    ],
  );

  /** 通过服务端准备的检查点重新生成目标回答，并隐藏被替代的旧消息。 */
  const regenerateMessage = useCallback(
    async (
      threadId: string,
      messageId: string,
      supersededMessageIds: string[] = [messageId],
    ) => {
      if (sendInFlightRef.current || !threadId || !messageId) {
        return;
      }
      sendInFlightRef.current = true;
      prevHumanMsgCountRef.current = humanMessageCount;
      pendingUsageBaselineMessageIdsRef.current = new Set(
        persistedMessages
          .map(messageIdentity)
          .filter((id): id is string => Boolean(id)),
      );
      setLiveMessagesThreadId(threadId);
      listeners.current.onSend?.(threadId);
      let preparedSupersededRunId: string | null = null;
      let preparedSupersededMessageIds: string[] = [];

      try {
        const response = await fetch(
          `${getBackendBaseURL()}/api/threads/${encodeURIComponent(
            threadId,
          )}/runs/regenerate/prepare`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            credentials: "include",
            body: JSON.stringify({ message_id: messageId }),
          },
        );
        if (!response.ok) {
          throw new Error(await readResponseErrorMessage(response));
        }
        const prepared = (await response.json()) as RegeneratePrepareResponse;
        preparedSupersededRunId = prepared.target_run_id;
        preparedSupersededMessageIds = supersededMessageIds;
        setPendingSupersededRunIds((current) => {
          const next = new Set(current);
          next.add(prepared.target_run_id);
          return next;
        });
        setPendingSupersededMessageIds((current) => {
          const next = new Set(current);
          for (const id of supersededMessageIds) {
            next.add(id);
          }
          return next;
        });

        await thread.submit(prepared.input, {
          threadId,
          checkpoint: prepared.checkpoint,
          metadata: prepared.metadata,
          streamSubgraphs: true,
          streamResumable: true,
          config: {
            recursion_limit: 1000,
          },
          context: {
            ...context,
            thinking_enabled: context.mode !== "flash",
            is_plan_mode: context.mode === "pro" || context.mode === "ultra",
            subagent_enabled: context.mode === "ultra",
            reasoning_effort:
              context.reasoning_effort ??
              (context.mode === "ultra"
                ? "high"
                : context.mode === "pro"
                  ? "medium"
                  : context.mode === "thinking"
                    ? "low"
                    : undefined),
            thread_id: threadId,
          },
        });
        void queryClient.invalidateQueries({ queryKey: ["thread", threadId] });
        void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
        void queryClient.invalidateQueries({
          queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
        });
        void queryClient.invalidateQueries({
          queryKey: threadTokenUsageQueryKey(threadId),
        });
      } catch (error) {
        setLiveMessagesThreadId(null);
        if (preparedSupersededRunId) {
          const supersededRunId = preparedSupersededRunId;
          setPendingSupersededRunIds((current) =>
            removeSetItems(current, [supersededRunId]),
          );
          setPendingSupersededMessageIds((current) =>
            removeSetItems(current, preparedSupersededMessageIds),
          );
        }
        toast.error(getStreamErrorMessage(error));
      } finally {
        sendInFlightRef.current = false;
      }
    },
    [context, humanMessageCount, persistedMessages, queryClient, thread],
  );

  // 在引用中缓存最新线程消息，用于与传入历史消息去重，并使 onUpdateEvent 可访问完整
  // 消息列表而不触发重新渲染。
  if (persistedMessages.length >= messagesRef.current.length) {
    messagesRef.current = persistedMessages;
  }

  const visibleOptimisticMessages = getVisibleOptimisticMessages(
    optimisticThreadId === currentViewThreadId ? optimisticMessages : [],
    prevHumanMsgCountRef.current,
    humanMessageCount,
  );

  const transientHistoryOrder =
    transientHistoryBridgeRef.current.length > 0 &&
    transientHistoryThreadIdRef.current === threadId
      ? mergeTransientHistoryBridgeOrder(
          transientHistoryOrderRef.current,
          persistedMessages,
        )
      : transientHistoryOrderRef.current;

  // React 提交本次渲染后再写入扩展后的非渲染顺序骨架。上方局部值在渲染期间不修改
  // 引用的前提下，保证本次渲染正确锚定。
  useEffect(() => {
    if (
      transientHistoryBridgeRef.current.length > 0 &&
      transientHistoryThreadIdRef.current === threadId
    ) {
      transientHistoryOrderRef.current = mergeTransientHistoryBridgeOrder(
        transientHistoryOrderRef.current,
        persistedMessages,
      );
    }
  }, [persistedMessages, threadId]);

  const effectiveHistory = resolveThreadTransientHistoryBridge(
    visibleHistory,
    transientHistoryBridgeRef.current,
    transientHistoryThreadIdRef.current,
    threadId,
    transientHistoryOrder,
  );
  const mergedMessages = mergeMessages(
    effectiveHistory,
    persistedMessages,
    visibleOptimisticMessages,
  );
  const pendingUsageMessages = thread.isLoading
    ? getMessagesAfterBaseline(
        persistedMessages,
        pendingUsageBaselineMessageIdsRef.current,
      )
    : [];

  // 合并历史、实时流和乐观消息以供展示。
  // 历史消息可能与 thread.messages 重叠；以后者为准。
  const mergedThread = {
    ...thread,
    stop: stopThread,
    values: hasVisibleStreamState ? thread.values : EMPTY_THREAD_VALUES,
    messages: mergedMessages,
  } as typeof thread;

  return {
    thread: mergedThread,
    pendingUsageMessages,
    sendMessage,
    regenerateMessage,
    isUploading,
    isHistoryLoading,
    hasMoreHistory,
    loadMoreHistory,
  } as const;
}

type ThreadHistoryOptions = {
  enabled?: boolean;
  pendingSupersededRunIds?: ReadonlySet<string>;
};

/** 分页加载线程持久化历史，并与实时状态叠加。 */
export function useThreadHistory(
  threadId: string,
  { enabled = true, pendingSupersededRunIds }: ThreadHistoryOptions = {},
) {
  const historyQuery = useInfiniteQuery<
    ThreadMessagesPageResponse,
    Error,
    InfiniteData<ThreadMessagesPageResponse>,
    ReturnType<typeof threadHistoryQueryKey>,
    number | null
  >({
    queryKey: threadHistoryQueryKey(threadId),
    enabled: enabled && Boolean(threadId),
    initialPageParam: null,
    queryFn: async ({ pageParam, signal }) => {
      const url = buildThreadMessagesPageUrl(
        getBackendBaseURL(),
        threadId,
        pageParam ?? undefined,
      );
      const response = await fetch(url, {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "include",
        signal,
      });
      if (!response.ok) {
        throw new Error(
          await readResponseErrorMessage(
            response,
            "Failed to load thread history.",
          ),
        );
      }
      return (await response.json()) as ThreadMessagesPageResponse;
    },
    getNextPageParam: getThreadHistoryNextPageParam,
  });

  const messageRows = useMemo(
    () => flattenThreadHistoryPages(historyQuery.data?.pages ?? []),
    [historyQuery.data?.pages],
  );

  const messages = useMemo(() => {
    return buildVisibleHistoryMessages(
      messageRows,
      pendingSupersededRunIds ?? new Set<string>(),
    );
  }, [messageRows, pendingSupersededRunIds]);

  useEffect(() => {
    if (historyQuery.error) {
      console.error(historyQuery.error);
      toast.error("Failed to load thread history.");
    }
  }, [historyQuery.error]);

  return {
    messages,
    loading: historyQuery.isLoading || historyQuery.isFetchingNextPage,
    hasMore: Boolean(historyQuery.hasNextPage),
    loadMore: historyQuery.fetchNextPage,
  };
}

/** 查询线程列表并隐藏不应显示的侧栏线程。 */
export function useThreads(
  params: ThreadSearchParams = DEFAULT_THREAD_SEARCH_PARAMS,
) {
  const apiClient = getAPIClient();
  return useQuery<AgentThread[]>({
    ...buildThreadsSearchQueryOptions(apiClient, params),
  });
}

/** 无限滚动线程列表每页获取的记录数。 */
export const INFINITE_THREADS_PAGE_SIZE = 50;

/** 无限分页线程列表查询缓存键的稳定前缀。 */
export const INFINITE_THREADS_QUERY_KEY_PREFIX = [
  "threads",
  "searchInfinite",
] as const;

const INFINITE_THREADS_NEXT_PAGE_PARAM = Symbol(
  "deerflow.infiniteThreads.nextPageParam",
);

type InfiniteThreadsParams = Omit<
  Parameters<ThreadsClient["search"]>[0],
  "limit" | "offset"
>;

type InfiniteThreadsSearchClient = {
  threads: {
    search: ThreadsClient["search"];
  };
};

type InfiniteThreadsPageWithNextParam = AgentThread[] & {
  [INFINITE_THREADS_NEXT_PAGE_PARAM]?: number;
};

/** 为无限分页结果补充本页使用的搜索参数。 */
function annotateInfiniteThreadsPage(
  page: AgentThread[],
  nextPageParam: number | undefined,
): AgentThread[] {
  if (nextPageParam !== undefined) {
    Reflect.set(page, INFINITE_THREADS_NEXT_PAGE_PARAM, nextPageParam);
  }
  return page;
}

/** 获取线程无限列表的一页结果。 */
export async function fetchInfiniteThreadsPage(
  apiClient: InfiniteThreadsSearchClient,
  params: InfiniteThreadsParams,
  pageParam: number,
  pageSize: number = INFINITE_THREADS_PAGE_SIZE,
): Promise<AgentThread[]> {
  const threads: AgentThread[] = [];
  let offset = pageParam;
  let nextPageParam: number | undefined;

  while (threads.length < pageSize) {
    const currentLimit = pageSize - threads.length;
    const response = (await apiClient.threads.search<AgentThreadState>({
      ...params,
      limit: currentLimit,
      offset,
    })) as AgentThread[];

    threads.push(...filterThreadSearchResults(response, params));
    offset += response.length;

    if (response.length < currentLimit) {
      nextPageParam = undefined;
      break;
    }

    nextPageParam = offset;
  }

  return annotateInfiniteThreadsPage(threads, nextPageParam);
}

/** 根据当前页结果计算无限线程查询的下一页参数。 */
export function getInfiniteThreadsNextPageParam(
  lastPage: AgentThread[],
  allPages: AgentThread[][],
  pageSize: number = INFINITE_THREADS_PAGE_SIZE,
): number | undefined {
  const annotatedNextPageParam = Reflect.get(
    lastPage as InfiniteThreadsPageWithNextParam,
    INFINITE_THREADS_NEXT_PAGE_PARAM,
  );
  if (typeof annotatedNextPageParam === "number") {
    return annotatedNextPageParam;
  }

  if (lastPage.length < pageSize) {
    return undefined;
  }
  return allPages.reduce((sum, page) => sum + page.length, 0);
}

/** 对无限线程缓存中的每个页面应用映射函数。 */
export function mapInfiniteThreadsCache(
  oldData: InfiniteData<AgentThread[]> | undefined,
  mapper: (thread: AgentThread) => AgentThread,
): InfiniteData<AgentThread[]> | undefined {
  if (!oldData) {
    return oldData;
  }
  return {
    ...oldData,
    pages: oldData.pages.map((page) => page.map(mapper)),
  };
}

/** 从无限线程缓存中筛除不符合条件的线程。 */
export function filterInfiniteThreadsCache(
  oldData: InfiniteData<AgentThread[]> | undefined,
  predicate: (thread: AgentThread) => boolean,
): InfiniteData<AgentThread[]> | undefined {
  if (!oldData) {
    return oldData;
  }
  return {
    ...oldData,
    pages: oldData.pages.map((page) => page.filter(predicate)),
  };
}

/** 以无限滚动方式查询线程列表。 */
export function useInfiniteThreads(
  params: InfiniteThreadsParams = {
    sortBy: "updated_at",
    sortOrder: "desc",
    select: ["thread_id", "updated_at", "values", "metadata"],
  },
) {
  const apiClient = getAPIClient();
  return useInfiniteQuery<
    AgentThread[],
    Error,
    InfiniteData<AgentThread[]>,
    readonly unknown[],
    number
  >({
    queryKey: [...INFINITE_THREADS_QUERY_KEY_PREFIX, params],
    initialPageParam: 0,
    queryFn: async ({ pageParam }) =>
      fetchInfiniteThreadsPage(
        apiClient,
        params,
        pageParam,
        INFINITE_THREADS_PAGE_SIZE,
      ),
    getNextPageParam: (lastPage, allPages) =>
      getInfiniteThreadsNextPageParam(lastPage, allPages),
    refetchOnWindowFocus: false,
  });
}

/** 查询指定线程的运行记录。 */
export function useThreadRuns(
  threadId?: string,
  { enabled = true }: { enabled?: boolean } = {},
) {
  const apiClient = getAPIClient();
  return useQuery<Run[]>({
    queryKey: ["thread", threadId],
    queryFn: async () => {
      if (!threadId) {
        return [];
      }
      const response = await apiClient.runs.list(threadId);
      return response;
    },
    enabled: enabled && Boolean(threadId),
    refetchOnWindowFocus: false,
  });
}

/** 查询指定线程的元数据。 */
export function useThreadMetadata(
  threadId?: string | null,
  { enabled = true }: { enabled?: boolean } = {},
) {
  const apiClient = getAPIClient();
  return useQuery<AgentThread | null>({
    queryKey: ["thread", "metadata", threadId],
    queryFn: async () => {
      if (!threadId) {
        return null;
      }
      try {
        const response = await apiClient.threads.get(threadId);
        return response as AgentThread;
      } catch (error) {
        if (isThreadMissingError(error)) {
          return null;
        }
        throw error;
      }
    },
    enabled: enabled && Boolean(threadId),
    retry: false,
    refetchOnWindowFocus: false,
  });
}

/** 查询指定线程的累计令牌使用量。 */
export function useThreadTokenUsage(
  threadId?: string | null,
  { enabled = true }: { enabled?: boolean } = {},
) {
  return useQuery<ThreadTokenUsageResponse | null>({
    queryKey: threadTokenUsageQueryKey(threadId),
    queryFn: async () => {
      if (!threadId) {
        return null;
      }
      return fetchThreadTokenUsage(threadId);
    },
    enabled: enabled && Boolean(threadId),
    retry: false,
    refetchOnWindowFocus: false,
  });
}

/** 创建从指定对话轮次分叉线程的变更操作。 */
export function useBranchThread() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      threadId,
      messageId,
      messageIds,
      title,
    }: {
      threadId: string;
      messageId: string;
      messageIds?: string[];
      title?: string;
    }) => branchThreadFromTurn(threadId, { messageId, messageIds, title }),
    /** 分支线程创建后失效源线程与新线程的元数据和列表缓存。 */
    onSuccess(response, { threadId }) {
      void queryClient.invalidateQueries({
        queryKey: ["thread", "metadata", response.thread_id],
      });
      void queryClient.invalidateQueries({
        queryKey: ["thread", "metadata", threadId],
      });
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
      void queryClient.invalidateQueries({
        queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
      });
    },
  });
}

/** 查询指定线程中单次运行的详情。 */
export function useRunDetail(threadId: string, runId: string) {
  const apiClient = getAPIClient();
  return useQuery<Run>({
    queryKey: ["thread", threadId, "run", runId],
    queryFn: async () => {
      const response = await apiClient.runs.get(threadId, runId);
      return response;
    },
    refetchOnWindowFocus: false,
  });
}

/** 删除浏览器中与线程关联的本地数据。 */
async function deleteLocalThreadData(threadId: string) {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}`,
    {
      method: "DELETE",
    },
  );

  // 404 表示线程已不存在，正是期望的最终状态。先前的 `apiClient.threads.delete`
  // 调用命中同一网关处理器（nginx 将 /api/langgraph/threads/* 重写为
  // /api/threads/*）并删除 thread_meta 行，因此第二次删除会被所有权守卫拒绝为
  // 404。将其视为成功，以保持删除操作幂等。
  if (!response.ok && response.status !== 404) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to delete local thread data." }));
    throw new Error(error.detail ?? "Failed to delete local thread data.");
  }
}

/** 在远端与本地删除单个线程。 */
async function deleteThreadEverywhere(
  apiClient: ThreadDeleteClient,
  threadId: string,
) {
  await apiClient.threads.delete(threadId);
  await deleteLocalThreadData(threadId);
}

/** 查找指定父线程关联的所有侧栏线程标识。 */
export async function findSidecarThreadIdsForParent(
  apiClient: ThreadSidecarSearchClient,
  parentThreadId: string,
) {
  const threadIds: string[] = [];
  const limit = 100;
  let offset = 0;

  while (true) {
    const response = await apiClient.threads.search({
      metadata: {
        [SIDECAR_METADATA_KEY]: true,
        parent_thread_id: parentThreadId,
      },
      limit,
      offset,
      sortBy: "updated_at",
      sortOrder: "desc",
      select: ["thread_id", "metadata"],
    });

    for (const thread of response) {
      if (
        isSidecarThread(thread) &&
        thread.metadata?.parent_thread_id === parentThreadId
      ) {
        threadIds.push(thread.thread_id);
      }
    }

    if (response.length < limit) {
      break;
    }
    offset += response.length;
  }

  return threadIds;
}

/** 删除父线程关联的侧栏线程。 */
async function deleteSidecarThreadsForParent(
  apiClient: ThreadDeleteClient,
  parentThreadId: string,
) {
  let sidecarThreadIds: string[];
  try {
    sidecarThreadIds = await findSidecarThreadIdsForParent(
      apiClient,
      parentThreadId,
    );
  } catch (err) {
    console.warn(
      `Failed to look up sidecar threads for parent ${parentThreadId}; skipping cascade cleanup. Orphaned sidecar threads may remain.`,
      err,
    );
    return [];
  }

  const results = await Promise.allSettled(
    sidecarThreadIds.map((threadId) =>
      deleteThreadEverywhere(apiClient, threadId),
    ),
  );

  const failedDeletions = results
    .map((result, index) =>
      result.status === "rejected"
        ? { threadId: sidecarThreadIds[index], reason: result.reason }
        : null,
    )
    .filter((entry): entry is { threadId: string; reason: unknown } =>
      Boolean(entry),
    );

  if (failedDeletions.length > 0) {
    console.warn(
      `Failed to delete ${failedDeletions.length} sidecar thread(s) for parent ${parentThreadId}; orphaned sidecar threads may remain.`,
      failedDeletions,
    );
  }

  return sidecarThreadIds.filter((_, index) => {
    return results[index]?.status === "fulfilled";
  });
}

/** 创建删除线程及其侧栏子线程的变更操作。 */
export function useDeleteThread() {
  const queryClient = useQueryClient();
  const apiClient = getAPIClient() as ThreadDeleteClient;
  return useMutation({
    mutationFn: async ({
      threadId,
      onRemoteDeleted,
    }: {
      threadId: string;
      onRemoteDeleted?: () => void;
    }) => {
      const deletedSidecarThreadIds = await deleteSidecarThreadsForParent(
        apiClient,
        threadId,
      );
      await apiClient.threads.delete(threadId);
      onRemoteDeleted?.();
      await deleteLocalThreadData(threadId);
      return deletedSidecarThreadIds;
    },
    /** 删除成功后从普通列表和分页缓存移除主线程及其侧边线程。 */
    onSuccess(deletedSidecarThreadIds, { threadId }) {
      const deletedThreadIds = new Set([threadId, ...deletedSidecarThreadIds]);
      queryClient.setQueriesData(
        {
          queryKey: ["threads", "search"],
          exact: false,
        },
        (oldData: Array<AgentThread> | undefined) => {
          if (oldData == null) {
            return oldData;
          }
          return oldData.filter((t) => !deletedThreadIds.has(t.thread_id));
        },
      );
      queryClient.setQueriesData(
        {
          queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
          exact: false,
        },
        (oldData: InfiniteData<AgentThread[]> | undefined) =>
          filterInfiniteThreadsCache(
            oldData,
            (t) => !deletedThreadIds.has(t.thread_id),
          ),
      );
    },

    /** 无论删除成功与否都重新验证线程列表，修复可能的缓存偏差。 */
    onSettled() {
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
      void queryClient.invalidateQueries({
        queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
      });
    },
  });
}

/** 创建重命名线程并同步列表缓存的变更操作。 */
export function useRenameThread() {
  const queryClient = useQueryClient();
  const apiClient = getAPIClient();
  return useMutation({
    mutationFn: async ({
      threadId,
      title,
    }: {
      threadId: string;
      title: string;
    }) => {
      await apiClient.threads.updateState(threadId, {
        values: { title },
      });
    },
    /** 重命名成功后同步更新普通列表和无限滚动列表中的线程标题。 */
    onSuccess(_, { threadId, title }) {
      queryClient.setQueriesData(
        {
          queryKey: ["threads", "search"],
          exact: false,
        },
        (oldData: Array<AgentThread>) => {
          return oldData.map((t) => {
            if (t.thread_id === threadId) {
              return {
                ...t,
                values: {
                  ...t.values,
                  title,
                },
              };
            }
            return t;
          });
        },
      );
      queryClient.setQueriesData(
        {
          queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
          exact: false,
        },
        (oldData: InfiniteData<AgentThread[]> | undefined) =>
          mapInfiniteThreadsCache(oldData, (t) =>
            t.thread_id === threadId
              ? {
                  ...t,
                  values: {
                    ...t.values,
                    title,
                  },
                }
              : t,
          ),
      );
    },
  });
}
