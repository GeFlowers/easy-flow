import { afterEach, describe, expect, rs, test } from "@rstest/core";

import {
  canCreateRegularAccount,
  fetchSetupStatus,
  isSystemAlreadyInitializedError,
  setupStatusFetchInit,
} from "@/core/auth/setup";

describe("auth setup helpers", () => {
  afterEach(() => {
    rs.unstubAllGlobals();
  });

  /**
   * 覆盖“setup-status requests bypass browser caches”这一可观察行为，防止相关边界在重构后回归。

   */

  test("setup-status requests bypass browser caches", () => {
    expect(setupStatusFetchInit).toMatchObject({
      cache: "no-store",
      credentials: "include",
    });
  });

  /**
   * 覆盖“fetchSetupStatus uses the shared no-store request options”这一可观察行为，防止相关边界在重构后回归。

   */

  test("fetchSetupStatus uses the shared no-store request options", async () => {
    const fetchMock = rs.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ needs_setup: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    rs.stubGlobal("fetch", fetchMock);

    await expect(fetchSetupStatus()).resolves.toEqual({ needs_setup: true });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/auth/setup-status",
      setupStatusFetchInit,
    );
  });

  /**
   * 覆盖“regular sign-up is disabled only while setup is required or unknown”这一可观察行为，防止相关边界在重构后回归。

   */

  test("regular sign-up is disabled only while setup is required or unknown", () => {
    expect(canCreateRegularAccount({ checked: false, status: null })).toBe(
      false,
    );
    expect(
      canCreateRegularAccount({
        checked: true,
        status: { needs_setup: true },
      }),
    ).toBe(false);
    expect(
      canCreateRegularAccount({
        checked: true,
        status: { needs_setup: false },
      }),
    ).toBe(true);
    expect(canCreateRegularAccount({ checked: true, status: null })).toBe(true);
  });

  /**
   * 覆盖“detects already-initialized setup conflicts”这一可观察行为，防止相关边界在重构后回归。

   */

  test("detects already-initialized setup conflicts", () => {
    expect(
      isSystemAlreadyInitializedError({
        detail: {
          code: "system_already_initialized",
          message: "System already initialized",
        },
      }),
    ).toBe(true);

    expect(
      isSystemAlreadyInitializedError({
        detail: {
          code: "invalid_credentials",
          message: "Wrong password",
        },
      }),
    ).toBe(false);
  });
});
