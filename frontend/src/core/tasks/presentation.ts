import { formatTokenCount, type TokenUsage } from "@/core/messages/usage";
import type { Model } from "@/core/models/types";

/** 返回已配置子代理模型面向用户的展示标签。 */
export function resolveSubtaskModelLabel(
  modelName: string | undefined,
  models: Model[],
): string | undefined {
  if (!modelName) {
    return undefined;
  }
  return (
    models.find((model) => model.name === modelName)?.display_name ?? modelName
  );
}

/** 格式化子任务令牌用量以供卡片展示。 */
export function formatSubtaskTokenUsage(
  usage: TokenUsage | undefined,
): string | undefined {
  return usage ? formatTokenCount(usage.totalTokens) : undefined;
}
