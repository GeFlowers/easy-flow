import type { AIMessage, Message } from "@langchain/langgraph-sdk";

interface GenericMessageGroup<T = string> {
  type: T;
  id: string | undefined;
  messages: Message[];
}

interface HumanMessageGroup extends GenericMessageGroup<"human"> {}

interface AssistantProcessingGroup extends GenericMessageGroup<"assistant:processing"> {}

interface AssistantMessageGroup extends GenericMessageGroup<"assistant"> {}

interface AssistantPresentFilesGroup extends GenericMessageGroup<"assistant:present-files"> {}

interface AssistantClarificationGroup extends GenericMessageGroup<"assistant:clarification"> {}

interface AssistantSubagentGroup extends GenericMessageGroup<"assistant:subagent"> {}

/** 按人类回合、助手处理、回答、澄清、文件展示或子代理划分的消息组。 */
export type MessageGroup =
  | HumanMessageGroup
  | AssistantProcessingGroup
  | AssistantMessageGroup
  | AssistantPresentFilesGroup
  | AssistantClarificationGroup
  | AssistantSubagentGroup;

const HIDDEN_CONTROL_MESSAGE_NAMES = new Set([
  "summary",
  "loop_warning",
  "todo_reminder",
  "todo_completion_reminder",
]);

/** 过滤隐藏消息，并按 UI 语义将消息归组以保持工具调用关联。 */
export function getMessageGroups(messages: Message[]): MessageGroup[] {
  if (messages.length === 0) {
    return [];
  }

  const groups: MessageGroup[] = [];

  // 若最后一个分组仍可接收工具消息则返回它，即正在处理中的分组，而非终态的人类或助手分组。
  /** 返回仍可接收后续工具消息的末尾分组；终态分组不再复用。 */
  function lastOpenGroup() {
    const last = groups[groups.length - 1];
    if (
      last &&
      last.type !== "human" &&
      last.type !== "assistant" &&
      last.type !== "assistant:clarification"
    ) {
      return last;
    }
    return null;
  }

  for (const message of messages) {
    if (isHiddenFromUIMessage(message)) {
      continue;
    }

    if (message.type === "human") {
      groups.push({ id: message.id, type: "human", messages: [message] });
      continue;
    }

    if (message.type === "tool") {
      if (isClarificationToolMessage(message)) {
        // 加入前一个处理分组以保留工具调用关联，同时新建独立的澄清分组以突出显示。
        lastOpenGroup()?.messages.push(message);
        groups.push({
          id: message.id,
          type: "assistant:clarification",
          messages: [message],
        });
      } else {
        const open = lastOpenGroup();
        if (open) {
          open.messages.push(message);
        } else {
          // 孤立工具消息的回退处理：LangGraph `messages-tuple` 可能乱序发送工具结果
          // 事件，或从子代理状态重放它们（例如 LocalSandboxProvider 下启用
          // allow_host_bash 的 bash 子代理）。此时工具消息会出现在终态分组之后，
          // lastOpenGroup() 返回 null。此前会用 console.error 丢弃该消息，使工具
          // 结果在 UI 中被悄然隐藏；现改为附加至最近分组，确保用户仍能看到代理所做的操作。
          const lastGroup = groups[groups.length - 1];
          if (lastGroup) {
            lastGroup.messages.push(message);
          } else {
            // groups 为空本不应发生：外层循环已由 `messages.length === 0 -> return []`
            // 保护；仍保留诊断信息以防万一。
            console.error(
              "Unexpected tool message with no preceding group",
              message,
            );
          }
        }
      }
      continue;
    }

    if (message.type === "ai") {
      // 含回答内容且没有工具调用的消息会成为下方独立的助手气泡；该气泡已在其
      // <Reasoning> 折叠区渲染消息的 reasoning_content。此类消息不得再进入处理分组，
      // 否则气泡上方的 ChainOfThought 面板会重复渲染相同推理（#3868）。不含内容的
      // 中间推理以及工具调用步骤仍应归入处理分组。
      const becomesAssistantBubble =
        hasContent(message) && !hasToolCalls(message);

      if (hasPresentFiles(message)) {
        groups.push({
          id: message.id,
          type: "assistant:present-files",
          messages: [message],
        });
      } else if (hasSubagent(message)) {
        groups.push({
          id: message.id,
          type: "assistant:subagent",
          messages: [message],
        });
      } else if (
        !becomesAssistantBubble &&
        (hasReasoning(message) || hasToolCalls(message))
      ) {
        const lastGroup = groups[groups.length - 1];
        // 将连续的中间 AI 消息累积到同一个处理分组中。
        if (lastGroup?.type !== "assistant:processing") {
          groups.push({
            id: message.id,
            type: "assistant:processing",
            messages: [message],
          });
        } else {
          lastGroup.messages.push(message);
        }
      }

      if (becomesAssistantBubble) {
        groups.push({ id: message.id, type: "assistant", messages: [message] });
      }
    }
  }

  return groups;
}

