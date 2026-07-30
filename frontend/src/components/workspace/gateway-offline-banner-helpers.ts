/** 网关离线横幅重新探测认证端点的固定间隔。 */
export const OFFLINE_BANNER_RETRY_INTERVAL_MS = 10_000;

/** 连续收到此数量的 401 后视为会话过期，并交由 AuthProvider.refreshUser() 重定向 `/login`；大于 1 可吸收网关刚恢复时的短暂 401，同时不会永久掩盖真正失效的 cookie。 */
export const OFFLINE_BANNER_AUTH_FAILURE_THRESHOLD = 3;

import type { User } from "@/core/auth/types";

/** 判断服务端探测结果是否需要进入网关离线横幅降级流程。 */
export function shouldShowOfflineBanner(
  user: User | null,
  gatewayUnavailable: boolean,
): boolean {
  return gatewayUnavailable && user === null;
}

/** 单次 /auth/me 探测的分类结果。 */
export type ProbeOutcome =
  | { kind: "ok"; user: User } // 具有可解析响应体的 2xx
  | { kind: "unauthorized" } // 401
  | { kind: "transient" }; // 5xx、网络异常、中止、响应体无效等

/** 横幅副作用在探测结束后应采取的下一步操作。 */
export type ProbeAction =
  | { type: "apply-user"; user: User }
  | { type: "delegate-refresh"; reason: "session-expired" }
  | { type: "noop"; nextFailureCount: number };

/** 纯函数：将 HTTP 探测结果归类为 ProbeOutcome。它从横幅副作用中拆出以便独立测试；`parsedUser` 是 2xx 响应的 JSON 体（缺失或无效时为 null），调用方可直接应用，避免通过 refreshUser() 再请求一次 `/auth/me`。 */
export function classifyProbe(
  res: Response | null,
  errored: boolean,
  parsedUser: User | null = null,
): ProbeOutcome {
  if (errored || res === null) return { kind: "transient" };
  if (res.ok && parsedUser !== null) return { kind: "ok", user: parsedUser };
  if (res.ok) return { kind: "transient" }; // 虽为 2xx，但响应体不可用
  if (res.status === 401) return { kind: "unauthorized" };
  return { kind: "transient" };
}

/** 纯状态机：根据累计 401 次数和新探测结果决定应用用户、委托 refreshUser() 重定向 `/login`，或仅更新计数。短暂结果（5xx、网络异常、中止）将失败连续值减一且不低于零，而非清零；这样网关在 401 与 5xx 间波动时，计数仍会收敛到会话过期阈值。 */
export function decideProbeAction(
  consecutiveAuthFailures: number,
  outcome: ProbeOutcome,
  threshold: number = OFFLINE_BANNER_AUTH_FAILURE_THRESHOLD,
): ProbeAction {
  if (outcome.kind === "ok") {
    return { type: "apply-user", user: outcome.user };
  }
  if (outcome.kind === "unauthorized") {
    const next = consecutiveAuthFailures + 1;
    if (next >= threshold) {
      return { type: "delegate-refresh", reason: "session-expired" };
    }
    return { type: "noop", nextFailureCount: next };
  }
  // 短暂故障时递减而非重置，避免网关在 401 与 5xx 间反复波动时
  // 无法最终收敛为会话已过期。
  return {
    type: "noop",
    nextFailureCount: Math.max(0, consecutiveAuthFailures - 1),
  };
}
