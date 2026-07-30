import type { Message } from "@langchain/langgraph-sdk";

import type { Translations } from "@/core/i18n/locales/types";

import { getUsageMetadata, type TokenUsage } from "./usage";
import { hasContent } from "./utils";

/** 令牌用量的行内展示模式。 */
export type TokenUsageInlineMode = "off" | "per_turn" | "step_debug";

/** 令牌用量视图的持久化偏好。 */
export interface TokenUsagePreferences {
  headerTotal: boolean;
  inlineMode: TokenUsageInlineMode;
}

/** 面向界面的令牌用量预设，映射为具体展示偏好。 */
export type TokenUsageViewPreset = "off" | "summary" | "per_turn" | "debug";

/** 令牌调试视图中归属于单条 AI 消息的一步。 */
export interface TokenDebugStep {
  id: string;
  messageId: string;
  label: string;
  secondaryLabels: string[];
  usage: TokenUsage | null;
  sharedAttribution: boolean;
}

type TokenUsageAttributionAction =
  | {
      kind: "todo_start" | "todo_complete" | "todo_update" | "todo_remove";
      content?: string;
      tool_call_id?: string;
    }
  | {
      kind: "subagent";
      description?: string | null;
      subagent_type?: string | null;
      tool_call_id?: string;
    }
  | {
      kind: "search";
      query?: string | null;
      tool_name?: string | null;
      tool_call_id?: string;
    }
  | {
      kind: "present_files" | "clarification";
      tool_call_id?: string;
    }
  | {
      kind: "tool";
      tool_name?: string | null;
      description?: string | null;
      tool_call_id?: string;
    };

interface TokenUsageAttribution {
  version?: number;
  kind?:
    | "thinking"
    | "final_answer"
    | "tool_batch"
    | "todo_update"
    | "subagent_dispatch";
  shared_attribution?: boolean;
  tool_call_ids?: string[];
  actions?: TokenUsageAttributionAction[];
}

// 精确的 write_todos 标签来自后端的归因载荷。
// 前端回退逻辑有意保持通用，避免复制
// backend/packages/harness/deerflow/agents/middlewares/token_usage_middleware.py
//::_build_todo_actions，从而使两套差异比较算法逐渐产生偏差。

/** 将详细令牌用量偏好归并为对应的界面预设。 */
export function getTokenUsageViewPreset(
  preferences: TokenUsagePreferences,
): TokenUsageViewPreset {
  if (!preferences.headerTotal && preferences.inlineMode === "off") {
    return "off";
  }
  if (preferences.headerTotal && preferences.inlineMode === "off") {
    return "summary";
  }
  if (preferences.inlineMode === "step_debug") {
    return "debug";
  }
  return "per_turn";
}

/** 将界面预设展开为详细的令牌用量偏好。 */
export function tokenUsagePreferencesFromPreset(
  preset: TokenUsageViewPreset,
): TokenUsagePreferences {
  switch (preset) {
    case "off":
      return { headerTotal: false, inlineMode: "off" };
    case "summary":
      return { headerTotal: true, inlineMode: "off" };
    case "debug":
      return { headerTotal: true, inlineMode: "step_debug" };
    case "per_turn":
    default:
      return { headerTotal: true, inlineMode: "per_turn" };
  }
}

