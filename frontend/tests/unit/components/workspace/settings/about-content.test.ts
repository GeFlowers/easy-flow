import { afterEach, expect, test, rs } from "@rstest/core";

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
 * 覆盖“aboutMarkdown heading interpolates the app version”这一可观察行为，防止相关边界在重构后回归。

 */

test("aboutMarkdown heading interpolates the app version", async () => {
  process.env.NEXT_PUBLIC_APP_VERSION = "9.9.9-test";
  const { aboutMarkdown } =
    await import("@/components/workspace/settings/about-content");
  // 标题链接文本携带版本标记。
  expect(aboutMarkdown).toContain("[About DeerFlow 9.9.9-test]");
  // 致谢中的里程碑文案指向 1.0/2.0 产品世代，绝不能参数化。
  expect(aboutMarkdown).toContain("DeerFlow 1.0 and 2.0");
});

/**
 * 覆盖“aboutMarkdown heading reflects the package version when env is unset”这一可观察行为，防止相关边界在重构后回归。

 */

test("aboutMarkdown heading reflects the package version when env is unset", async () => {
  delete process.env.NEXT_PUBLIC_APP_VERSION;
  const { APP_VERSION } = await import("@/version");
  const { aboutMarkdown } =
    await import("@/components/workspace/settings/about-content");
  // 正向校验：标题携带真实的已解析版本。它能捕获空或 undefined 的 APP_VERSION
  // 插值（`About DeerFlow ]` / `About DeerFlow undefined]`），而不只是捕获
  // 旧字面量被移除的情况。
  expect(aboutMarkdown).toContain(`[About DeerFlow ${APP_VERSION}]`);
});