/** 找出每个已完成可见回合中允许从最终助手回答分支的分组 ID。 */
export function getBranchableAssistantGroupIds(
  groups: MessageGroup[],
  isCurrentTurnLoading: boolean,
): Set<string> {
  // getMessageGroups 已移除隐藏消息，与后端分支检查点的可见性规则一致。每个可见
  // 人类回合中，只有最后一个包含 AI 消息的分组为终态助手文本分组时才提供分支操作。
  // 处理、文件展示和子代理分组均不渲染助手操作。
  const branchableGroupIds = new Set<string>();
  let lastAIGroup: MessageGroup | null = null;

  /** 结束当前可见回合，并在末尾分组是助手回答时记录其可分支标识。 */
  const completeTurn = () => {
    if (lastAIGroup?.type === "assistant" && lastAIGroup.id) {
      branchableGroupIds.add(lastAIGroup.id);
    }
    lastAIGroup = null;
  };

  for (const group of groups) {
    if (group.type === "human") {
      completeTurn();
      continue;
    }

    if (group.messages.some((message) => message.type === "ai")) {
      lastAIGroup = group;
    }
  }

  if (!isCurrentTurnLoading) {
    completeTurn();
  }

  return branchableGroupIds;
}

/** 按 UI 消息分组映射结果并移除空值。 */
export function groupMessages<T>(
  messages: Message[],
  mapper: (group: MessageGroup) => T,
): T[] {
  return getMessageGroups(messages)
    .map(mapper)
    .filter((result) => result !== undefined && result !== null) as T[];
}

/** 为每个助手回合结束分组收集该回合全部 AI 消息，以归集令牌用量。 */
export function getAssistantTurnUsageMessages(groups: MessageGroup[]) {
  const usageMessagesByGroupIndex: Array<Message[] | null> = Array.from(
    { length: groups.length },
    () => null,
  );

  let turnStartIndex: number | null = null;

  for (const [index, group] of groups.entries()) {
    if (group.type === "human") {
      turnStartIndex = null;
      continue;
    }

    turnStartIndex ??= index;

    const nextGroup = groups[index + 1];
    const isTurnEnd = !nextGroup || nextGroup.type === "human";

    if (!isTurnEnd) {
      continue;
    }

    usageMessagesByGroupIndex[index] = groups
      .slice(turnStartIndex, index + 1)
      .flatMap((currentGroup) => currentGroup.messages)
      .filter((message) => message.type === "ai");

    turnStartIndex = null;
  }

  return usageMessagesByGroupIndex;
}

type MessageMetadataLookup = (
  message: Message,
  index: number,
) => { streamMetadata?: Record<string, unknown> } | undefined;

/** 以消息 ID 和对象引用双重识别流式消息的查询表。 */
export type StreamingMessageLookup = {
  ids: ReadonlySet<string>;
  messages: ReadonlySet<Message>;
};

/** 从流元数据建立流式消息查询表，兼容 ID 与对象引用两种匹配方式。 */
export function getStreamingMessageLookup(
  messages: Message[],
  isStreaming: boolean,
  getMessagesMetadata?: MessageMetadataLookup,
): StreamingMessageLookup {
  const streamingMessageIds = new Set<string>();
  const streamingMessages = new Set<Message>();

  if (!isStreaming) {
    return {
      ids: streamingMessageIds,
      messages: streamingMessages,
    };
  }

  messages.forEach((message, index) => {
    if (!getMessagesMetadata?.(message, index)?.streamMetadata) {
      return;
    }

    if (typeof message.id === "string" && message.id.length > 0) {
      streamingMessageIds.add(message.id);
    }
    streamingMessages.add(message);
  });

  return {
    ids: streamingMessageIds,
    messages: streamingMessages,
  };
}

