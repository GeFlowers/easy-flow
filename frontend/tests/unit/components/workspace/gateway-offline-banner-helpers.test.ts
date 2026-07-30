import { describe, expect, it } from "@rstest/core";

import {
  OFFLINE_BANNER_AUTH_FAILURE_THRESHOLD,
  OFFLINE_BANNER_RETRY_INTERVAL_MS,
  classifyProbe,
  decideProbeAction,
  shouldShowOfflineBanner,
} from "@/components/workspace/gateway-offline-banner-helpers";
import type { User } from "@/core/auth/types";

const fakeUser: User = {
  id: "u1",
  email: "user@example.com",
  system_role: "user",
  needs_setup: false,
};

/**
 * 构造测试所需的稳定夹具，使调用处能够明确复用 makeResponse 的约定。

 */

function makeResponse(status: number, ok = status >= 200 && status < 300) {
  return { status, ok } as Response;
}

describe("shouldShowOfflineBanner", () => {
  /**
   * 覆盖“hides when the gateway is reachable”这一可观察行为，防止相关边界在重构后回归。
   */
  it("hides when the gateway is reachable", () => {
    expect(shouldShowOfflineBanner(null, false)).toBe(false);
    expect(shouldShowOfflineBanner(fakeUser, false)).toBe(false);
  });

  /**
   * 覆盖“shows when the gateway is unavailable and the client has no user yet”这一可观察行为，防止相关边界在重构后回归。

   */

  it("shows when the gateway is unavailable and the client has no user yet", () => {
    expect(shouldShowOfflineBanner(null, true)).toBe(true);
  });

  /**
   * 覆盖“hides as soon as the client recovers an authenticated user”这一可观察行为，防止相关边界在重构后回归。

   */

  it("hides as soon as the client recovers an authenticated user", () => {
    expect(shouldShowOfflineBanner(fakeUser, true)).toBe(false);
  });
});

describe("OFFLINE_BANNER_RETRY_INTERVAL_MS", () => {
  /**
   * 覆盖“is a positive finite number”这一可观察行为，防止相关边界在重构后回归。
   */
  it("is a positive finite number", () => {
    expect(OFFLINE_BANNER_RETRY_INTERVAL_MS).toBeGreaterThan(0);
    expect(Number.isFinite(OFFLINE_BANNER_RETRY_INTERVAL_MS)).toBe(true);
  });
});

describe("OFFLINE_BANNER_AUTH_FAILURE_THRESHOLD", () => {
  /**
   * 覆盖“is an integer greater than 1 so a single transient 401 cannot expire the session”这一可观察行为，防止相关边界在重构后回归。
   */
  it("is an integer greater than 1 so a single transient 401 cannot expire the session", () => {
    expect(Number.isInteger(OFFLINE_BANNER_AUTH_FAILURE_THRESHOLD)).toBe(true);
    expect(OFFLINE_BANNER_AUTH_FAILURE_THRESHOLD).toBeGreaterThan(1);
  });
});

describe("classifyProbe", () => {
  /**
   * 覆盖“returns transient when fetch errored”这一可观察行为，防止相关边界在重构后回归。
   */
  it("returns transient when fetch errored", () => {
    expect(classifyProbe(null, true)).toEqual({ kind: "transient" });
  });

  /**
   * 覆盖“returns transient when response is null with no error flag”这一可观察行为，防止相关边界在重构后回归。

   */

  it("returns transient when response is null with no error flag", () => {
    expect(classifyProbe(null, false)).toEqual({ kind: "transient" });
  });

  /**
   * 覆盖“returns ok with parsed user for a 2xx response with body”这一可观察行为，防止相关边界在重构后回归。

   */

  it("returns ok with parsed user for a 2xx response with body", () => {
    expect(classifyProbe(makeResponse(200), false, fakeUser)).toEqual({
      kind: "ok",
      user: fakeUser,
    });
  });

  /**
   * 覆盖“returns transient for a 2xx response whose body failed to parse”这一可观察行为，防止相关边界在重构后回归。

   */

  it("returns transient for a 2xx response whose body failed to parse", () => {
    // 防御性处理：返回 200 但 JSON 格式错误或模式不匹配时，不应视为“ok”，
    // 因为调用方没有可应用的用户信息。
    expect(classifyProbe(makeResponse(200), false, null)).toEqual({
      kind: "transient",
    });
  });

  /**
   * 覆盖“returns unauthorized for a 401 response”这一可观察行为，防止相关边界在重构后回归。

   */

  it("returns unauthorized for a 401 response", () => {
    expect(classifyProbe(makeResponse(401), false)).toEqual({
      kind: "unauthorized",
    });
  });

  /**
   * 覆盖“returns transient for 5xx responses”这一可观察行为，防止相关边界在重构后回归。

   */

  it("returns transient for 5xx responses", () => {
    expect(classifyProbe(makeResponse(503), false)).toEqual({
      kind: "transient",
    });
    expect(classifyProbe(makeResponse(500), false)).toEqual({
      kind: "transient",
    });
  });

  /**
   * 覆盖“returns transient for unexpected non-401 4xx responses”这一可观察行为，防止相关边界在重构后回归。

   */

  it("returns transient for unexpected non-401 4xx responses", () => {
    expect(classifyProbe(makeResponse(429), false)).toEqual({
      kind: "transient",
    });
  });
});

