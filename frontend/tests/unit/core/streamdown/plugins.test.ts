import { expect, test } from "@rstest/core";
import rehypeRaw from "rehype-raw";

import { reasoningPlugins, streamdownPlugins } from "@/core/streamdown/plugins";

/**
 * 覆盖“streamdownPlugins includes rehypeRaw”这一可观察行为，防止相关边界在重构后回归。

 */

test("streamdownPlugins includes rehypeRaw", () => {
  expect(streamdownPlugins.rehypePlugins).toContain(rehypeRaw);
});

/**
 * 覆盖“reasoningPlugins does not include rehypeRaw”这一可观察行为，防止相关边界在重构后回归。

 */

test("reasoningPlugins does not include rehypeRaw", () => {
  const flat = reasoningPlugins.rehypePlugins?.flat();
  expect(flat).not.toContain(rehypeRaw);
});
