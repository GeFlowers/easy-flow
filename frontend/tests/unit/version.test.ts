import { afterEach, expect, test, rs } from "@rstest/core";

import pkg from "../../package.json";

const original = process.env.NEXT_PUBLIC_APP_VERSION;

afterEach(() => {
  rs.resetModules();
  if (original === undefined) {
    delete process.env.NEXT_PUBLIC_APP_VERSION;
  } else {
    process.env.NEXT_PUBLIC_APP_VERSION = original;
  }
});

/**
 * 覆盖“APP_VERSION uses NEXT_PUBLIC_APP_VERSION when set (nightly build-arg)”这一可观察行为，防止相关边界在重构后回归。

 */

test("APP_VERSION uses NEXT_PUBLIC_APP_VERSION when set (nightly build-arg)", async () => {
  process.env.NEXT_PUBLIC_APP_VERSION = "2.1.0-nightly.20260712-abc1234";
  const { APP_VERSION } = await import("@/version");
  expect(APP_VERSION).toBe("2.1.0-nightly.20260712-abc1234");
});

/**
 * 覆盖“APP_VERSION falls back to package.json version when env is unset (local dev)”这一可观察行为，防止相关边界在重构后回归。

 */

test("APP_VERSION falls back to package.json version when env is unset (local dev)", async () => {
  delete process.env.NEXT_PUBLIC_APP_VERSION;
  const { APP_VERSION } = await import("@/version");
  expect(APP_VERSION).toBe(pkg.version);
});

/**
 * 覆盖“APP_VERSION treats an empty NEXT_PUBLIC_APP_VERSION as unset (release Docker build)”这一可观察行为，防止相关边界在重构后回归。

 */

test("APP_VERSION treats an empty NEXT_PUBLIC_APP_VERSION as unset (release Docker build)", async () => {
  // 当前端 Dockerfile 的夜间 CI 未传入 APP_VERSION 时，会设置 ENV NEXT_PUBLIC_APP_VERSION=""；
  // 空字符串必须与未设置变量一样回退到 package.json 版本。
  process.env.NEXT_PUBLIC_APP_VERSION = "";
  const { APP_VERSION } = await import("@/version");
  expect(APP_VERSION).toBe(pkg.version);
});
