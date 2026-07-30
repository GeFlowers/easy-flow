import {
  afterEach,
  beforeEach,
  describe,
  expect,
  test,
  rs,
} from "@rstest/core";

import { AUTH_DISABLED_USER } from "@/core/auth/auth-disabled-user";
import { STATIC_WEBSITE_USER } from "@/core/auth/static-user";

rs.mock("next/headers", () => ({
  cookies: rs.fn(() => {
    throw new Error("cookies should not be read in static website mode");
  }),
}));

const ENV_KEYS = [
  "DEER_FLOW_AUTH_DISABLED",
  "DEER_FLOW_ENV",
  "ENVIRONMENT",
  "NEXT_PUBLIC_STATIC_WEBSITE_ONLY",
] as const;

type EnvSnapshot = Partial<
  Record<(typeof ENV_KEYS)[number], string | undefined>
>;

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 snapshotEnv 的约定。

 */

function snapshotEnv(): EnvSnapshot {
  const snapshot: EnvSnapshot = {};
  for (const key of ENV_KEYS) {
    snapshot[key] = process.env[key];
  }
  return snapshot;
}

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 setEnv 的约定。

 */

function setEnv(key: (typeof ENV_KEYS)[number], value: string | undefined) {
  const env = process.env as Record<string, string | undefined>;
  if (value === undefined) {
    delete env[key];
  } else {
    env[key] = value;
  }
}

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 restoreEnv 的约定。

 */

function restoreEnv(snapshot: EnvSnapshot) {
  for (const key of ENV_KEYS) {
    setEnv(key, snapshot[key]);
  }
}

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 loadFreshServerAuth 的约定。

 */

async function loadFreshServerAuth() {
  rs.resetModules();
  return await import("@/core/auth/server");
}

describe("getServerSideUser", () => {
  let saved: EnvSnapshot;

  beforeEach(() => {
    saved = snapshotEnv();
    setEnv("DEER_FLOW_AUTH_DISABLED", undefined);
    setEnv("DEER_FLOW_ENV", undefined);
    setEnv("ENVIRONMENT", undefined);
    setEnv("NEXT_PUBLIC_STATIC_WEBSITE_ONLY", undefined);
  });

  afterEach(() => {
    restoreEnv(saved);
    rs.unstubAllGlobals();
  });

  /**
   * 覆盖“bypasses gateway auth in static website mode”这一可观察行为，防止相关边界在重构后回归。

   */

  test("bypasses gateway auth in static website mode", async () => {
    setEnv("NEXT_PUBLIC_STATIC_WEBSITE_ONLY", "true");
    const fetchSpy = rs.fn(() => {
      throw new Error("fetch should not be called in static website mode");
    });
    rs.stubGlobal("fetch", fetchSpy);

    const { getServerSideUser } = await loadFreshServerAuth();

    await expect(getServerSideUser()).resolves.toEqual({
      tag: "authenticated",
      user: STATIC_WEBSITE_USER,
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  /**
   * 覆盖“bypasses gateway auth in auth-disabled mode”这一可观察行为，防止相关边界在重构后回归。

   */

  test("bypasses gateway auth in auth-disabled mode", async () => {
    setEnv("DEER_FLOW_AUTH_DISABLED", "1");
    const fetchSpy = rs.fn(() => {
      throw new Error("fetch should not be called in auth-disabled mode");
    });
    rs.stubGlobal("fetch", fetchSpy);

    const { getServerSideUser } = await loadFreshServerAuth();

    await expect(getServerSideUser()).resolves.toEqual({
      tag: "authenticated",
      user: AUTH_DISABLED_USER,
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  /**
   * 覆盖“does not enable auth-disabled mode in explicit production environments”这一可观察行为，防止相关边界在重构后回归。

   */

  test("does not enable auth-disabled mode in explicit production environments", async () => {
    setEnv("DEER_FLOW_AUTH_DISABLED", "1");
    setEnv("DEER_FLOW_ENV", "production");

    const { isAuthDisabledMode } =
      await import("@/core/auth/auth-disabled-user");

    expect(isAuthDisabledMode()).toBe(false);
  });
});

describe("getServerSideUser — gateway_unavailable contract (issue #3493)", () => {
  let saved: EnvSnapshot;

  beforeEach(() => {
    saved = snapshotEnv();
    setEnv("DEER_FLOW_AUTH_DISABLED", undefined);
    setEnv("NEXT_PUBLIC_STATIC_WEBSITE_ONLY", undefined);
  });

  afterEach(() => {
    restoreEnv(saved);
    rs.unstubAllGlobals();
    rs.doUnmock("next/headers");
  });

  /**
   * 覆盖“returns gateway_unavailable when /auth/me fetch rejects (e.g. AbortError)”这一可观察行为，防止相关边界在重构后回归。

   */

  test("returns gateway_unavailable when /auth/me fetch rejects (e.g. AbortError)", async () => {
    rs.doMock("next/headers", () => ({
      cookies: rs.fn(async () => ({
        get: (name: string) =>
          name === "access_token" ? { value: "stub-token" } : undefined,
      })),
    }));
    const abortErr = new DOMException("Aborted", "AbortError");
    rs.stubGlobal(
      "fetch",
      rs.fn(() => Promise.reject(abortErr)),
    );

    const { getServerSideUser } = await loadFreshServerAuth();

    await expect(getServerSideUser()).resolves.toEqual({
      tag: "gateway_unavailable",
    });
  });

  /**
   * 覆盖“returns gateway_unavailable when /auth/me responds with a 5xx”这一可观察行为，防止相关边界在重构后回归。

   */

  test("returns gateway_unavailable when /auth/me responds with a 5xx", async () => {
    rs.doMock("next/headers", () => ({
      cookies: rs.fn(async () => ({
        get: (name: string) =>
          name === "access_token" ? { value: "stub-token" } : undefined,
      })),
    }));
    rs.stubGlobal(
      "fetch",
      rs.fn(() =>
        Promise.resolve(
          new Response("upstream error", {
            status: 503,
            statusText: "Service Unavailable",
          }),
        ),
      ),
    );

    const { getServerSideUser } = await loadFreshServerAuth();

    await expect(getServerSideUser()).resolves.toEqual({
      tag: "gateway_unavailable",
    });
  });
});
