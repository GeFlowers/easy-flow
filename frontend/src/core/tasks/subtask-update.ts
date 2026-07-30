import { mergeSteps } from "./steps";
import type { Subtask } from "./types";

/** 判断子任务状态是否已进入终态。 */
export function isTerminalSubtaskStatus(status: Subtask["status"] | undefined) {
  return status === "completed" || status === "failed";
}

/**
 * 单次子任务更新的纯状态转换（#3779）。
 *
 * 将其与 React Hook 分离，既便于单元测试，也确保 Hook 能从函数式 `setTasks` 更新器提供的
 * 最新 `previous` 计算 `next`，而非使用闭包捕获的陈旧 `tasks` 快照。始终从调用方传入的
 * `previous` 推导 `next`，可让进行中的 `fetchSubtaskSteps().then(...)` 合并到当前状态，
 * 而不会覆盖期间到达的 SSE 步骤或同级子任务。
 *
 * `steps` 被视为增量：会合并到 `previous.steps`（按 `message_index` 去重并排序）而不是直接
 * 替换，使实时 SSE 步骤与展开时拉取的回填共同构成同一条时间线。
 */
export function computeNextSubtask(
  previous: Subtask | undefined,
  task: Partial<Subtask> & { id: string },
): { next: Subtask; becameTerminal: boolean; changed: boolean } {
  const previousStatus = previous?.status;

  // MessageList 会先写入待处理工具调用，再在同一渲染解析对应结果；保持终态稳定可避免刷新通知循环。
  const next = {
    ...previous,
    ...task,
    ...(task.status === "in_progress" && isTerminalSubtaskStatus(previousStatus)
      ? { status: previousStatus }
      : {}),
  } as Subtask;

  if (task.steps) {
    next.steps = mergeSteps(previous?.steps ?? [], task.steps);
  }

  // 用量事件是累计快照；迟到的旧帧不得让折叠卡片显示更少的令牌消耗。
  if (
    task.usage &&
    previous?.usage &&
    task.usage.totalTokens < previous.usage.totalTokens
  ) {
    next.usage = previous.usage;
  }

  const becameTerminal =
    isTerminalSubtaskStatus(next.status) && previousStatus !== next.status;

  return { next, becameTerminal, changed: subtaskChanged(previous, next) };
}

/**
 * `next` 相对于 `previous` 是否存在实质性变化？
 *
 * 每次 `MessageList` 渲染都会重新解析终态 `ToolMessage`，而 `parseSubtaskResult` 每次都会将
 * `modelName` 与 `usage` 重建为新对象。按值而非引用比较，才能让 Hook 跳过幂等重新解析产生的
 * 冗余 `setTasks`；否则子代理结束后，新对象标识会导致无限渲染循环。
 */
/** 判断折叠后的子任务是否相较旧状态发生可观察变化。 */
function subtaskChanged(prev: Subtask | undefined, next: Subtask): boolean {
  if (!prev) {
    return true;
  }
  return (
    prev.status !== next.status ||
    prev.modelName !== next.modelName ||
    prev.result !== next.result ||
    prev.error !== next.error ||
    prev.stopReason !== next.stopReason ||
    prev.subagent_type !== next.subagent_type ||
    prev.description !== next.description ||
    prev.prompt !== next.prompt ||
    prev.latestMessage !== next.latestMessage ||
    prev.steps !== next.steps ||
    !usageEquals(prev.usage, next.usage)
  );
}

/** 比较两份可选令牌用量快照是否等价。 */
function usageEquals(a: Subtask["usage"], b: Subtask["usage"]): boolean {
  if (a === b) {
    return true;
  }
  if (!a || !b) {
    return false;
  }
  return (
    a.inputTokens === b.inputTokens &&
    a.outputTokens === b.outputTokens &&
    a.totalTokens === b.totalTokens
  );
}

/** 子任务状态转换应采用的发布时机。 */
export type SubtaskNotification = "eager" | "deferred" | "none";

/**
 * 决定 `useUpdateSubtask` 应如何发布已计算的状态转换。
 *
 * - `deferred`：终态转换。它们在 `MessageList` 渲染期间到达（组件会内联解析 `ToolMessage`），
 *   因而不能在渲染中调用 `setTasks`；Hook 会标记引用，并在渲染后的 Effect 中发布。
 * - `eager`：实际改变状态的实时 SSE 更新（步骤、`latestMessage`、模型或用量），应从异步回调
 *   立即发布。
 * - `none`：状态没有变化。关键在于重新解析的终态结果仍会携带 `modelName` 与 `usage`，因此以
 *   `changed` 而非字段是否存在作为条件，才能阻止渲染循环。
 */
export function subtaskNotification(
  task: Partial<Subtask> & { id: string },
  transition: { becameTerminal: boolean; changed: boolean },
): SubtaskNotification {
  if (transition.becameTerminal) {
    return "deferred";
  }
  if (
    transition.changed &&
    (task.latestMessage || task.steps || task.modelName || task.usage)
  ) {
    return "eager";
  }
  return "none";
}