/** 判断助手消息组中是否包含仍在流式输出的 AI 消息。 */
export function isAssistantMessageGroupStreaming(
  groupMessages: Message[],
  streamingMessages: StreamingMessageLookup,
) {
  return groupMessages.some((message) => {
    if (message.type !== "ai") {
      return false;
    }

    return (
      (typeof message.id === "string" &&
        message.id.length > 0 &&
        streamingMessages.ids.has(message.id)) ||
      streamingMessages.messages.has(message)
    );
  });
}

/** 返回助手回合最后一段可复制内容；流式期间不提供复制数据。 */
export function getAssistantTurnCopyData(
  messages: Message[],
  { isStreaming = false }: { isStreaming?: boolean } = {},
) {
  if (isStreaming) {
    return null;
  }

  return (
    [...messages]
      .reverse()
      .filter((message) => message.type === "ai")
      .map((message) => {
        const content = extractContentFromMessage(message);
        return content ?? extractReasoningContentFromMessage(message) ?? "";
      })
      .find((content) => content.length > 0) ?? null
  );
}

/** 提取单条消息的可复制内容，并移除人类消息中的上传文件标签。 */
export function getMessageCopyData(message: Message) {
  const content = extractContentFromMessage(message);
  if (message.type === "human") {
    return stripUploadedFilesTag(content);
  }
  if (content.length > 0) {
    return content;
  }
  return extractReasoningContentFromMessage(message) ?? "";
}

/** 从字符串或多模态消息内容中拼接纯文本，供摘要和复制流程使用。 */
export function extractTextFromMessage(message: Message) {
  if (typeof message.content === "string") {
    return (
      splitInlineReasoningFromAIMessage(message)?.content ??
      message.content.trim()
    );
  }
  if (Array.isArray(message.content)) {
    return message.content
      .map((content) =>
        typeof content === "string"
          ? content
          : content.type === "text"
            ? content.text
            : "",
      )
      .join("\n")
      .trim();
  }
  return "";
}

const THINK_OPEN_TAG = "<think>";
const THINK_TAG_RE = /<think>\s*([\s\S]*?)\s*<\/think>/g;

/** 拆分 splitInlineReasoning 所需的内容片段。 */
function splitInlineReasoning(content: string) {
  const reasoningParts: string[] = [];

  // 第一轮：移除每一对完整闭合的 `<think>...</think>`，并将其内容收集为推理。
  let cleaned = content.replace(THINK_TAG_RE, (_, reasoning: string) => {
    const normalized = reasoning.trim();
    if (normalized) {
      reasoningParts.push(normalized);
    }
    return "";
  });

  // 流式安全处理：尚未收到 `</think>` 的 `<think>` 起始标记意味着该片段余下部分
  // 是正在输出的推理。将它放入推理区域而非作为消息内容渲染，否则原始 HTML 的
  // Markdown 管线会在闭合标记到达前将内部文本显示到屏幕上。
  // 若起始标记紧跟反引号则跳过：这表示模型在 Markdown 内联代码中原样讨论
  // `<think>`，并非实际流式输出推理。
  const openTagIndex = cleaned.indexOf(THINK_OPEN_TAG);
  if (openTagIndex !== -1 && cleaned[openTagIndex - 1] !== "`") {
    const tail = cleaned.slice(openTagIndex + THINK_OPEN_TAG.length).trim();
    if (tail) {
      reasoningParts.push(tail);
    }
    cleaned = cleaned.slice(0, openTagIndex);
  }

  return {
    content: cleaned.trim(),
    reasoning: reasoningParts.length > 0 ? reasoningParts.join("\n\n") : null,
  };
}

/** 拆分 splitInlineReasoningFromAIMessage 所需的内容片段。 */
function splitInlineReasoningFromAIMessage(message: Message) {
  if (message.type !== "ai" || typeof message.content !== "string") {
    return null;
  }
  return splitInlineReasoning(message.content);
}

/** 提取消息的展示内容，同时从 AI 字符串内容中剥离内联推理。 */
export function extractContentFromMessage(message: Message) {
  if (typeof message.content === "string") {
    return (
      splitInlineReasoningFromAIMessage(message)?.content ??
      message.content.trim()
    );
  }
  if (Array.isArray(message.content)) {
    return message.content
      .map((content) => {
        if (typeof content === "string") {
          return content;
        }
        switch (content.type) {
          case "text":
            return content.text;
          case "image_url":
            const imageURL = extractURLFromImageURLContent(content.image_url);
            return `![image](${imageURL})`;
          default:
            return "";
        }
      })
      .join("\n")
      .trim();
  }
  return "";
}

