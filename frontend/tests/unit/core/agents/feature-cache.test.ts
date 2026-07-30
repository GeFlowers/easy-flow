import { afterEach, describe, expect, test } from "@rstest/core";

import {
  readCachedAgentsApiEnabled,
  resolveAgentsApiEnabled,
  writeCachedAgentsApiEnabled,
} from "@/core/agents/feature-cache";

describe("resolveAgentsApiEnabled", () => {
  /**
   * 覆盖“a live value always wins over the cache”这一可观察行为，防止相关边界在重构后回归。
   */
  test("a live value always wins over the cache", () => {
    expect(resolveAgentsApiEnabled(true, false)).toBe(true);
    expect(resolveAgentsApiEnabled(false, true)).toBe(false);
  });

  /**
   * 覆盖“falls back to the cached value when live is unknown (sticky)”这一可观察行为，防止相关边界在重构后回归。

   */

  test("falls back to the cached value when live is unknown (sticky)", () => {
    // `/api/features` 不可用期间，已禁用状态仍保持禁用，以免 403 风暴（#3757）
    // 重现。
    expect(resolveAgentsApiEnabled(undefined, false)).toBe(false);
    expect(resolveAgentsApiEnabled(undefined, true)).toBe(true);
  });

  /**
   * 覆盖“fails open only when nothing has ever been observed”这一可观察行为，防止相关边界在重构后回归。

   */

  test("fails open only when nothing has ever been observed", () => {
    expect(resolveAgentsApiEnabled(undefined, undefined)).toBe(true);
  });
});

describe("agents_api feature cache persistence", () => {
  const store = new Map<string, string>();
  const fakeWindow = {
    localStorage: {
      getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
      setItem: (k: string, v: string) => {
        store.set(k, v);
      },
      removeItem: (k: string) => {
        store.delete(k);
      },
    },
  };

  afterEach(() => {
    store.clear();
    delete (globalThis as { window?: unknown }).window;
  });

  /**
   * 覆盖“round-trips a persisted value”这一可观察行为，防止相关边界在重构后回归。

   */

  test("round-trips a persisted value", () => {
    (globalThis as { window?: unknown }).window = fakeWindow;
    writeCachedAgentsApiEnabled(false);
    expect(readCachedAgentsApiEnabled()).toBe(false);
    writeCachedAgentsApiEnabled(true);
    expect(readCachedAgentsApiEnabled()).toBe(true);
  });

  /**
   * 覆盖“returns undefined when nothing is stored”这一可观察行为，防止相关边界在重构后回归。

   */

  test("returns undefined when nothing is stored", () => {
    (globalThis as { window?: unknown }).window = fakeWindow;
    expect(readCachedAgentsApiEnabled()).toBeUndefined();
  });

  /**
   * 覆盖“no-ops without a browser environment (SSR)”这一可观察行为，防止相关边界在重构后回归。

   */

  test("no-ops without a browser environment (SSR)", () => {
    // 在 node 测试环境中，window 为 undefined。
    expect(readCachedAgentsApiEnabled()).toBeUndefined();
    expect(() => writeCachedAgentsApiEnabled(true)).not.toThrow();
  });
});
