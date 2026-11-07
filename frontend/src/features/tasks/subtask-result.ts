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
 * `SUBAGENT_RESULT_SHA256_KEY`、`SUBAGENT_MODEL_NAME_KEY` 与 `SUBAGENT_TOKEN_USAGE_KEY`）。
 * 结果元数据字段均为可选且有界：`subagent_result_brief` 保存已完成任务的截断摘要，
 * `subagent_result_sha256` 保存完整结果的摘要。跨语言夹具
 * `contracts/subagent_status_contract.json` 约束两端使用相同取值。
 */
export const SUBAGENT_STATUS_KEY = "subagent_status";
export const SUBAGENT_STOP_REASON_KEY = "subagent_stop_reason";
export const SUBAGENT_ERROR_KEY = "subagent_error";
export const SUBAGENT_RESULT_BRIEF_KEY = "subagent_result_brief";
export const SUBAGENT_RESULT_SHA256_KEY = "subagent_result_sha256";
export const SUBAGENT_MODEL_NAME_KEY = "subagent_model_name";
export const SUBAGENT_TOKEN_USAGE_KEY = "subagent_token_usage";
/**
 * 导致子代理运行被护栏上限提前结束的原因（#3875 第二阶段）。与 Python 的
 * `SUBAGENT_STOP_REASON_VALUES` 及共享夹具的 `valid_stop_reason_values` 对应。该字段是
 * 可选的增量字段，只读取 `subagent_status` 的旧版前端不会看到它。
 */
const SUBAGENT_STOP_REASON_VALUES = [
  "token_capped",
  "turn_capped",
  "loop_capped",
] as const;
const STRUCTURED_SUBAGENT_KEYS = [
  SUBAGENT_STATUS_KEY,
  SUBAGENT_STOP_REASON_KEY,
  SUBAGENT_ERROR_KEY,
  SUBAGENT_RESULT_BRIEF_KEY,
  SUBAGENT_RESULT_SHA256_KEY,
  SUBAGENT_MODEL_NAME_KEY,
  SUBAGENT_TOKEN_USAGE_KEY,
];

const SUCCESS_PREFIX = "Task Succeeded. Result:";
const FAILURE_PREFIX = "Task failed.";
const TIMEOUT_PREFIX = "Task timed out";
const CANCELLED_PREFIX = "Task cancelled by user.";
const POLLING_TIMEOUT_PREFIX = "Task polling timed out";
const ERROR_WRAPPER_PATTERN = /^Error\b/i;

/**
 * 将后端 `subagent_status` 映射为前端 {@link SubtaskStatus} 枚举。子任务卡片仅渲染三种
 * 状态标签，因此前端会将 `cancelled`、`timed_out` 与 `polling_timed_out` 归并为 `failed`。
 * 需要细节的工具仍可通过 `error` 获得更丰富的后端状态词汇。
 *
 * `max_turns_reached` 保留为**已弃用的只读别名**：第一阶段（#3949）曾将它写入
 * `ToolMessage.additional_kwargs`，该值会检查点保存至线程历史，因此旧轮次仍可能携带它。第二阶段
 * （#3980）已停止产生此值（上限信息现由 `subagent_stop_reason` 承载）；但若移除此别名，历史卡片将
 * 永远停留在旋转的 `in_progress` 标签上（`readStructuredStatus` 会返回 null，但同级键仍使
 * `hasStructuredSubagentMetadata` 返回 true）。将其映射为 `failed` 可保持终态，符合第一阶段的
 * 原有渲染方式。当前没有任何代码路径会再产生该值；它仅用于读侧兼容。
 */
const STRUCTURED_STATUS_TO_SUBTASK: Record<string, SubtaskStatus> = {
  completed: "completed",
  failed: "failed",
  cancelled: "failed",
  timed_out: "failed",
  polling_timed_out: "failed",
  max_turns_reached: "failed",
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
/** 从工具消息中解析结构化或旧格式的子任务结果。 */
export function parseSubtaskResult(
  text: string,
  additionalKwargs?: Record<string, unknown> | null,
): SubtaskResultUpdate {
  const structured = readStructuredStatus(additionalKwargs);
  if (!structured) {
    if (!hasStructuredSubagentMetadata(additionalKwargs)) {
      return parseLegacyTaskResult(text.trim());
    }
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

/** 兼容解析旧版文本格式的子任务结果。 */
function parseLegacyTaskResult(trimmed: string): SubtaskResultUpdate {
  if (trimmed.startsWith(SUCCESS_PREFIX)) {
    return {
      status: "completed",
      result: trimmed.slice(SUCCESS_PREFIX.length).trim(),
    };
  }

  if (trimmed.startsWith(FAILURE_PREFIX)) {
    return {
      status: "failed",
      error: trimmed.slice(FAILURE_PREFIX.length).trim(),
    };
  }

  if (trimmed.startsWith(TIMEOUT_PREFIX)) {
    return { status: "failed", error: trimmed };
  }

  if (trimmed.startsWith(CANCELLED_PREFIX)) {
    return { status: "failed", error: trimmed };
  }

  if (trimmed.startsWith(POLLING_TIMEOUT_PREFIX)) {
    return { status: "failed", error: trimmed };
  }

  if (ERROR_WRAPPER_PATTERN.test(trimmed)) {
    return { status: "failed", error: trimmed };
  }

  return { status: "in_progress" };
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

/** 判断结构化结果是否含有子代理元数据。 */
function hasStructuredSubagentMetadata(
  additionalKwargs: Record<string, unknown> | null | undefined,
): boolean {
  if (!additionalKwargs) return false;
  return STRUCTURED_SUBAGENT_KEYS.some((key) =>
    Object.prototype.hasOwnProperty.call(additionalKwargs, key),
  );
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