/** 提取 AI 消息的推理内容，兼容元数据、内容块和内联 `<think>` 标记。 */
export function extractReasoningContentFromMessage(message: Message) {
  if (message.type !== "ai") {
    return null;
  }
  if (
    message.additional_kwargs &&
    "reasoning_content" in message.additional_kwargs
  ) {
    return message.additional_kwargs.reasoning_content as string | null;
  }
  if (Array.isArray(message.content)) {
    const part = message.content[0];
    if (part && typeof part === "object" && "thinking" in part) {
      return part.thinking as string;
    }
  }
  if (typeof message.content === "string") {
    return splitInlineReasoning(message.content).reasoning;
  }
  return null;
}

/** 从 AI 消息的附加参数中删除已处理的 reasoning_content。 */
export function removeReasoningContentFromMessage(message: Message) {
  if (message.type !== "ai" || !message.additional_kwargs) {
    return;
  }
  delete message.additional_kwargs.reasoning_content;
}

/** 从图片消息片段读取图片地址，兼容字符串和带 URL 字段的对象。 */
export function extractURLFromImageURLContent(
  content:
    | string
    | {
        url: string;
      },
) {
  if (typeof content === "string") {
    return content;
  }
  return content.url;
}

/** 判断消息是否包含可展示的非推理内容。 */
export function hasContent(message: Message) {
  if (typeof message.content === "string") {
    return (
      (
        splitInlineReasoningFromAIMessage(message)?.content ??
        message.content.trim()
      ).length > 0
    );
  }
  if (Array.isArray(message.content)) {
    return message.content.length > 0;
  }
  return false;
}

/** 判断 AI 消息是否携带推理内容。 */
export function hasReasoning(message: Message) {
  if (message.type !== "ai") {
    return false;
  }
  if (typeof message.additional_kwargs?.reasoning_content === "string") {
    return true;
  }
  if (Array.isArray(message.content)) {
    const part = message.content[0];
    // 兼容 Anthropic 网关。
    return (part as unknown as { type: "thinking" })?.type === "thinking";
  }
  if (typeof message.content === "string") {
    return splitInlineReasoning(message.content).reasoning !== null;
  }
  return false;
}

/** 判断 AI 消息是否携带工具调用。 */
export function hasToolCalls(message: Message) {
  return (
    message.type === "ai" && message.tool_calls && message.tool_calls.length > 0
  );
}

/** 判断 AI 消息是否调用 present_files。 */
export function hasPresentFiles(message: Message) {
  return (
    message.type === "ai" &&
    message.tool_calls?.some((toolCall) => toolCall.name === "present_files")
  );
}

/** 判断工具消息是否来自 ask_clarification。 */
export function isClarificationToolMessage(message: Message) {
  return message.type === "tool" && message.name === "ask_clarification";
}

/** 提取 present_files 工具调用中声明的文件路径。 */
export function extractPresentFilesFromMessage(message: Message) {
  if (message.type !== "ai" || !hasPresentFiles(message)) {
    return [];
  }
  const files: string[] = [];
  for (const toolCall of message.tool_calls ?? []) {
    if (
      toolCall.name === "present_files" &&
      Array.isArray(toolCall.args.filepaths)
    ) {
      files.push(...(toolCall.args.filepaths as string[]));
    }
  }
  return files;
}

/** 判断 AI 消息是否通过 task 工具派发子代理。 */
export function hasSubagent(message: AIMessage) {
  for (const toolCall of message.tool_calls ?? []) {
    if (toolCall.name === "task") {
      return true;
    }
  }
  return false;
}

/** 在消息列表中查找指定工具调用 ID 的首个非空文本结果。 */
export function findToolCallResult(toolCallId: string, messages: Message[]) {
  for (const message of messages) {
    if (message.type === "tool" && message.tool_call_id === toolCallId) {
      const content = extractTextFromMessage(message);
      if (content) {
        return content;
      }
    }
  }
  return undefined;
}

