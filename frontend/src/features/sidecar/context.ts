import type { Message } from "@langchain/langgraph-sdk";

import {
  extractTextFromMessage,
  isHiddenFromUIMessage,
} from "@/features/messages/utils";

/** 可被侧栏引用的消息角色。 */
export type SidecarContextRole = "user" | "assistant";

/** 来自主会话单条消息或其选中文本的侧栏引用。 */
export type ReferencedMessageSidecarContext = {
  type: "referenced_message";
  label: string;
  messageId?: string;
  role: SidecarContextRole;
  content: string;
};

/** 当前仅支持的侧栏上下文联合类型，为后续上下文来源预留扩展点。 */
export type SidecarContext = ReferencedMessageSidecarContext;

/** 侧栏提示词中作为只读背景附带的主会话消息。 */
export type ParentConversationContextMessage = {
  messageId?: string;
  role: SidecarContextRole;
  content: string;
};

/** 将单个侧栏上下文统一转换为数组，保留调用方提供的顺序和内容。 */
export function normalizeSidecarContexts(
  contextOrContexts: SidecarContext | SidecarContext[],
): SidecarContext[] {
  return Array.isArray(contextOrContexts)
    ? contextOrContexts
    : [contextOrContexts];
}

/** 解析消息可作为侧栏上下文时对应的角色。 */
function roleOfMessage(message: Message): SidecarContextRole | null {
  if (message.type === "human") {
    return "user";
  }
  if (message.type === "ai") {
    return "assistant";
  }
  return null;
}

/** 返回侧栏提示词中使用的上下文角色标签。 */
function labelOfRole(role: SidecarContextRole) {
  return role === "user" ? "User" : "Assistant";
}

/** 在保留首尾语义的前提下截断过长上下文。 */
function truncateContextText(content: string, maxChars: number) {
  if (content.length <= maxChars) {
    return content;
  }
  return `${content.slice(0, maxChars).trimEnd()}\n[已截断]`;
}

/** 从父会话构建可供侧栏任务引用的上下文片段。 */
export function buildParentConversationContext(
  messages: Message[],
  {
    maxMessages = 8,
    maxCharsPerMessage = 1200,
    maxTotalChars = 6000,
  }: {
    maxMessages?: number;
    maxCharsPerMessage?: number;
    maxTotalChars?: number;
  } = {},
): ParentConversationContextMessage[] {
  const visibleMessages = messages.flatMap((message) => {
    const role = roleOfMessage(message);
    if (!role || isHiddenFromUIMessage(message)) {
      return [];
    }
    const content = extractTextFromMessage(message).trim();
    if (!content) {
      return [];
    }
    return [
      {
        messageId: message.id,
        role,
        content,
      },
    ];
  });

  const recentMessages = visibleMessages.slice(-maxMessages);
  const selectedMessages: ParentConversationContextMessage[] = [];
  let selectedChars = 0;

  for (let index = recentMessages.length - 1; index >= 0; index -= 1) {
    const message = recentMessages[index];
    if (!message) {
      continue;
    }
    const remainingChars = Math.max(maxTotalChars - selectedChars, 0);
    if (remainingChars <= 0) {
      break;
    }
    const content = truncateContextText(
      message.content,
      Math.min(maxCharsPerMessage, remainingChars),
    );
    selectedMessages.unshift({
      ...message,
      content,
    });
    selectedChars += content.length;
  }

  return selectedMessages;
}

/** 将单条消息转换为侧栏可引用的上下文。 */
export function buildMessageSidecarContext(
  message: Message,
  displayIndex?: number,
  {
    selectedText,
  }: {
    selectedText?: string;
  } = {},
): ReferencedMessageSidecarContext | null {
  const role = roleOfMessage(message);
  const content = selectedText?.trim() ?? extractTextFromMessage(message);
  if (!role || !content || isHiddenFromUIMessage(message)) {
    return null;
  }

  const prefix = selectedText
    ? role === "assistant"
      ? "选中的助手文本"
      : "选中的用户文本"
    : role === "assistant"
      ? "助手消息"
      : "用户消息";
  return {
    type: "referenced_message",
    label:
      typeof displayIndex === "number" ? `${prefix} #${displayIndex}` : prefix,
    messageId: message.id,
    role,
    content,
  };
}

/** 转义写入标记属性的上下文值。 */
function escapeXmlAttribute(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/** 将已选侧栏引用序列化为供模型使用的提示词。 */
export function buildSidecarContextPrompt(
  contextOrContexts: SidecarContext | SidecarContext[] = [],
  {
    parentConversation = [],
  }: {
    parentConversation?: ParentConversationContextMessage[];
  } = {},
) {
  const contexts = normalizeSidecarContexts(contextOrContexts);
  const lines = [
    "你正在回答一个附属于当前 DeerFlow 对话引用内容的侧边对话问题。",
    parentConversation.length > 0
      ? "parent_conversation_context 块是主对话的只读背景，可用于理解目标、约束和代词指代，但不能当作用户最新的问题。"
      : null,
    contexts.length === 1
      ? "用户附加了 1 条引用消息，请将其视为引用材料。"
      : contexts.length === 0
        ? "用户没有为这个侧边问题附加新的引用消息。"
        : `用户附加了 ${contexts.length} 条引用消息，请将每个 referenced_message 块视为独立的引用材料。`,
    contexts.length > 0
      ? "优先依据引用材料回答；只有用户明确要求时，才使用更广泛的对话背景。"
      : "只将 parent_conversation_context 用作理解用户最新侧边问题的连续背景。",
    "只回答用户最新的侧边问题。",
    "除非用户明确要求将内容带回主对话，否则不要声称你修改了主对话。",
    "",
    parentConversation.length > 0
      ? `<parent_conversation_context message_count="${parentConversation.length}">`
      : null,
    ...parentConversation.flatMap((message, index) =>
      [
        `<parent_message index="${index + 1}" role="${labelOfRole(
          message.role,
        )}"${
          message.messageId
            ? ` message_id="${escapeXmlAttribute(message.messageId)}"`
            : ""
        }>`,
        message.content,
        "</parent_message>",
        "",
      ].filter((line): line is string => line !== null),
    ),
    parentConversation.length > 0 ? "</parent_conversation_context>" : null,
    parentConversation.length > 0 ? "" : null,
    ...contexts.flatMap((context, index) =>
      [
        `<referenced_message index="${index + 1}" label="${escapeXmlAttribute(
          context.label,
        )}">`,
        `角色：${context.role === "user" ? "用户" : "助手"}`,
        context.messageId ? `消息编号：${context.messageId}` : null,
        "",
        context.content,
        "</referenced_message>",
        "",
      ].filter((line): line is string => line !== null),
    ),
  ].filter((line): line is string => line !== null);

  return lines.join("\n").trim();
}
