import type { GoalState } from "@/core/threads";

export type GoalContinuationDisplay = {
  count: number;
  max: number;
};

/** 决定活动目标是否显示续跑计数。代理尚未自动续跑（`continuation_count > 0`）时返回 `null`，避免将含义不明的 “0/8” 展示给用户；开始续跑后显示 `{count}/{max}` 并提供说明提示。 */
export function getGoalContinuationDisplay(
  goal: Pick<GoalState, "continuation_count" | "max_continuations">,
): GoalContinuationDisplay | null {
  const count = goal.continuation_count ?? 0;
  const max = goal.max_continuations ?? 0;
  if (!Number.isFinite(count) || count <= 0) {
    return null;
  }
  return { count, max };
}

/** 生成服务端目标的稳定签名，以判断客户端乐观覆盖何时应让位给服务端状态。新设目标（`created_at`）、代理自动续跑（`continuation_count` / `updated_at`）或后端清除、满足目标（`null`）均会改变签名；`useActiveGoal` 据此重置乐观副本，避免流式续跑计数长期被遮蔽。 */
export function goalReconciliationKey(goal: GoalState | null): string {
  if (!goal) {
    return "none";
  }
  return [
    goal.objective,
    goal.status,
    goal.created_at ?? "",
    goal.updated_at ?? "",
    goal.continuation_count ?? 0,
  ].join("|");
}
