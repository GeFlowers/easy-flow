"use client";

import { Client as LangGraphClient } from "@langchain/langgraph-sdk/client";

import { getLangGraphBaseURL } from "../config";
import { isStaticWebsiteOnly } from "../static-mode";
import {
  loadStaticDemoThread,
  loadStaticDemoThreads,
  staticDemoThreadState,
} from "../threads/static-demo";
import type { AgentThreadState } from "../threads/types";

import { isStateChangingMethod, readCsrfCookie } from "./fetcher";
import { sanitizeRunStreamOptions } from "./stream-mode";

/**
 * SDK 的 ``onRequest`` 钩子：每次发起出站请求前，从当前 ``csrf_token``
 * Cookie 生成 ``X-CSRF-Token`` 请求头。
 *
 * 每次请求读取 Cookie（而非在构造 SDK 时写入 ``defaultHeaders``）可透明处理
 * 登录、登出及修改密码导致的 Cookie 轮换。``/api/langgraph/*`` SDK 路径和
 * ``fetcher.ts:fetchWithAuth`` 中的直连 REST 端点共用
 * :func:`readCsrfCookie` 与 :const:`STATE_CHANGING_METHODS`，从而保持该约定同步。
 */
function injectCsrfHeader(_url: URL, init: RequestInit): RequestInit {
  if (!isStateChangingMethod(init.method ?? "GET")) {
    return init;
  }
  const token = readCsrfCookie();
  if (!token) return init;
  const headers = new Headers(init.headers);
  if (!headers.has("X-CSRF-Token")) {
    headers.set("X-CSRF-Token", token);
  }
  return { ...init, headers };
}

// 已到达终态、无法继续流式传输的运行状态。对此类运行调用重连（``joinStream``）
// 要么会得到 409，要么会在后端回收内存流桥接器后（``worker.py`` 对所有运行，
// 包括被中断的运行，都会无条件调用 ``publish_end``，再于 60 秒后回收桥接器），
// 永久阻塞在已耗尽的条件变量上。这会让 ``isLoading`` 一直为 true，使提交按钮
// 保持“停止”状态，并导致刷新后的第一条消息无法发送。下方 ``joinStream`` 包装器
// 会在真正加入流之前短路这些情形。
//
// 包含 ``interrupted``，因为它在 DeerFlow 中只由 ``RunManager.cancel()`` 写入
// （即用户主动停止）；可恢复的人机交互路径使用
// ``Command(goto=END)``（``ClarificationMiddleware``），会将运行以
// ``success`` 而非 ``interrupted`` 结束。因此，被中断的运行已没有内容可流式传输：
// 其状态保存在由 ``useThreadHistory`` 独立获取的检查点中，恢复意味着重新 ``submit``。
//
// 错误和超时状态同样是终态，因此在约 60 秒的桥接器回收窗口内刷新页面时，
// 不再会通过 ``onError`` 重放缓冲的错误事件，临时错误提示
// （``getStreamErrorMessage``）会被丢弃。持久化的错误状态仍由
// ``useThreadHistory`` 从检查点加载，因此损失的只有提示；这是有意为之，
// 因为每次刷新都显示陈旧错误提示只会制造噪音。
const TERMINAL_RUN_STATUSES = new Set([
  "success",
  "error",
  "timeout",
  "interrupted",
]);

/**
 * Gateway 409 冲突响应的共享匹配器。SDK 将非 2xx 响应呈现为
 * ``HTTPError { status, message }``，其中 ``message`` 形如
 * ``"HTTP 409: {\"detail\":\"...\"}"``，所以既可通过数值 ``status``，也可通过
 * ``message`` 子串检测 409。
 *
 * 传入的每个 ``needles`` 子串都必须存在；这一“与”语义让调用方可凭措辞区分并列的
 * 冲突分支（例如，区分终态取消分支与仍在另一工作进程中活动的分支）。
 *
 * 在 API 提供结构化错误码前先匹配字符串；事实来源是
 * ``backend/app/gateway/routers/thread_runs.py`` 中的
 * ``_cancel_conflict_detail`` / 仅存储响应。
 */
function isRunConflictError(error: unknown, ...needles: string[]): boolean {
  const status =
    typeof error === "object" && error !== null
      ? Reflect.get(error, "status")
      : undefined;
  const message =
    typeof error === "string"
      ? error
      : error instanceof Error
        ? error.message
        : typeof error === "object" && error !== null
          ? String(Reflect.get(error, "message") ?? "")
          : "";

  return (
    (status === 409 || message.includes("HTTP 409")) &&
    needles.every((needle) => message.includes(needle))
  );
}

// 仅存储的运行无法流式传输（此工作进程没有内存流桥接器），重连时没有流可加入。
/** 判断错误是否表示运行不在当前工作进程中，因而无法重新加入流。 */
export function isInactiveRunStreamError(error: unknown): boolean {
  return isRunConflictError(
    error,
    "not active on this worker",
    "cannot be streamed",
  );
}

/**
 * 匹配 Gateway 的终态取消冲突：当 ``RunManager.cancel`` 拒绝已结束的运行时，
 * ``backend/app/gateway/routers/thread_runs.py`` 中的
 * ``_cancel_conflict_detail`` 会返回
 * “运行 X 不可取消（状态：成功、错误或超时）”。
 *
 * 有意不匹配“运行不在当前工作进程中且无法取消”的并列分支：
 * 在多实例部署中，它表示运行仍在另一工作进程中等待或执行，是活动运行的真实取消失败，
 * 必须对用户可见。只有终态分支才是真正的无操作。
 */
export function isRunNotCancellableError(error: unknown): boolean {
  return isRunConflictError(error, "is not cancellable");
}

