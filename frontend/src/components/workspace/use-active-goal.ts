import { useEffect, useRef, useState } from "react";

import type { GoalState } from "@/core/threads/types";

import { goalReconciliationKey } from "./goal-status-helpers";

export type UseActiveGoalResult = {
  /** 待渲染的目标：存在本地乐观覆盖时使用覆盖值，否则使用服务端状态。 */
  activeGoal: GoalState | null;
  hasGoal: boolean;
  /** 在 `/goal` 命令后应用乐观目标；传入 `null` 时隐藏目标。 */
  setLocalGoal: (goal: GoalState | null) => void;
};

/** 优先返回本地乐观目标；未覆盖时使用服务端线程状态。 */
export function resolveActiveGoal(
  localGoal: GoalState | null | undefined,
  serverGoal: GoalState | null | undefined,
): GoalState | null {
  return localGoal !== undefined ? localGoal : (serverGoal ?? null);
}

/** 判断服务端目标是否已追上本地乐观覆盖，从而可安全清除覆盖。 */
export function shouldResetLocalGoalOverride({
  serverGoalProvided,
  threadChanged,
}: {
  serverGoalProvided: boolean;
  threadChanged: boolean;
}): boolean {
  if (threadChanged) {
    return true;
  }
  return serverGoalProvided;
}

/** 管理编辑器目标命令产生的乐观展示状态，并与流式线程状态协调。 */
export function useActiveGoal(
  threadId: string,
  serverGoal: GoalState | null | undefined,
): UseActiveGoalResult {
  const [localGoal, setLocalGoal] = useState<GoalState | null | undefined>(
    undefined,
  );
  const previousThreadIdRef = useRef(threadId);
  const serverGoalProvided = serverGoal !== undefined;
  const serverGoalKey = serverGoalProvided
    ? goalReconciliationKey(serverGoal)
    : "missing";

  useEffect(() => {
    const threadChanged = previousThreadIdRef.current !== threadId;
    previousThreadIdRef.current = threadId;
    if (shouldResetLocalGoalOverride({ serverGoalProvided, threadChanged })) {
      setLocalGoal(undefined);
    }
  }, [serverGoalKey, serverGoalProvided, threadId]);

  const activeGoal = resolveActiveGoal(localGoal, serverGoal);
  return { activeGoal, hasGoal: Boolean(activeGoal), setLocalGoal };
}