describe("decideProbeAction", () => {
  /**
   * 覆盖“returns apply-user with the body on a 2xx response”这一可观察行为，防止相关边界在重构后回归。
   */
  it("returns apply-user with the body on a 2xx response", () => {
    expect(decideProbeAction(0, { kind: "ok", user: fakeUser })).toEqual({
      type: "apply-user",
      user: fakeUser,
    });
    // 即使此前累计了一些 401，200 也会立即优先。
    expect(decideProbeAction(2, { kind: "ok", user: fakeUser })).toEqual({
      type: "apply-user",
      user: fakeUser,
    });
  });

  /**
   * 覆盖“treats a single 401 as transient noise and only bumps the counter”这一可观察行为，防止相关边界在重构后回归。

   */

  it("treats a single 401 as transient noise and only bumps the counter", () => {
    expect(decideProbeAction(0, { kind: "unauthorized" })).toEqual({
      type: "noop",
      nextFailureCount: 1,
    });
  });

  /**
   * 覆盖“treats consecutive 401s below the threshold as still transient”这一可观察行为，防止相关边界在重构后回归。

   */

  it("treats consecutive 401s below the threshold as still transient", () => {
    expect(decideProbeAction(1, { kind: "unauthorized" })).toEqual({
      type: "noop",
      nextFailureCount: 2,
    });
  });

  /**
   * 覆盖“delegates to refreshUser as 'session-expired' once 401s reach the threshold”这一可观察行为，防止相关边界在重构后回归。

   */

  it("delegates to refreshUser as 'session-expired' once 401s reach the threshold", () => {
    expect(decideProbeAction(2, { kind: "unauthorized" })).toEqual({
      type: "delegate-refresh",
      reason: "session-expired",
    });
  });

  /**
   * 覆盖“honours a custom threshold (parameterised for safer tests)”这一可观察行为，防止相关边界在重构后回归。

   */

  it("honours a custom threshold (parameterised for safer tests)", () => {
    expect(decideProbeAction(0, { kind: "unauthorized" }, 2)).toEqual({
      type: "noop",
      nextFailureCount: 1,
    });
    expect(decideProbeAction(1, { kind: "unauthorized" }, 2)).toEqual({
      type: "delegate-refresh",
      reason: "session-expired",
    });
  });

  /**
   * 覆盖“decrements (not resets) the auth-failure streak on a transient outcome”这一可观察行为，防止相关边界在重构后回归。

   */

  it("decrements (not resets) the auth-failure streak on a transient outcome", () => {
    // 原值为 2 → 1，因此即使网关在 401↔5xx 之间抖动，计数仍会收敛至
    // 阈值，而不会无限期掩盖会话过期。
    expect(decideProbeAction(2, { kind: "transient" })).toEqual({
      type: "noop",
      nextFailureCount: 1,
    });
    // 最小值为 0，绝不变为负数。
    expect(decideProbeAction(0, { kind: "transient" })).toEqual({
      type: "noop",
      nextFailureCount: 0,
    });
    expect(decideProbeAction(1, { kind: "transient" })).toEqual({
      type: "noop",
      nextFailureCount: 0,
    });
  });

  /**
   * 覆盖“convergence: alternating 401/transient still triggers session-expired”这一可观察行为，防止相关边界在重构后回归。

   */

  it("convergence: alternating 401/transient still triggers session-expired", () => {
    // 模拟 #3493 CR 中的确切场景：抖动的网关交替返回 401（会话已失效）和
    // 503（过载）。采用每次减 1 时，计数器在每组 401/瞬态错误后仍净增 1，
    // 并会达到阈值。
    let count = 0;
    const seq: Array<"unauthorized" | "transient"> = [
      "unauthorized", // count -> 1
      "transient", // count -> 0
      "unauthorized", // count -> 1
      "unauthorized", // count -> 2
      "transient", // count -> 1
      "unauthorized", // count -> 2
    ];
    for (const kind of seq) {
      const action = decideProbeAction(count, { kind });
      expect(action.type).toBe("noop");
      if (action.type === "noop") count = action.nextFailureCount;
    }
    // 下一次 401 应触发阈值（2 -> 3 == threshold）。
    expect(decideProbeAction(count, { kind: "unauthorized" })).toEqual({
      type: "delegate-refresh",
      reason: "session-expired",
    });
  });
});
