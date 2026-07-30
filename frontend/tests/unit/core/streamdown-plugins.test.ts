import { expect, test } from "@rstest/core";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { artifactMarkdownPlugins } from "@/components/workspace/artifacts/markdown-preview-plugins";
import { ArtifactLink } from "@/components/workspace/citations/artifact-link";
import { SafeStreamdown, streamdownPlugins } from "@/core/streamdown";

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 renderArtifactMarkdown 的约定。

 */

function renderArtifactMarkdown(content: string) {
  return renderToStaticMarkup(
    createElement(
      SafeStreamdown,
      { ...artifactMarkdownPlugins, components: { a: ArtifactLink } },
      content,
    ),
  );
}

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 renderSharedMarkdown 的约定。

 */

function renderSharedMarkdown(content: string) {
  return renderToStaticMarkup(
    createElement(SafeStreamdown, streamdownPlugins, content),
  );
}

/**
 * 覆盖“adds GitHub-style heading anchors to artifact markdown previews”这一可观察行为，防止相关边界在重构后回归。

 */

test("adds GitHub-style heading anchors to artifact markdown previews", () => {
  const html = renderArtifactMarkdown(
    ["[概述](#概述)", "", "## 概述"].join("\n"),
  );

  expect(html).toContain('href="#%E6%A6%82%E8%BF%B0"');
  expect(html).toContain('id="概述"');
  expect(html).not.toContain("target=");
});

/**
 * 覆盖“does not add heading anchors to the shared streamdown plugin config”这一可观察行为，防止相关边界在重构后回归。

 */

test("does not add heading anchors to the shared streamdown plugin config", () => {
  const html = [
    renderSharedMarkdown("## Summary"),
    renderSharedMarkdown("## Summary"),
  ].join("");

  expect(html).not.toContain('id="summary"');
});
