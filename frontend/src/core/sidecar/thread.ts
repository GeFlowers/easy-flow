import type { AgentThread } from "@/core/threads";

import { normalizeSidecarContexts, type SidecarContext } from "./context";

/** 线程元数据中标记侧栏会话的固定字段名。 */
export const SIDECAR_METADATA_KEY = "deerflow_sidecar";

/** 标识侧栏线程、父线程和所引用内容的持久化元数据。 */
export type SidecarThreadMetadata = {
  [SIDECAR_METADATA_KEY]: true;
  parent_thread_id: string;
  sidecar_context_type: SidecarContext["type"];
  sidecar_context_label: string;
  sidecar_context_count: number;
  referenced_message_id?: string;
  referenced_message_ids: string[];
  referenced_message_role: SidecarContext["role"];
  referenced_message_roles: SidecarContext["role"][];
};

/** 构建用于标识侧栏线程及其父线程的元数据。 */
export function buildSidecarThreadMetadata(
  parentThreadId: string,
  contextOrContexts: SidecarContext | SidecarContext[],
): SidecarThreadMetadata {
  const contexts = normalizeSidecarContexts(contextOrContexts);
  const primaryContext = contexts[0];
  if (!primaryContext) {
    throw new Error("At least one sidecar context is required.");
  }

  // 引用消息标识、角色和计数必须与引用集合一一平行，消费者才能安全按位置组合；同源片段会使去重后的标识数组失去对齐。
  const referencedMessageIds = contexts.map(
    (context) => context.messageId ?? "",
  );

  return {
    [SIDECAR_METADATA_KEY]: true,
    parent_thread_id: parentThreadId,
    sidecar_context_type: primaryContext.type,
    sidecar_context_label: primaryContext.label,
    sidecar_context_count: contexts.length,
    referenced_message_id: primaryContext.messageId,
    referenced_message_ids: referencedMessageIds,
    referenced_message_role: primaryContext.role,
    referenced_message_roles: contexts.map((context) => context.role),
  };
}

/** 判断线程是否携带有效的侧栏线程元数据。 */
export function isSidecarThread(
  thread:
    | Pick<AgentThread, "metadata">
    | { metadata?: Record<string, unknown> },
) {
  return thread.metadata?.[SIDECAR_METADATA_KEY] === true;
}

/** 判断线程是否应出现在主会话列表中。 */
export function shouldShowInPrimaryThreadLists(
  thread:
    | Pick<AgentThread, "metadata">
    | { metadata?: Record<string, unknown> },
) {
  return !isSidecarThread(thread);
}
