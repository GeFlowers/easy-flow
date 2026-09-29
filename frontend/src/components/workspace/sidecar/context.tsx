"use client";

import type { Message } from "@langchain/langgraph-sdk";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  appendSidecarReference,
  buildMessageSidecarContext,
  getNextSidecarOpenState,
  type SidecarContext,
  type SidecarReferenceStateItem,
} from "@/core/sidecar";
import { findLatestSidecarThread } from "@/core/sidecar/api";
import type { ThreadStreamOptions } from "@/core/threads/hooks";

export type SidecarReference = SidecarReferenceStateItem;

type SidecarContextValue = {
  open: boolean;
  activeReferences: SidecarReference[];
  conversationQuotes: SidecarReference[];
  parentThreadId: string;
  context: ThreadStreamOptions["context"];
  setContext: (context: ThreadStreamOptions["context"]) => void;
  sidecarThreadId: string | null;
  setSidecarThreadId: (threadId: string | null) => void;
  restoreSidecarThread: (options?: {
    force?: boolean;
  }) => Promise<string | null>;
  addContextToConversation: (context: SidecarContext) => void;
  clearConversationQuotes: (ids?: number[]) => void;
  clearActiveReferences: () => void;
  openSidecar: () => void;
  openContext: (context: SidecarContext) => void;
  openSelectedText: (
    message: Message,
    selectedText: string,
    displayIndex?: number,
  ) => void;
  close: () => void;
};

const SidecarContextObject = createContext<SidecarContextValue | null>(null);