/** 判断消息是否应因隐藏标记、控制消息名或纯技能激活内容而不在 UI 展示。 */
export function isHiddenFromUIMessage(message: Message) {
  const content = extractTextFromMessage(message);
  return (
    message.additional_kwargs?.hide_from_ui === true ||
    (typeof message.name === "string" &&
      HIDDEN_CONTROL_MESSAGE_NAMES.has(message.name)) ||
    (message.type === "human" &&
      content.includes("<slash_skill_activation>") &&
      stripUploadedFilesTag(content).length === 0)
  );
}

/**
 * 表示存放在消息 additional_kwargs.files 中的文件。
 * 用于乐观 UI（上传状态）和结构化文件元数据。
 */
export interface FileInMessage {
  filename: string;
  size: number; // 字节数
  path?: string; // 虚拟路径，上传期间可能尚未设置
  status?: "uploading" | "uploaded";
}

/**
 * 从消息内容中移除后端注入的人类上下文标签。
 * 因调用方使用它清理上传文件展示，故保留其历史名称。
 */
export function stripUploadedFilesTag(content: string): string {
  return content
    .replace(/<(uploaded_files|slash_skill_activation)>[\s\S]*?<\/\1>/g, "")
    .trim();
}

/**
 * 后端中间件在内部载荷外包裹的标签名，随后这些载荷会随 LangGraph 消息 ``content`` 传递。
 *
 * 这些标记不是用户文案，来源如下：
 *
 * - ``UploadsMiddleware`` → ``<uploaded_files>``
 * - ``SkillActivationMiddleware`` → ``<slash_skill_activation>``
 * - ``DynamicContextMiddleware`` → ``<system-reminder>``（内部携带
 *   ``<memory>`` / ``<current_date>``）
 * - ``TodoListMiddleware`` / ``LoopDetectionMiddleware`` 风格的提醒存放在
 *   ``hide_from_ui`` HumanMessages 中，但其内部载荷使用同一套标签词汇。
 *
 * 主要的导出过滤器是 {@link isHiddenFromUIMessage}。若因中间件缺陷、供应商特性或
 * 合并冲突回归导致某条消息未设置 ``hide_from_ui`` 标记便漏网，本列表提供纵深清理。
 */
export const INTERNAL_MARKER_TAGS = [
  "uploaded_files",
  "slash_skill_activation",
  "system-reminder",
  "memory",
  "current_date",
] as const;

const INTERNAL_MARKER_RE = new RegExp(
  `<(${INTERNAL_MARKER_TAGS.join("|")})>[\\s\\S]*?</\\1>`,
  "g",
);

/**
 * 从消息内容中移除全部已知的后端注入标记。
 *
 * 此函数用于聊天导出路径，标记泄漏到该路径属于隐私回归。UI 渲染路径应继续使用
 * {@link stripUploadedFilesTag}：其通过独立过滤器处理 ``hide_from_ui`` 消息，且更
 * 窄的函数避免删去用户可能在元讨论中合法输入的内容（例如询问模型自身的
 * ``<memory>`` 系统）。
 */
export function stripInternalMarkers(content: string): string {
  return content.replace(INTERNAL_MARKER_RE, "").trim();
}

/** 从 `<uploaded_files>` 标签的后端格式中解析上传文件元数据。 */
export function parseUploadedFiles(content: string): FileInMessage[] {
  // 匹配 <uploaded_files>...</uploaded_files> 标签。
  const uploadedFilesRegex = /<uploaded_files>([\s\S]*?)<\/uploaded_files>/;
  // eslint-disable-next-line @typescript-eslint/prefer-regexp-exec
  const match = content.match(uploadedFilesRegex);

  if (!match) {
    return [];
  }

  const uploadedFilesContent = match[1];

  // 检查是否为“尚未上传文件”的后端占位内容。
  if (uploadedFilesContent?.includes("No files have been uploaded yet.")) {
    return [];
  }

  // 检查后端是否报告此消息没有新增上传文件。
  if (uploadedFilesContent?.includes("(empty)")) {
    return [];
  }

  // 解析文件列表。
  // 格式：- filename (size)\n  Path: /path/to/file
  const fileRegex = /- ([^\n(]+)\s*\(([^)]+)\)\s*\n\s*Path:\s*([^\n]+)/g;
  const files: FileInMessage[] = [];
  let fileMatch;

  while ((fileMatch = fileRegex.exec(uploadedFilesContent ?? "")) !== null) {
    files.push({
      filename: fileMatch[1].trim(),
      size: parseInt(fileMatch[2].trim(), 10) ?? 0,
      path: fileMatch[3].trim(),
    });
  }

  return files;
}
