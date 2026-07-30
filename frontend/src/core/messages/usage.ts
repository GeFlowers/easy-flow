import type { Message } from "@langchain/langgraph-sdk";

/** 统一的输入、输出与总令牌用量。 */
export interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
}

/** 从 AI 消息中提取 usage_metadata；该字段由后端添加（PR #1218），但 SDK 尚未为其声明类型。 */
export function getUsageMetadata(message: Message): TokenUsage | null {
  if (message.type !== "ai") {
    return null;
  }
  const usage =
    ((message as Record<string, unknown>).usage_metadata as
      | {
          input_tokens?: number;
          output_tokens?: number;
          total_tokens?: number;
        }
      | undefined) ??
    (message.additional_kwargs?.usage_metadata as
      | {
          input_tokens?: number;
          output_tokens?: number;
          total_tokens?: number;
        }
      | undefined);
  if (!usage) {
    return null;
  }
  return {
    inputTokens: usage.input_tokens ?? 0,
    outputTokens: usage.output_tokens ?? 0,
    totalTokens: usage.total_tokens ?? 0,
  };
}

/**
 * 汇总多条 AI 消息的令牌用量。
 *
 * UI 渲染可能将同一条 AI 消息放入多个分组，例如消息同时包含推理和最终回答时。
 * 令牌用量归属于 AI 消息本身，因此每个消息 ID 在任一汇总中只能计入一次。
 */
export function accumulateUsage(messages: Message[]): TokenUsage | null {
  const cumulative: TokenUsage = {
    inputTokens: 0,
    outputTokens: 0,
    totalTokens: 0,
  };
  let hasUsage = false;
  const countedMessageIds = new Set<string>();

  for (const message of messages) {
    const usage = getUsageMetadata(message);
    if (!usage) {
      continue;
    }

    if (message.id) {
      if (countedMessageIds.has(message.id)) {
        continue;
      }
      countedMessageIds.add(message.id);
    }

    hasUsage = true;
    cumulative.inputTokens += usage.inputTokens;
    cumulative.outputTokens += usage.outputTokens;
    cumulative.totalTokens += usage.totalTokens;
  }
  return hasUsage ? cumulative : null;
}

/**
 * 将原始的 `{input,output,total}_tokens` 对象校验并转换为 {@link TokenUsage}。
 *
 * 这是子代理两种用量来源共用的唯一校验器：实时 `task_running` 事件
 * （`core/tasks/lifecycle.ts`）和终态 ToolMessage 元数据
 * （`core/tasks/subtask-result.ts`）。共用函数可防止两处规则漂移，例如一处接受
 * 额外令牌字段而另一处拒绝。每个键均须是有限且非负的数字，否则整个快照返回
 * `undefined`。
 */
export function normalizeTokenUsage(value: unknown): TokenUsage | undefined {
  if (typeof value !== "object" || value === null) {
    return undefined;
  }
  const record = value as Record<string, unknown>;
  const inputTokens = nonNegativeNumber(record.input_tokens);
  const outputTokens = nonNegativeNumber(record.output_tokens);
  const totalTokens = nonNegativeNumber(record.total_tokens);
  if (
    inputTokens === undefined ||
    outputTokens === undefined ||
    totalTokens === undefined
  ) {
    return undefined;
  }
  return { inputTokens, outputTokens, totalTokens };
}

/** 将有限的非负数规范化为可用令牌数。 */
function nonNegativeNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value
    : undefined;
}

/** 判断令牌用量是否存在且至少有一项大于零。 */
export function hasNonZeroUsage(
  usage: TokenUsage | null | undefined,
): usage is TokenUsage {
  return (
    usage !== null &&
    usage !== undefined &&
    (usage.inputTokens > 0 || usage.outputTokens > 0 || usage.totalTokens > 0)
  );
}

/** 将一段令牌用量累加到既有汇总。 */
export function addUsage(base: TokenUsage, delta: TokenUsage): TokenUsage {
  return {
    inputTokens: base.inputTokens + delta.inputTokens,
    outputTokens: base.outputTokens + delta.outputTokens,
    totalTokens: base.totalTokens + delta.totalTokens,
  };
}

/** 选择页头显示的令牌用量，优先采用后端提供的总量。 */
export function selectHeaderTokenUsage({
  backendUsage,
  messages,
  pendingMessages = [],
}: {
  backendUsage?: TokenUsage | null;
  messages: Message[];
  pendingMessages?: Message[];
}): TokenUsage | null {
  if (hasNonZeroUsage(backendUsage)) {
    const pendingUsage = accumulateUsage(pendingMessages);
    return pendingUsage ? addUsage(backendUsage, pendingUsage) : backendUsage;
  }
  return accumulateUsage(messages);
}

/** 将令牌数格式化为显示值：1234 → "1,234"，12345 → "12.3K"。 */
export function formatTokenCount(count: number): string {
  if (count < 10_000) {
    return count.toLocaleString();
  }
  return `${(count / 1000).toFixed(1)}K`;
}
