import type { ToolCall } from "@langchain/core/messages";
import type { AIMessage } from "@langchain/langgraph-sdk";

import type { Translations } from "../i18n";
import { hasToolCalls } from "../messages/utils";

/** 为消息中的最后一次工具调用生成本地化说明。 */
export function explainLastToolCall(message: AIMessage, t: Translations) {
  if (hasToolCalls(message)) {
    const lastToolCall = message.tool_calls![message.tool_calls!.length - 1]!;
    return explainToolCall(lastToolCall, t);
  }
  return t.common.thinking;
}

/** 为单次工具调用解析对应的本地化说明。 */
export function explainToolCall(toolCall: ToolCall, t: Translations) {
  if (toolCall.name === "web_search" || toolCall.name === "image_search") {
    return t.toolCalls.searchFor(toolCall.args.query);
  } else if (toolCall.name === "web_fetch") {
    return t.toolCalls.viewWebPage;
  } else if (toolCall.name === "present_files") {
    return t.toolCalls.presentFiles;
  } else if (toolCall.name === "write_todos") {
    return t.toolCalls.writeTodos;
  } else if (toolCall.args.description) {
    return toolCall.args.description;
  } else {
    return t.toolCalls.useTool(toolCall.name);
  }
}