/**
 * 重连预检：如果运行已到达终态，就没有流可加入。当调用方应跳过底层
 * ``joinStream`` 时返回 ``true``，使 SDK 的 ``onSuccess`` 路径执行并将
 * ``isLoading`` 复位为 false，避免永久阻塞在已耗尽的流桥接器上。
 *
 * 任意错误（被驱逐记录的 404、短暂网络故障、认证异常等）都会回退至原始加入逻辑，
 * 以免合法活动的重连被静默抑制。
 */
async function shouldSkipReconnect(
  client: LangGraphClient,
  threadId: string,
  runId: string,
): Promise<boolean> {
  try {
    const run = await client.runs.get(threadId, runId);
    return TERMINAL_RUN_STATUSES.has(run.status);
  } catch {
    return false;
  }
}

/** 仅在会话存储仍指向指定运行时，清除该线程的陈旧重连标记。 */
export function clearReconnectRun(
  threadId: string | null | undefined,
  runId: string,
): void {
  if (typeof window === "undefined" || !threadId) return;

  const key = `lg:stream:${threadId}`;
  try {
    const storage = window.sessionStorage;
    if (storage.getItem(key) === runId) {
      storage.removeItem(key);
    }
  } catch {
    // 忽略存储访问失败，确保清理重连状态本身永不抛错。
  }
}

/** 创建兼容 Gateway、CSRF 保护、终态重连和流模式约束的 LangGraph 客户端。 */
function createCompatibleClient(isMock?: boolean): LangGraphClient {
  if (isStaticWebsiteOnly() && !isMock) {
    return createStaticClient();
  }

  const apiUrl = getLangGraphBaseURL(isMock);
  console.log(`Creating API client with base URL: ${apiUrl}`);
  const client = new LangGraphClient({
    apiUrl,
    onRequest: injectCsrfHeader,
  });

  const originalRunStream = client.runs.stream.bind(client.runs);
  client.runs.stream = ((threadId, assistantId, payload) =>
    originalRunStream(
      threadId,
      assistantId,
      sanitizeRunStreamOptions(payload),
    )) as typeof client.runs.stream;

  const originalCancel = client.runs.cancel.bind(client.runs);
  client.runs.cancel = (async (threadId, runId, wait, action, options) => {
    try {
      return await originalCancel(threadId, runId, wait, action, options);
    } catch (error) {
      if (isRunNotCancellableError(error)) {
        // 运行已到达终态，取消操作是无操作。吞掉 409，避免在结束窗口内点击停止
        // （后端已切换为 ``success``，但 SSE 流尚未排空）时出现未处理的拒绝；同时
        // 清除已陈旧的重连键。clearReconnectRun 仅在键仍匹配该 runId 时删除，
        // 因此绝不会误触及更新运行的键。
        clearReconnectRun(threadId, runId);
        return;
      }
      throw error;
    }
  }) as typeof client.runs.cancel;

  const originalJoinStream = client.runs.joinStream.bind(client.runs);
  client.runs.joinStream = async function* (threadId, runId, options) {
    // 短路已结束运行的重连：否则，在后端回收流桥接器后刷新页面会永久阻塞在已耗尽的
    // 条件变量上，使 ``isLoading`` 固定为 true，刷新后的第一条消息会被路由到
    // ``stop`` 而非 ``submit``。
    if (threadId && (await shouldSkipReconnect(client, threadId, runId))) {
      clearReconnectRun(threadId, runId);
      return;
    }
    try {
      yield* originalJoinStream(
        threadId,
        runId,
        sanitizeRunStreamOptions(options),
      );
    } catch (error) {
      if (isInactiveRunStreamError(error)) {
        clearReconnectRun(threadId, runId);
        return;
      }
      throw error;
    }
  } as typeof client.runs.joinStream;

  return client;
}

/** 创建供静态网站演示模式使用的本地 LangGraph 客户端替身。 */
function createStaticClient(): LangGraphClient {
  const apiUrl =
    typeof window === "undefined"
      ? "http://localhost:3000"
      : window.location.origin;
  const client = new LangGraphClient({ apiUrl });

  client.threads.search = (async (query) => {
    return loadStaticDemoThreads(query);
  }) as typeof client.threads.search;

  client.threads.get = (async (threadId) => {
    return loadStaticDemoThread(threadId);
  }) as typeof client.threads.get;

  client.threads.getState = (async (threadId) => {
    return staticDemoThreadState(await loadStaticDemoThread(threadId));
  }) as typeof client.threads.getState;

  client.threads.getHistory = (async (threadId) => {
    return [staticDemoThreadState(await loadStaticDemoThread(threadId))];
  }) as typeof client.threads.getHistory;

  client.threads.update = (async (threadId) => {
    return loadStaticDemoThread(threadId);
  }) as typeof client.threads.update;

  client.runs.list = (async () => []) as typeof client.runs.list;
  client.runs.stream = async function* () {
    /* 静态演示模式没有运行流。 */
  } as typeof client.runs.stream;
  client.runs.joinStream = async function* () {
    /* 静态演示模式没有可重新加入的运行流。 */
  } as typeof client.runs.joinStream;

  return client as LangGraphClient<AgentThreadState>;
}

const _clients = new Map<string, LangGraphClient>();
/** 按普通或模拟模式获取并缓存唯一的兼容 LangGraph 客户端。 */
export function getAPIClient(isMock?: boolean): LangGraphClient {
  const cacheKey = isMock ? "mock" : "default";
  let client = _clients.get(cacheKey);

  if (!client) {
    client = createCompatibleClient(isMock);
    _clients.set(cacheKey, client);
  }

  return client;
}
