import { describe, expect, it } from "@rstest/core";
import { createElement, type ImgHTMLAttributes } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { MarkdownContent } from "@/components/workspace/messages/markdown-content";

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 renderMarkdown 的约定。

 */

function renderMarkdown(
  content: string,
  isLoading: boolean,
  components?: Parameters<typeof MarkdownContent>[0]["components"],
) {
  return renderToStaticMarkup(
    createElement(MarkdownContent, { content, isLoading, components }),
  );
}

describe("MarkdownContent streaming code blocks", () => {
  /**
   * 覆盖“renders fenced code without Streamdown highlighting while streaming”这一可观察行为，防止相关边界在重构后回归。
   */
  it("renders fenced code without Streamdown highlighting while streaming", () => {
    const html = renderMarkdown(
      ["```html", '<main class="report">Hello</main>', "```"].join("\n"),
      true,
    );

    expect(html).toContain("data-streaming-code-block");
    expect(html).toContain('data-language="html"');
    expect(html).toContain(
      "&lt;main class=&quot;report&quot;&gt;Hello&lt;/main&gt;",
    );
    expect(html).not.toContain('data-streamdown="code-block"');
  });

  /**
   * 覆盖“keeps inline code inline while streaming”这一可观察行为，防止相关边界在重构后回归。

   */

  it("keeps inline code inline while streaming", () => {
    const html = renderMarkdown("Use `const answer = 42` here.", true);

    expect(html).toContain('data-streaming-inline-code="true"');
    expect(html).not.toContain("data-streaming-code-block");
  });

  /**
   * 覆盖“keeps an unlabeled single-line fence as a block while streaming”这一可观察行为，防止相关边界在重构后回归。

   */

  it("keeps an unlabeled single-line fence as a block while streaming", () => {
    const html = renderMarkdown(["```", "x", "```"].join("\n"), true);

    expect(html).toContain("data-streaming-code-block");
    expect(html).not.toContain('data-streaming-inline-code="true"');
  });

  /**
   * 覆盖“restores Streamdown highlighting after streaming finishes”这一可观察行为，防止相关边界在重构后回归。

   */

  it("restores Streamdown highlighting after streaming finishes", () => {
    const html = renderMarkdown(
      ["```html", '<main class="report">Hello</main>', "```"].join("\n"),
      false,
    );

    expect(html).toContain('data-streamdown="code-block"');
    expect(html).not.toContain("data-streaming-code-block");
  });

  /**
   * 覆盖“preserves custom non-code renderers while streaming”这一可观察行为，防止相关边界在重构后回归。

   */

  it("preserves custom non-code renderers while streaming", () => {
    const html = renderMarkdown(
      "[Docs](https://example.com)\n\n![Chart](chart.png)",
      true,
      {
        a: ({ children, href }) =>
          createElement("a", { "data-custom-link": true, href }, children),
        img: (props: ImgHTMLAttributes<HTMLImageElement>) =>
          createElement("img", { ...props, "data-custom-image": true }),
      },
    );

    expect(html).toContain('data-custom-link="true"');
    expect(html).toContain('data-custom-image="true"');
  });

  /**
   * 覆盖“preserves a caller-provided code renderer while streaming”这一可观察行为，防止相关边界在重构后回归。

   */

  it("preserves a caller-provided code renderer while streaming", () => {
    const html = renderMarkdown(
      ["```html", "<main />", "```"].join("\n"),
      true,
      {
        code: ({ children }) =>
          createElement("code", { "data-custom-code": true }, children),
      },
    );

    expect(html).toContain('data-custom-code="true"');
    expect(html).toContain("data-streaming-code-block");
  });
});
