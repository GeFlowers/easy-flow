import { describe, expect, it } from "@rstest/core";

import {
  formatSubtaskTokenUsage,
  resolveSubtaskModelLabel,
} from "@/core/tasks/presentation";

describe("resolveSubtaskModelLabel", () => {
  /**
   * 覆盖“prefers the configured display name and falls back to the model identifier”这一可观察行为，防止相关边界在重构后回归。
   */
  it("prefers the configured display name and falls back to the model identifier", () => {
    expect(
      resolveSubtaskModelLabel("claude-3-7-sonnet", [
        {
          id: "model-1",
          name: "claude-3-7-sonnet",
          model: "claude-3-7-sonnet@20250219",
          display_name: "Claude 3.7 Sonnet",
        },
      ]),
    ).toBe("Claude 3.7 Sonnet");

    expect(resolveSubtaskModelLabel("unlisted-model", [])).toBe(
      "unlisted-model",
    );
  });

  /**
   * 覆盖“formats only reported cumulative token usage”这一可观察行为，防止相关边界在重构后回归。

   */

  it("formats only reported cumulative token usage", () => {
    expect(formatSubtaskTokenUsage(undefined)).toBeUndefined();
    expect(
      formatSubtaskTokenUsage({
        inputTokens: 10_000,
        outputTokens: 2_345,
        totalTokens: 12_345,
      }),
    ).toBe("12.3K");
  });
});
