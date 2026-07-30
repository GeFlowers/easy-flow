import type { Message } from "@langchain/langgraph-sdk";

import {
  extractContentFromMessage,
  extractReasoningContentFromMessage,
  hasContent,
  hasToolCalls,
  isHiddenFromUIMessage,
  stripInternalMarkers,
} from "../messages/utils";

import type { AgentThread } from "./types";
import { titleOfThread } from "./utils";

/**
 * 高级导出的可选调试开关。
 *
 * Bytedance/deer-flow 的 issue #3107 BUG-006 明确规定，默认导出仅包含用户可见
 * 的对话记录，并排除思考／推理内容、工具调用、工具结果、隐藏消息、记忆注入以及
 * `<system-reminder>` 载荷。这些选项让未来的“调试导出”界面无需分叉格式化器便可
 * 重新纳入其中任一类别。目前它们未接入任何 UI 控件；需要使用的调用方必须显式构造
 * 此选项对象。
 */
export interface ExportOptions {
  includeReasoning?: boolean;
  includeToolCalls?: boolean;
  includeToolMessages?: boolean;
  includeHidden?: boolean;
}

/** 过滤出可安全导出的用户可见消息。 */
function visibleMessages(
  messages: Message[],
  options: ExportOptions,
): Message[] {
  return messages.filter((message) => {
    if (!options.includeHidden && isHiddenFromUIMessage(message)) {
      return false;
    }
    if (!options.includeToolMessages && message.type === "tool") {
      return false;
    }
    return true;
  });
}

/** 清理消息内容中的内部标记并格式化为导出文本。 */
function formatMessageContent(message: Message): string {
  const text = extractContentFromMessage(message);
  if (!text) return "";
  // 纵深防护：即使中间件插入的标记漏过 hide_from_ui 过滤，也要在写入
  // 用户可见的导出文件前清除所有已知内部标签。
  return stripInternalMarkers(text);
}

/** 将消息中的工具调用格式化为 Markdown 代码块。 */
function formatToolCalls(message: Message): string {
  if (message.type !== "ai" || !hasToolCalls(message)) return "";
  const calls = message.tool_calls ?? [];
  return calls.map((call) => `- **Tool:** \`${call.name}\``).join("\n");
}

/** 将线程与消息格式化为可下载的 Markdown。 */
export function formatThreadAsMarkdown(
  thread: AgentThread,
  messages: Message[],
  options: ExportOptions = {},
): string {
  const title = titleOfThread(thread);
  const createdAt = thread.created_at
    ? new Date(thread.created_at).toLocaleString()
    : "Unknown";

  const lines: string[] = [
    `# ${title}`,
    "",
    `*Exported on ${new Date().toLocaleString()} · Created ${createdAt}*`,
    "",
    "---",
    "",
  ];

  for (const message of visibleMessages(messages, options)) {
    if (message.type === "human") {
      const content = formatMessageContent(message);
      if (content) {
        lines.push(`## 🧑 User`, "", content, "", "---", "");
      }
    } else if (message.type === "ai") {
      const reasoning = options.includeReasoning
        ? extractReasoningContentFromMessage(message)
        : undefined;
      const content = formatMessageContent(message);
      const toolCalls = options.includeToolCalls
        ? formatToolCalls(message)
        : "";

      if (!content && !toolCalls && !reasoning) continue;

      lines.push(`## 🤖 Assistant`);

      if (reasoning) {
        lines.push(
          "",
          "<details>",
          "<summary>Thinking</summary>",
          "",
          reasoning,
          "",
          "</details>",
        );
      }

      if (toolCalls) {
        lines.push("", toolCalls);
      }

      if (content && hasContent(message)) {
        lines.push("", content);
      }

      lines.push("", "---", "");
    }
  }

  return lines.join("\n").trimEnd() + "\n";
}

interface JSONExportMessage {
  type: Message["type"];
  id: string | undefined;
  content: string;
  reasoning?: string;
  tool_calls?: unknown;
}

/** 构建不含内部载荷的单条 JSON 导出消息。 */
function buildJSONMessage(
  msg: Message,
  options: ExportOptions,
): JSONExportMessage | null {
  // 使用与 Markdown 导出相同的清理逻辑，确保 JSON content 不会包含
  // 内联 think 包装、内容数组推理块、uploaded_files 标记或其他内部载荷。
  const content = formatMessageContent(msg);
  const reasoning =
    options.includeReasoning && msg.type === "ai"
      ? (extractReasoningContentFromMessage(msg) ?? undefined)
      : undefined;
  const toolCalls =
    options.includeToolCalls &&
    msg.type === "ai" &&
    "tool_calls" in msg &&
    msg.tool_calls?.length
      ? msg.tool_calls
      : undefined;

  // 移除没有可导出载荷的行（空内容且没有选择导出的推理或工具调用）。
  // 这里采用假值判断，让空字符串推理内容与 Markdown 的行为一致，避免导出无意义字段。
  if (!content && !reasoning && !toolCalls) {
    return null;
  }

  return {
    type: msg.type,
    id: msg.id,
    content,
    ...(reasoning !== undefined ? { reasoning } : {}),
    ...(toolCalls !== undefined ? { tool_calls: toolCalls } : {}),
  };
}

/** 将线程与消息格式化为可下载的 JSON。 */
export function formatThreadAsJSON(
  thread: AgentThread,
  messages: Message[],
  options: ExportOptions = {},
): string {
  const exportData = {
    title: titleOfThread(thread),
    thread_id: thread.thread_id,
    created_at: thread.created_at,
    exported_at: new Date().toISOString(),
    messages: visibleMessages(messages, options)
      .map((msg) => buildJSONMessage(msg, options))
      .filter((m): m is JSONExportMessage => m !== null),
  };
  return JSON.stringify(exportData, null, 2);
}

/** 清理线程标题，使其可安全用作下载文件名。 */
function sanitizeFilename(name: string): string {
  return name.replace(/[^\p{L}\p{N}_\- ]/gu, "").trim() || "conversation";
}

/** 在浏览器中下载指定内容与文件名。 */
export function downloadAsFile(
  content: string,
  filename: string,
  mimeType: string,
) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/** 将线程导出为 Markdown 下载文件。 */
export function exportThreadAsMarkdown(
  thread: AgentThread,
  messages: Message[],
) {
  const markdown = formatThreadAsMarkdown(thread, messages);
  const filename = `${sanitizeFilename(titleOfThread(thread))}.md`;
  downloadAsFile(markdown, filename, "text/markdown;charset=utf-8");
}

/** 将线程导出为 JSON 下载文件。 */
export function exportThreadAsJSON(thread: AgentThread, messages: Message[]) {
  const json = formatThreadAsJSON(thread, messages);
  const filename = `${sanitizeFilename(titleOfThread(thread))}.json`;
  downloadAsFile(json, filename, "application/json;charset=utf-8");
}
