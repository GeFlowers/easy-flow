import type { BaseStream } from "@langchain/langgraph-sdk/react";
import { createContext, useContext } from "react";

import type { AgentThreadState } from "@/core/threads";

/** 定义消息子树读取当前线程数据所需的最小上下文契约。 */
export interface ThreadContextType {
  thread: BaseStream<AgentThreadState>;
  isMock?: boolean;
}

/** 线程消息上下文；默认 undefined 使缺失 Provider 的装配错误可被显式识别。 */
export const ThreadContext = createContext<ThreadContextType | undefined>(
  undefined,
);

/** 读取当前线程上下文；必须在消息线程 Provider 的作用域内调用。 */
export function useThread() {
  const context = useContext(ThreadContext);
  if (context === undefined) {
    throw new Error("useThread must be used within a ThreadContext");
  }
  return context;
}
