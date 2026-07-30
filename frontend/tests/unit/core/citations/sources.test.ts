import { describe, expect, it } from "@rstest/core";

import {
  extractCitationSources,
  formatCitationMarkdownReference,
} from "@/core/citations/sources";

describe("extractCitationSources", () => {
  /**
   * 覆盖“extracts citation markdown links in first-seen order”这一可观察行为，防止相关边界在重构后回归。
   */
  it("extracts citation markdown links in first-seen order", () => {
    const markdown = [
      "Deep research needs evidence [citation:Paper A](https://example.com/a).",
      "A second claim cites [citation:Report B](https://news.example.org/report?x=1).",
    ].join("\n");
    const firstIndex = markdown.indexOf("[citation:Paper A]");
    const secondIndex = markdown.indexOf("[citation:Report B]");

    expect(extractCitationSources(markdown)).toEqual([
      {
        id: "https://example.com/a",
        title: "Paper A",
        url: "https://example.com/a",
        domain: "example.com",
        count: 1,
        occurrences: [{ index: firstIndex, title: "Paper A" }],
      },
      {
        id: "https://news.example.org/report?x=1",
        title: "Report B",
        url: "https://news.example.org/report?x=1",
        domain: "news.example.org",
        count: 1,
        occurrences: [{ index: secondIndex, title: "Report B" }],
      },
    ]);
  });

  /**
   * 覆盖“deduplicates repeated citation URLs and preserves occurrence titles”这一可观察行为，防止相关边界在重构后回归。

   */

  it("deduplicates repeated citation URLs and preserves occurrence titles", () => {
    const markdown = [
      "First [citation:Original Title](https://example.com/research).",
      "Later [citation:Updated Title](https://example.com/research).",
    ].join("\n");
    const firstIndex = markdown.indexOf("[citation:Original Title]");
    const secondIndex = markdown.indexOf("[citation:Updated Title]");

    expect(extractCitationSources(markdown)).toEqual([
      {
        id: "https://example.com/research",
        title: "Original Title",
        url: "https://example.com/research",
        domain: "example.com",
        count: 2,
        occurrences: [
          { index: firstIndex, title: "Original Title" },
          { index: secondIndex, title: "Updated Title" },
        ],
      },
    ]);
  });

  /**
   * 覆盖“ignores normal links, image links, and citations inside fenced code”这一可观察行为，防止相关边界在重构后回归。

   */

  it("ignores normal links, image links, and citations inside fenced code", () => {
    const markdown = [
      "[Normal](https://example.com/normal)",
      "![citation:Image](https://example.com/image.png)",
      "```md",
      "[citation:Example](https://example.com/example)",
      "```",
      "Real source [citation:Real](https://example.com/real).",
    ].join("\n");
    const realIndex = markdown.indexOf("[citation:Real]");

    expect(extractCitationSources(markdown)).toEqual([
      {
        id: "https://example.com/real",
        title: "Real",
        url: "https://example.com/real",
        domain: "example.com",
        count: 1,
        occurrences: [{ index: realIndex, title: "Real" }],
      },
    ]);
  });

  /**
   * 覆盖“keeps every source when citations are directly adjacent”这一可观察行为，防止相关边界在重构后回归。

   */

  it("keeps every source when citations are directly adjacent", () => {
    const markdown =
      "[citation:A](https://example.com/a)[citation:B](https://example.com/b)[citation:C](https://example.com/c)";

    expect(extractCitationSources(markdown).map((s) => s.url)).toEqual([
      "https://example.com/a",
      "https://example.com/b",
      "https://example.com/c",
    ]);
  });

  /**
   * 覆盖“keeps URLs that contain multiple balanced parenthetical groups”这一可观察行为，防止相关边界在重构后回归。

   */

  it("keeps URLs that contain multiple balanced parenthetical groups", () => {
    const markdown = "[citation:W](https://en.wikipedia.org/wiki/Foo_(a)_(b))";

    expect(extractCitationSources(markdown)[0]).toMatchObject({
      url: "https://en.wikipedia.org/wiki/Foo_(a)_(b)",
      domain: "en.wikipedia.org",
    });
  });

  /**
   * 覆盖“ignores citations inside inline code spans”这一可观察行为，防止相关边界在重构后回归。

   */

  it("ignores citations inside inline code spans", () => {
    const markdown =
      "Example: `[citation:X](https://x.com/inline)` then real [citation:Real](https://example.com/real).";

    expect(extractCitationSources(markdown).map((s) => s.url)).toEqual([
      "https://example.com/real",
    ]);
  });

  /**
   * 覆盖“ignores citations inside an unclosed fenced code block”这一可观察行为，防止相关边界在重构后回归。

   */

  it("ignores citations inside an unclosed fenced code block", () => {
    const markdown = [
      "Streaming output:",
      "```md",
      "[citation:Streaming](https://example.com/streaming)",
    ].join("\n");

    expect(extractCitationSources(markdown)).toEqual([]);
  });

  /**
   * 覆盖“uses the source domain when the citation label is generic”这一可观察行为，防止相关边界在重构后回归。

   */

  it("uses the source domain when the citation label is generic", () => {
    const markdown = "See [citation:Source](https://www.example.com/path).";

    expect(extractCitationSources(markdown)[0]).toMatchObject({
      title: "example.com",
      domain: "example.com",
      url: "https://www.example.com/path",
    });
  });
});

describe("formatCitationMarkdownReference", () => {
  /**
   * 覆盖“formats a source as a reusable markdown reference”这一可观察行为，防止相关边界在重构后回归。
   */
  it("formats a source as a reusable markdown reference", () => {
    const [source] = extractCitationSources(
      "Evidence [citation:Paper A](https://example.com/a).",
    );

    expect(formatCitationMarkdownReference(source!)).toBe(
      "[Paper A](https://example.com/a)",
    );
  });
});