/** 按后端归因或工具调用回退信息构建令牌调试步骤。 */
export function buildTokenDebugSteps(
  messages: Message[],
  t: Translations,
): TokenDebugStep[] {
  const steps: TokenDebugStep[] = [];

  for (const [index, message] of messages.entries()) {
    if (message.type !== "ai") {
      continue;
    }

    const usage = getUsageMetadata(message);
    const attribution = getTokenUsageAttribution(message);
    const actionLabels: string[] = [];

    if (attribution) {
      actionLabels.push(...buildActionLabelsFromAttribution(attribution, t));

      if (actionLabels.length === 0) {
        if (attribution.kind === "final_answer") {
          actionLabels.push(t.tokenUsage.finalAnswer);
        } else if (attribution.kind === "thinking") {
          actionLabels.push(t.common.thinking);
        }
      }

      if (actionLabels.length > 0) {
        const sharedAttribution =
          attribution.shared_attribution ?? actionLabels.length > 1;
        steps.push({
          id: message.id ?? `token-step-${index}`,
          messageId: message.id ?? `token-step-${index}`,
          label:
            sharedAttribution && actionLabels.length > 1
              ? t.tokenUsage.stepTotal
              : actionLabels[0]!,
          secondaryLabels:
            sharedAttribution && actionLabels.length > 1 ? actionLabels : [],
          usage,
          sharedAttribution,
        });
        continue;
      }
    }

    for (const toolCall of message.tool_calls ?? []) {
      const toolArgs = (toolCall.args ?? {}) as Record<string, unknown>;

      if (toolCall.name === "write_todos") {
        actionLabels.push(t.toolCalls.writeTodos);
        continue;
      }

      actionLabels.push(
        describeToolCall(
          {
            name: toolCall.name,
            args: toolArgs,
          },
          t,
        ),
      );
    }

    if (actionLabels.length === 0) {
      if (hasContent(message)) {
        actionLabels.push(t.tokenUsage.finalAnswer);
      } else {
        actionLabels.push(t.common.thinking);
      }
    }

    steps.push({
      id: message.id ?? `token-step-${index}`,
      messageId: message.id ?? `token-step-${index}`,
      label:
        actionLabels.length === 1 ? actionLabels[0]! : t.tokenUsage.stepTotal,
      secondaryLabels: actionLabels.length > 1 ? actionLabels : [],
      usage,
      sharedAttribution: actionLabels.length > 1,
    });
  }

  return steps;
}

/** 获取 getTokenUsageAttribution 所需的结果或配置。 */
function getTokenUsageAttribution(
  message: Message,
): TokenUsageAttribution | null {
  if (message.type !== "ai") {
    return null;
  }

  const additionalKwargs = message.additional_kwargs;
  if (!additionalKwargs || typeof additionalKwargs !== "object") {
    return null;
  }

  const attribution = (additionalKwargs as Record<string, unknown>)
    .token_usage_attribution;
  const normalized = normalizeTokenUsageAttribution(attribution);
  if (!normalized) {
    return null;
  }

  return normalized;
}

/** 构建 buildActionLabelsFromAttribution 所需的结果。 */
function buildActionLabelsFromAttribution(
  attribution: TokenUsageAttribution,
  t: Translations,
): string[] {
  return (attribution.actions ?? [])
    .map((action) => describeAttributionAction(action, t))
    .filter((label): label is string => !!label);
}

/** 实现 describeAttributionAction 的受限辅助逻辑。 */
function describeAttributionAction(
  action: TokenUsageAttributionAction,
  t: Translations,
): string | null {
  switch (action.kind) {
    case "todo_start":
      return action.content
        ? t.tokenUsage.startTodo(action.content)
        : t.toolCalls.writeTodos;
    case "todo_complete":
      return action.content
        ? t.tokenUsage.completeTodo(action.content)
        : t.toolCalls.writeTodos;
    case "todo_update":
      return action.content
        ? t.tokenUsage.updateTodo(action.content)
        : t.toolCalls.writeTodos;
    case "todo_remove":
      return action.content
        ? t.tokenUsage.removeTodo(action.content)
        : t.toolCalls.writeTodos;
    case "subagent":
      return t.tokenUsage.subagent(action.description ?? t.subtasks.subtask);
    case "search":
      if (action.query) {
        return t.toolCalls.searchFor(action.query);
      }
      return t.toolCalls.useTool(action.tool_name ?? "search");
    case "present_files":
      return t.toolCalls.presentFiles;
    case "clarification":
      return t.toolCalls.needYourHelp;
    case "tool":
      return describeToolCall(
        {
          name: action.tool_name ?? "tool",
          args: action.description ? { description: action.description } : {},
        },
        t,
      );
    default:
      return null;
  }
}

