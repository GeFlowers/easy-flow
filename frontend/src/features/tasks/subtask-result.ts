import type { Message } from "@langchain/langgraph-sdk";

import { normalizeTokenUsage } from "../messages/usage";

import type { Subtask } from "./types";

/** 子任务卡片可展示的标准状态。 */
export type SubtaskStatus = Subtask["status"];

/** 从任务工具结果中提取出的子任务状态更新。 */
export interface SubtaskResultUpdate {
  status: SubtaskStatus;
  result?: string;
  error?: string;
  modelName?: string;
  usage?: Subtask["usage"];
  /**
   * 后端写入 `subagent_stop_reason` 时，导致运行被护栏上限提前结束的原因（`token_capped`、
   * `turn_capped` 或 `loop_capped`）。已达上限的运行仍保留正常状态标签：产生最终答案为
   * `completed`，否则为 `failed`；因此该字段是区分“已结束”与“已达上限”的唯一信号（#3875 第二阶段）。
   */
  stopReason?: string;
}

/**
 * 后端为每个 `task` 工具结果写入 `ToolMessage.additional_kwargs` 的结构化状态键。
 *
 * 取值与 Python 契约 `backend/deerflow/subagents/status_contract.py`
 * 保持一致（`SUBAGENT_STATUS_KEY`、`SUBAGENT_ERROR_KEY`、`SUBAGENT_RESULT_BRIEF_KEY`、
 * `SUBAGENT_MODEL_NAME_KEY` 与 `SUBAGENT_TOKEN_USAGE_KEY`）。
 * 可选字段 `subagent_result_brief` 保存已完成任务的截断摘要。
 */
export const SUBAGENT_STATUS_KEY = "subagent_status";
export const SUBAGENT_STOP_REASON_KEY = "subagent_stop_reason";
export const SUBAGENT_ERROR_KEY = "subagent_error";
export const SUBAGENT_RESULT_BRIEF_KEY = "subagent_result_brief";
export const SUBAGENT_MODEL_NAME_KEY = "subagent_model_name";
export const SUBAGENT_TOKEN_USAGE_KEY = "subagent_token_usage";
/**
 * 导致子代理运行被护栏上限提前结束的原因（#3875 第二阶段）。与 Python 的
 * `SUBAGENT_STOP_REASON_VALUES` 对应。
 */
const SUBAGENT_STOP_REASON_VALUES = [
  "token_capped",
  "turn_capped",
  "loop_capped",
] as const;

/**
 * 将后端 `subagent_status` 映射为前端 {@link SubtaskStatus} 枚举。子任务卡片仅渲染三种
 * 状态标签，因此前端会将 `cancelled`、`timed_out` 与 `polling_timed_out` 归并为 `failed`。
 * 需要细节的工具仍可通过 `error` 获得更丰富的后端状态词汇。
 */
const STRUCTURED_STATUS_TO_SUBTASK: Record<string, SubtaskStatus> = {
  completed: "completed",
  failed: "failed",
  cancelled: "failed",
  timed_out: "failed",
  polling_timed_out: "failed",
};

/**
 * 将 `task` 工具结果映射为 {@link SubtaskStatus}。
 *
 * 后端将任务生命周期事实写入 `ToolMessage.additional_kwargs`。文本 `content` 仅是模型可见的展示
 * 内容，不会被解析为协议。
 *
 * 对未携带结构化标记的内容，刻意默认返回 `in_progress`。LangChain 仅会在工具自身返回后（成功或
 * 被包装的异常）发出 `ToolMessage`，因此未知形状意味着“底层契约已变更”。将其显示为仍在运行可提示
 * 操作人员排查；若贸然标记为终态失败，反而会掩盖这种漂移。
 */
export function parseSubtaskResult(
  additionalKwargs?: Record<string, unknown> | null,
): SubtaskResultUpdate {
  const structured = readStructuredStatus(additionalKwargs);
  if (!structured) {
    return { status: "in_progress" };
  }

  const update: SubtaskResultUpdate = { status: structured.status };
  if (structured.error) {
    update.error = structured.error;
  }
  const structuredResult = readStructuredResultBrief(additionalKwargs);
  if (structured.status === "completed" && structuredResult) {
    update.result = structuredResult;
  }
  const stopReason = readStructuredStopReason(additionalKwargs);
  if (stopReason) {
    update.stopReason = stopReason;
  }
  const modelName = readStructuredModelName(additionalKwargs);
  if (modelName) {
    update.modelName = modelName;
  }
  const usage = readStructuredTokenUsage(additionalKwargs);
  if (usage) {
    update.usage = usage;
  }
  return update;
}

/** 判断工具消息是否携带可用于更新子任务的结果。 */
export function hasSubtaskToolResult(
  toolCallId: string | undefined,
  messages: Message[],
) {
  if (!toolCallId) {
    return false;
  }
  return messages.some(
    (message) => message.type === "tool" && message.tool_call_id === toolCallId,
  );
}

/** 根据工具调用与当前状态推导尚未完成子任务的临时状态。 */
export function derivePendingSubtaskStatus(
  toolCallId: string | undefined,
  messages: Message[],
  isCurrentTurnLoading: boolean,
): SubtaskStatus {
  if (isCurrentTurnLoading || hasSubtaskToolResult(toolCallId, messages)) {
    return "in_progress";
  }
  return "failed";
}

interface StructuredStatus {
  status: SubtaskStatus;
  error?: string;
}

/** 从结构化结果中读取并校验子任务状态。 */
function readStructuredStatus(
  additionalKwargs: Record<string, unknown> | null | undefined,
): StructuredStatus | null {
  if (!additionalKwargs) return null;
  const rawStatus = additionalKwargs[SUBAGENT_STATUS_KEY];
  if (typeof rawStatus !== "string") return null;
  const mapped = STRUCTURED_STATUS_TO_SUBTASK[rawStatus];
  if (mapped === undefined) {
    return null;
  }
  const rawError = additionalKwargs[SUBAGENT_ERROR_KEY];
  const result: StructuredStatus = { status: mapped };
  if (typeof rawError === "string" && rawError.trim()) {
    result.error = rawError;
  }
  return result;
}

/** 从结构化结果读取简短结果说明。 */
function readStructuredResultBrief(
  additionalKwargs: Record<string, unknown> | null | undefined,
): string | undefined {
  const value = additionalKwargs?.[SUBAGENT_RESULT_BRIEF_KEY];
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

/** 从结构化结果读取停止原因。 */
function readStructuredStopReason(
  additionalKwargs: Record<string, unknown> | null | undefined,
): string | undefined {
  const value = additionalKwargs?.[SUBAGENT_STOP_REASON_KEY];
  if (typeof value !== "string") return undefined;
  return SUBAGENT_STOP_REASON_VALUES.includes(
    value as (typeof SUBAGENT_STOP_REASON_VALUES)[number],
  )
    ? value
    : undefined;
}

/** 从结构化结果读取子代理模型名称。 */
function readStructuredModelName(
  additionalKwargs: Record<string, unknown> | null | undefined,
): string | undefined {
  const value = additionalKwargs?.[SUBAGENT_MODEL_NAME_KEY];
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

/** 从结构化结果读取令牌用量快照。 */
function readStructuredTokenUsage(
  additionalKwargs: Record<string, unknown> | null | undefined,
): Subtask["usage"] | undefined {
  return normalizeTokenUsage(additionalKwargs?.[SUBAGENT_TOKEN_USAGE_KEY]);
}
