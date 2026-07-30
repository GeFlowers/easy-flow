import { expect, test } from "@rstest/core";

import { sanitizeRunStreamOptions } from "@/core/api/stream-mode";

/**
 * 覆盖“drops unsupported stream modes from array payloads”这一可观察行为，防止相关边界在重构后回归。

 */

test("drops unsupported stream modes from array payloads", () => {
  const sanitized = sanitizeRunStreamOptions({
    streamMode: [
      "values",
      "messages-tuple",
      "custom",
      "updates",
      "events",
      "tools",
    ],
  });

  expect(sanitized.streamMode).toEqual([
    "values",
    "messages-tuple",
    "custom",
    "updates",
    "events",
  ]);
});

/**
 * 覆盖“drops unsupported stream modes from scalar payloads”这一可观察行为，防止相关边界在重构后回归。

 */

test("drops unsupported stream modes from scalar payloads", () => {
  const sanitized = sanitizeRunStreamOptions({
    streamMode: "tools",
  });

  expect(sanitized.streamMode).toBeUndefined();
});

/**
 * 覆盖“keeps payloads without streamMode untouched”这一可观察行为，防止相关边界在重构后回归。

 */

test("keeps payloads without streamMode untouched", () => {
  const options = {
    streamSubgraphs: true,
  };

  expect(sanitizeRunStreamOptions(options)).toBe(options);
});
