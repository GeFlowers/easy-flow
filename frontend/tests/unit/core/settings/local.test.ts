import { expect, test } from "@rstest/core";

import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";

/**
 * 覆盖“defaults token usage to header total plus per-turn breakdown”这一可观察行为，防止相关边界在重构后回归。

 */

test("defaults token usage to header total plus per-turn breakdown", () => {
  expect(DEFAULT_LOCAL_SETTINGS.tokenUsage).toEqual({
    headerTotal: true,
    inlineMode: "per_turn",
  });
});