/** 提供侧边对话的线程、草稿与引用状态，并负责与后端恢复结果协调。 */
export function SidecarProvider({
  children,
  parentThreadId,
  context,
}: {
  children: ReactNode;
  parentThreadId: string;
  context: ThreadStreamOptions["context"];
}) {
  const [open, setOpen] = useState(false);
  const [activeReferences, setActiveReferences] = useState<SidecarReference[]>(
    [],
  );
  const [sidecarThreadId, setSidecarThreadId] = useState<string | null>(null);
  const [sidecarContext, setSidecarContext] =
    useState<ThreadStreamOptions["context"]>(context);
  const [conversationQuotes, setConversationQuotes] = useState<
    SidecarReference[]
  >([]);
  const referenceIdRef = useRef(0);
  const parentThreadIdRef = useRef(parentThreadId);
  const sidecarThreadIdRef = useRef<string | null>(null);
  const restoreRequestRef = useRef<{
    parentThreadId: string;
    promise: Promise<string | null>;
  } | null>(null);

  const updateSidecarThreadId = useCallback((threadId: string | null) => {
    sidecarThreadIdRef.current = threadId;
    setSidecarThreadId(threadId);
  }, []);

  const createReference = useCallback((nextContext: SidecarContext) => {
    referenceIdRef.current += 1;
    return {
      id: referenceIdRef.current,
      context: nextContext,
    };
  }, []);

  useEffect(() => {
    if (parentThreadIdRef.current === parentThreadId) {
      return;
    }
    parentThreadIdRef.current = parentThreadId;
    setOpen(false);
    setActiveReferences([]);
    setSidecarContext(context);
    updateSidecarThreadId(null);
    setConversationQuotes([]);
  }, [context, parentThreadId, updateSidecarThreadId]);

  const restoreSidecarThread = useCallback(
    async (options?: { force?: boolean }) => {
      // 非强制恢复信任缓存 id；强制恢复始终重新查询后端，使其他位置删除的
      // 侧边线程能协调为 null，而不是让触发器指向失效线程（#3555）。
      if (!options?.force && sidecarThreadIdRef.current) {
        return sidecarThreadIdRef.current;
      }

      const restoreRequest = restoreRequestRef.current;
      if (restoreRequest?.parentThreadId === parentThreadId) {
        return restoreRequest.promise;
      }

      const promise = findLatestSidecarThread({
        parentThreadId,
      })
        .then((thread) => {
          const threadId = thread?.thread_id ?? null;
          if (parentThreadIdRef.current !== parentThreadId) {
            return null;
          }
          // 将缓存与后端协调：采用新发现的线程；强制刷新时，若后端已无匹配的
          // 侧边线程，则清除过期 id。
          if (threadId) {
            if (!sidecarThreadIdRef.current) {
              updateSidecarThreadId(threadId);
            }
          } else if (options?.force && sidecarThreadIdRef.current) {
            updateSidecarThreadId(null);
          }
          return threadId;
        })
        .catch(() => null)
        .finally(() => {
          if (restoreRequestRef.current?.promise === promise) {
            restoreRequestRef.current = null;
          }
        });

      restoreRequestRef.current = {
        parentThreadId,
        promise,
      };

      return promise;
    },
    [parentThreadId, updateSidecarThreadId],
  );

  useEffect(() => {
    void restoreSidecarThread();
  }, [restoreSidecarThread]);

  const openContext = useCallback(
    (nextContext: SidecarContext) => {
      const nextReference = createReference(nextContext);

      setActiveReferences(
        (references) =>
          getNextSidecarOpenState({
            open,
            sidecarThreadId,
            activeReferences: references,
            nextReference,
          }).activeReferences,
      );
      setOpen(true);
    },
    [createReference, open, sidecarThreadId],
  );

  const addContextToConversation = useCallback(
    (nextContext: SidecarContext) => {
      const nextReference = createReference(nextContext);
      setConversationQuotes((references) =>
        appendSidecarReference(references, nextReference),
      );
    },
    [createReference],
  );

  const clearConversationQuotes = useCallback((ids?: number[]) => {
    if (!ids) {
      setConversationQuotes([]);
      return;
    }
    const idsToClear = new Set(ids);
    setConversationQuotes((quotes) =>
      quotes.filter((quote) => !idsToClear.has(quote.id)),
    );
  }, []);

  const clearActiveReferences = useCallback(() => {
    setActiveReferences([]);
  }, []);

  const openSidecar = useCallback(() => {
    setOpen(true);
  }, []);

  const openSelectedText = useCallback(
    (message: Message, selectedText: string, displayIndex?: number) => {
      const nextContext = buildMessageSidecarContext(message, displayIndex, {
        selectedText,
      });
      if (!nextContext) {
        return;
      }
      openContext(nextContext);
    },
    [openContext],
  );

  const close = useCallback(() => {
    setOpen(false);
  }, []);

  const value = useMemo<SidecarContextValue>(
    () => ({
      open,
      activeReferences,
      conversationQuotes,
      parentThreadId,
      context: sidecarContext,
      setContext: setSidecarContext,
      sidecarThreadId,
      setSidecarThreadId: updateSidecarThreadId,
      restoreSidecarThread,
      addContextToConversation,
      clearConversationQuotes,
      clearActiveReferences,
      openSidecar,
      openContext,
      openSelectedText,
      close,
    }),
    [
      activeReferences,
      addContextToConversation,
      clearActiveReferences,
      clearConversationQuotes,
      close,
      conversationQuotes,
      open,
      openContext,
      openSelectedText,
      openSidecar,
      parentThreadId,
      restoreSidecarThread,
      sidecarContext,
      sidecarThreadId,
      updateSidecarThreadId,
    ],
  );

  return (
    <SidecarContextObject.Provider value={value}>
      {children}
    </SidecarContextObject.Provider>
  );
}

/** 在可选的侧边对话上下文中读取状态，缺失时返回 undefined。 */
export function useMaybeSidecar() {
  return useContext(SidecarContextObject);
}

/** 读取必需的侧边对话上下文，未被 Provider 包裹时抛出错误。 */
export function useSidecar() {
  const context = useMaybeSidecar();
  if (!context) {
    throw new Error("useSidecar must be used within a SidecarProvider");
  }
  return context;
}
