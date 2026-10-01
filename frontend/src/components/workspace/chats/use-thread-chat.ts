"use client";

import { useParams, usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { uuid } from "@/core/utils/uuid";

/** 线程删除后广播本地聊天状态重置的浏览器事件名称。 */
export const THREAD_CHAT_RESET_EVENT = "deer-flow:thread-chat-reset";

type ThreadChatResetDetail = {
  deletedThreadId: string;
  nextPath: string;
  force?: boolean;
};

/** 广播线程删除后的聊天状态重置信号。 */
export function resetThreadChatAfterDelete(detail: ThreadChatResetDetail) {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(
    new CustomEvent<ThreadChatResetDetail>(THREAD_CHAT_RESET_EVENT, {
      detail,
    }),
  );
}

/** 将路由、浏览器路径与本地新建线程状态协调为稳定的聊天线程标识。 */
export function useThreadChat() {
  const { thread_id: threadIdFromPath } = useParams<{ thread_id: string }>();
  const pathname = usePathname();
  // 渲染时以已提交的浏览器 URL 为准；下方同步副作用仍监听响应式路径，
  // 以便渲染期间 window.location 尚未更新时，客户端导航也能安排重置。
  const actualPathname =
    typeof window === "undefined" ? pathname : window.location.pathname;
  const isNewPath = actualPathname.endsWith("/new");
  const newThreadIdRef = useRef<string | null>(
    threadIdFromPath === "new" ? uuid() : null,
  );

  if (isNewPath && !newThreadIdRef.current) {
    newThreadIdRef.current = uuid();
  }

  const [threadId, setThreadIdState] = useState(() => {
    return threadIdFromPath === "new"
      ? (newThreadIdRef.current ?? uuid())
      : threadIdFromPath;
  });

  const [isNewThreadState, setIsNewThreadState] = useState(
    () => threadIdFromPath === "new",
  );

  /** 创建新的临时线程标识，并将聊天状态切换到未创建线程模式。 */
  const resetToNewThread = useCallback(() => {
    const nextThreadId = uuid();
    newThreadIdRef.current = nextThreadId;
    setIsNewThreadState(true);
    setThreadIdState(nextThreadId);
  }, []);

  useEffect(() => {
    if (pathname.endsWith("/new")) {
      const nextThreadId = newThreadIdRef.current ?? uuid();
      newThreadIdRef.current = nextThreadId;
      setIsNewThreadState(true);
      setThreadIdState(nextThreadId);
      return;
    }
    newThreadIdRef.current = null;
    // 原生 history 会更新规范路径但保留路由树，useParams 可能仍返回过期的
    // "new"。不要将其传给下游 Hook（如 useStream），否则会导致 422。
    if (threadIdFromPath === "new") {
      return;
    }
    setIsNewThreadState(false);
    setThreadIdState(threadIdFromPath);
  }, [pathname, threadIdFromPath]);

  useEffect(() => {
    /** 响应线程重置事件；仅当事件对应当前线程时清除本地聊天状态。 */
    const handleReset = (event: Event) => {
      const detail = (event as CustomEvent<ThreadChatResetDetail>).detail;
      if (!detail?.nextPath) {
        return;
      }

      const currentPathname = window.location.pathname;
      const isDeletingCurrentThread =
        detail.force === true ||
        detail.deletedThreadId === threadId ||
        detail.deletedThreadId === threadIdFromPath ||
        currentPathname.endsWith(`/${detail.deletedThreadId}`);

      if (!isDeletingCurrentThread) {
        return;
      }

      // URL 替换由调用方的 Next 路由操作负责；本 Hook 只重置本地聊天状态，
      // 从而让路由状态与浏览器 URL 保持一致。
      resetToNewThread();
    };

    window.addEventListener(THREAD_CHAT_RESET_EVENT, handleReset);
    return () =>
      window.removeEventListener(THREAD_CHAT_RESET_EVENT, handleReset);
  }, [resetToNewThread, threadId, threadIdFromPath]);

  /** 接受已创建的线程标识，并清除尚未提交的新线程标记。 */
  const setThreadId = useCallback((nextThreadId: string) => {
    newThreadIdRef.current = null;
    setThreadIdState(nextThreadId);
  }, []);

  /** 更新新线程状态，并在进入已有线程时丢弃临时线程标识。 */
  const setIsNewThread = useCallback((nextIsNewThread: boolean) => {
    if (!nextIsNewThread) {
      newThreadIdRef.current = null;
    }
    setIsNewThreadState(nextIsNewThread);
  }, []);

  return {
    threadId: isNewPath ? (newThreadIdRef.current ?? threadId) : threadId,
    setThreadId,
    isNewThread: isNewPath ? true : isNewThreadState,
    setIsNewThread,
  };
}
