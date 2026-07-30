import type { SidecarContext, SidecarContextRole } from "./context";

/** 持久化到消息附加字段中的单条侧栏引用上下文。 */
export type ReferenceMessageContextMetadata = {
  label: string;
  message_id?: string;
  role: SidecarContextRole;
  content: string;
};

/** 写入消息附加字段的侧栏引用元数据，平行数组须与引用集合保持相同顺序。 */
export type ReferenceMessageMetadata = {
  referenced_message_count: number;
  referenced_message_ids: string[];
  referenced_message_roles: SidecarContextRole[];
  referenced_message_contexts: ReferenceMessageContextMetadata[];
};

/** 校验值是否为允许写入引用元数据的侧栏上下文角色。 */
function isSidecarContextRole(value: unknown): value is SidecarContextRole {
  return value === "user" || value === "assistant";
}

/** 将侧栏上下文编码为可附加到消息的引用元数据。 */
export function buildReferenceMessageMetadata(
  contexts: SidecarContext[],
): ReferenceMessageMetadata {
  // 引用计数、标识与角色和引用集合保持一一对齐，消费者可安全按位置组合；不可在此去重标识，以免同源片段破坏数组对齐。
  return {
    referenced_message_count: contexts.length,
    referenced_message_ids: contexts.map((context) => context.messageId ?? ""),
    referenced_message_roles: contexts.map((context) => context.role),
    referenced_message_contexts: contexts.map((context) => ({
      label: context.label,
      ...(context.messageId ? { message_id: context.messageId } : {}),
      role: context.role,
      content: context.content,
    })),
  };
}

/** 判断未知值是否为普通对象记录。 */
function isObjectRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** 从消息元数据安全读取已持久化的侧栏引用上下文。 */
export function readReferenceMessageContexts(
  additionalKwargs: unknown,
): SidecarContext[] {
  if (!isObjectRecord(additionalKwargs)) {
    return [];
  }

  const rawContexts = additionalKwargs.referenced_message_contexts;
  if (!Array.isArray(rawContexts)) {
    return [];
  }

  return rawContexts.flatMap((rawContext) => {
    if (
      !isObjectRecord(rawContext) ||
      typeof rawContext.label !== "string" ||
      typeof rawContext.content !== "string" ||
      !isSidecarContextRole(rawContext.role)
    ) {
      return [];
    }

    return [
      {
        type: "referenced_message",
        label: rawContext.label,
        ...(typeof rawContext.message_id === "string"
          ? { messageId: rawContext.message_id }
          : {}),
        role: rawContext.role,
        content: rawContext.content,
      },
    ];
  });
}
