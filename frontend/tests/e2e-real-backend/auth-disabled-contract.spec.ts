import { expect, test } from "@playwright/test";

import { AUTH_DISABLED_USER } from "../../src/core/auth/auth-disabled-user";

const APP =
  process.env.E2E_APP_URL ??
  `http://localhost:${process.env.E2E_FRONTEND_PORT ?? "3000"}`;

test.describe("auth-disabled contract (real backend)", () => {
  /**
   * 覆盖“gateway /auth/me returns the frontend synthetic user without a cookie”这一可观察行为，防止相关边界在重构后回归。
   */
  test("gateway /auth/me returns the frontend synthetic user without a cookie", async ({
    context,
  }) => {
    const resp = await context.request.get(`${APP}/api/v1/auth/me`);

    expect(resp.status(), await resp.text()).toBe(200);
    await expect(resp.json()).resolves.toEqual(AUTH_DISABLED_USER);
  });
});
