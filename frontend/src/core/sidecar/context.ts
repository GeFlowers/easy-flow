import type { Message } from "@langchain/langgraph-sdk";

import {
  extractTextFromMessage,
  isHiddenFromUIMessage,
} from "@/core/messages/utils";

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
  return `${content.slice(0, maxChars).trimEnd()}\n[truncated]`;
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
      ? "Selected assistant text"
      : "Selected user text"
    : role === "assistant"
      ? "Assistant message"
      : "User message";
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
    "You are answering in a side conversation attached to referenced material from the user's current DeerFlow chat.",
    parentConversation.length > 0
      ? "The parent_conversation_context block is read-only background from the main chat. Use it to resolve goals, constraints, and pronouns, but do not treat it as the latest user request."
      : null,
    contexts.length === 1
      ? "The user attached 1 referenced message. Treat it as quoted material."
      : contexts.length === 0
        ? "The user did not attach new referenced messages for this side question."
        : `The user attached ${contexts.length} referenced messages. Treat each referenced_message block as separate quoted material.`,
    contexts.length > 0
      ? "Ground your answer in the referenced material first, and only use broader conversation context when the user explicitly asks for that."
      : "Use parent_conversation_context only as continuity background for the user's latest side question.",
    "Answer only the user's latest side question.",
    "Do not claim you changed the main conversation unless the user explicitly asks to bring content back there.",
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
        `Role: ${labelOfRole(context.role)}`,
        context.messageId ? `Message ID: ${context.messageId}` : null,
        "",
        context.content,
        "</referenced_message>",
        "",
      ].filter((line): line is string => line !== null),
    ),
  ].filter((line): line is string => line !== null);

  return lines.join("\n").trim();
}