/** 实现 describeToolCall 的受限辅助逻辑。 */
function describeToolCall(
  toolCall: {
    name: string;
    args: Record<string, unknown>;
  },
  t: Translations,
): string {
  if (toolCall.name === "task") {
    const description =
      typeof toolCall.args.description === "string"
        ? toolCall.args.description
        : t.subtasks.subtask;
    return t.tokenUsage.subagent(description);
  }

  if (
    (toolCall.name === "web_search" || toolCall.name === "image_search") &&
    typeof toolCall.args.query === "string"
  ) {
    return t.toolCalls.searchFor(toolCall.args.query);
  }

  if (toolCall.name === "web_fetch") {
    return t.toolCalls.viewWebPage;
  }

  if (toolCall.name === "present_files") {
    return t.toolCalls.presentFiles;
  }

  if (toolCall.name === "ask_clarification") {
    return t.toolCalls.needYourHelp;
  }

  if (typeof toolCall.args.description === "string") {
    return toolCall.args.description;
  }

  return t.toolCalls.useTool(toolCall.name);
}

/** 将输入规范化为 normalizeTokenUsageAttribution 所需的形式。 */
function normalizeTokenUsageAttribution(
  value: unknown,
): TokenUsageAttribution | null {
  const record = asRecord(value);
  if (!record) {
    return null;
  }

  const rawActions = record.actions;
  if (rawActions !== undefined && !Array.isArray(rawActions)) {
    return null;
  }

  return {
    // 当前版本策略仅做增量扩展：前端应忽略未知字段，并在必填字段不兼容时回退。
    version: typeof record.version === "number" ? record.version : undefined,
    kind: isTokenUsageAttributionKind(record.kind) ? record.kind : undefined,
    shared_attribution:
      typeof record.shared_attribution === "boolean"
        ? record.shared_attribution
        : undefined,
    tool_call_ids: Array.isArray(record.tool_call_ids)
      ? record.tool_call_ids.filter(
          (toolCallId): toolCallId is string =>
            typeof toolCallId === "string" && toolCallId.trim().length > 0,
        )
      : undefined,
    actions: Array.isArray(rawActions)
      ? rawActions
          .map((action) => normalizeTokenUsageAttributionAction(action))
          .filter(
            (action): action is TokenUsageAttributionAction => action !== null,
          )
      : undefined,
  };
}

/** 将输入规范化为 normalizeTokenUsageAttributionAction 所需的形式。 */
function normalizeTokenUsageAttributionAction(
  value: unknown,
): TokenUsageAttributionAction | null {
  const record = asRecord(value);
  if (!record) {
    return null;
  }

  const kind = record.kind;
  if (
    kind !== "todo_start" &&
    kind !== "todo_complete" &&
    kind !== "todo_update" &&
    kind !== "todo_remove" &&
    kind !== "subagent" &&
    kind !== "search" &&
    kind !== "present_files" &&
    kind !== "clarification" &&
    kind !== "tool"
  ) {
    return null;
  }

  const content = readString(record.content);
  const toolCallId = readString(record.tool_call_id);

  switch (kind) {
    case "todo_start":
    case "todo_complete":
    case "todo_update":
    case "todo_remove":
      return {
        kind,
        content,
        tool_call_id: toolCallId,
      };
    case "subagent":
      return {
        kind,
        description: readString(record.description),
        subagent_type: readString(record.subagent_type),
        tool_call_id: toolCallId,
      };
    case "search":
      return {
        kind,
        query: readString(record.query),
        tool_name: readString(record.tool_name),
        tool_call_id: toolCallId,
      };
    case "present_files":
    case "clarification":
      return {
        kind,
        tool_call_id: toolCallId,
      };
    case "tool":
      return {
        kind,
        tool_name: readString(record.tool_name),
        description: readString(record.description),
        tool_call_id: toolCallId,
      };
    default:
      return null;
  }
}

/** 实现 asRecord 的受限辅助逻辑。 */
function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }

  return value as Record<string, unknown>;
}

/** 解析并提取 readString 所需的数据。 */
function readString(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }

  const normalized = value.trim();
  return normalized.length > 0 ? normalized : undefined;
}

/** 判断 isTokenUsageAttributionKind 所表达的条件是否成立。 */
function isTokenUsageAttributionKind(
  value: unknown,
): value is NonNullable<TokenUsageAttribution["kind"]> {
  return (
    value === "thinking" ||
    value === "final_answer" ||
    value === "tool_batch" ||
    value === "todo_update" ||
    value === "subagent_dispatch"
  );
}
