import { expect, test } from "@rstest/core";

import {
  capBlockquoteNesting,
  capListNesting,
  capMarkdownNesting,
  compactDisplayMathBlocks,
  normalizeStreamdownMathMarkdown,
  preprocessStreamdownMarkdown,
} from "@/core/streamdown/preprocess";

/**
 * 覆盖“capBlockquoteNesting returns normal content unchanged”这一可观察行为，防止相关边界在重构后回归。

 */

test("capBlockquoteNesting returns normal content unchanged", () => {
  const input = "# Title\n\n> a quote\n>> nested\n\nsome `code`";
  expect(capBlockquoteNesting(input)).toBe(input);
});

/**
 * 覆盖“capBlockquoteNesting keeps nesting at or below the cap untouched”这一可观察行为，防止相关边界在重构后回归。

 */

test("capBlockquoteNesting keeps nesting at or below the cap untouched", () => {
  const input = "> ".repeat(100) + "hi";
  expect(capBlockquoteNesting(input)).toBe(input);
});

/**
 * 覆盖“capBlockquoteNesting caps pathological nesting and preserves content”这一可观察行为，防止相关边界在重构后回归。

 */

test("capBlockquoteNesting caps pathological nesting and preserves content", () => {
  const result = capBlockquoteNesting("> ".repeat(5000) + "hi");
  expect((result.match(/>/g) ?? []).length).toBe(100);
  expect(result.endsWith("hi")).toBe(true);
});

/**
 * 覆盖“capBlockquoteNesting handles markers without spaces”这一可观察行为，防止相关边界在重构后回归。

 */

test("capBlockquoteNesting handles markers without spaces", () => {
  const result = capBlockquoteNesting(">".repeat(5000) + "hi");
  expect((result.match(/>/g) ?? []).length).toBe(100);
  expect(result.endsWith("hi")).toBe(true);
});

/**
 * 覆盖“capBlockquoteNesting leaves fenced code content untouched”这一可观察行为，防止相关边界在重构后回归。

 */

test("capBlockquoteNesting leaves fenced code content untouched", () => {
  const literal = ">".repeat(150);
  const input = `${"> ".repeat(3000)}hi\n\`\`\`text\n${literal}\n\`\`\``;
  const result = capBlockquoteNesting(input);
  expect(result.split("\n")[2]).toBe(literal);
});

/**
 * 覆盖“capBlockquoteNesting leaves indented code blocks untouched”这一可观察行为，防止相关边界在重构后回归。

 */

test("capBlockquoteNesting leaves indented code blocks untouched", () => {
  const literal = "    " + ">".repeat(150);
  const input = `${"> ".repeat(3000)}hi\n\n${literal}`;
  const result = capBlockquoteNesting(input);
  expect(result.split("\n")[2]).toBe(literal);
});

/**
 * 覆盖“capBlockquoteNesting only rewrites pathological lines”这一可观察行为，防止相关边界在重构后回归。

 */

test("capBlockquoteNesting only rewrites pathological lines", () => {
  const normal = "> normal quote";
  const deep = "> ".repeat(3000) + "deep";
  const result = capBlockquoteNesting(`${normal}\n${deep}\nplain`);
  const lines = result.split("\n");
  expect(lines[0]).toBe(normal);
  expect((lines[1]?.match(/>/g) ?? []).length).toBe(100);
  expect(lines[2]).toBe("plain");
});

/**
 * 覆盖“capListNesting returns normally indented content unchanged”这一可观察行为，防止相关边界在重构后回归。

 */

test("capListNesting returns normally indented content unchanged", () => {
  const input = "- a\n  - b\n    - c\n\n      code continuation";
  expect(capListNesting(input)).toBe(input);
});

/**
 * 覆盖“capListNesting caps pathologically deep list indentation”这一可观察行为，防止相关边界在重构后回归。

 */

test("capListNesting caps pathologically deep list indentation", () => {
  const deep = "  ".repeat(2000) + "- x";
  const result = capListNesting(deep);
  const indent = /^[ \t]*/.exec(result)![0];
  expect(indent.length).toBe(200);
  expect(result.endsWith("- x")).toBe(true);
});

/**
 * 覆盖“capListNesting leaves fenced code content untouched”这一可观察行为，防止相关边界在重构后回归。

 */

test("capListNesting leaves fenced code content untouched", () => {
  const literal = " ".repeat(400) + "deeply indented ascii art";
  const input = `\`\`\`text\n${literal}\n\`\`\``;
  expect(capListNesting(input).split("\n")[1]).toBe(literal);
});

// 在围栏代码块之外，无论空行上下文如何，都要限制过深缩进：
// 无法区分缩进代码行和深层嵌套列表内容（两者都可能出现在空行之后）；
// 豁免任意一种都会重新引发崩溃，因为由空行分隔的深缩进列表与连续列表一样，
// 都会使 marked 的处理规模失控。
/**
 * 覆盖“capListNesting caps deep indentation even after a blank line”这一可观察行为，防止相关边界在重构后回归。
 */
test("capListNesting caps deep indentation even after a blank line", () => {
  const input = `- a\n\n${" ".repeat(500)}- deep`;
  const lines = capListNesting(input).split("\n");
  expect(/^[ \t]*/.exec(lines[2]!)![0].length).toBe(200);
});

/**
 * 覆盖“capListNesting only rewrites pathological lines”这一可观察行为，防止相关边界在重构后回归。

 */

test("capListNesting only rewrites pathological lines", () => {
  const normal = "    indented paragraph";
  const deep = " ".repeat(500) + "- deep";
  const result = capListNesting(`${normal}\n${deep}\nplain`);
  const lines = result.split("\n");
  expect(lines[0]).toBe(normal);
  expect(/^[ \t]*/.exec(lines[1]!)![0].length).toBe(200);
  expect(lines[2]).toBe("plain");
});

/**
 * 覆盖“capMarkdownNesting caps both blockquote and list nesting”这一可观察行为，防止相关边界在重构后回归。

 */

test("capMarkdownNesting caps both blockquote and list nesting", () => {
  const input = `${"> ".repeat(3000)}quote\n${" ".repeat(500)}- item`;
  const result = capMarkdownNesting(input);
  const lines = result.split("\n");
  expect((lines[0]?.match(/>/g) ?? []).length).toBe(100);
  expect(/^[ \t]*/.exec(lines[1]!)![0].length).toBe(200);
});

/**
 * 覆盖“normalizeStreamdownMathMarkdown converts inline math delimiters”这一可观察行为，防止相关边界在重构后回归。

 */

test("normalizeStreamdownMathMarkdown converts inline math delimiters", () => {
  expect(
    normalizeStreamdownMathMarkdown("Given \\(x\\), compute \\(x^2\\)."),
  ).toBe("Given $x$, compute $x^2$.");
});

/**
 * 覆盖“normalizeStreamdownMathMarkdown converts multiline display math delimiters”这一可观察行为，防止相关边界在重构后回归。

 */

test("normalizeStreamdownMathMarkdown converts multiline display math delimiters", () => {
  const input = [
    "Before",
    "\\[",
    "\\begin{aligned}",
    "x_t &= \\sqrt{\\bar{\\alpha}_t}x_0 + \\sqrt{1-\\bar{\\alpha}_t}\\epsilon, \\\\",
    "\\hat{x}_0 &= x_t",
    "\\end{aligned}",
    "\\]",
    "After",
  ].join("\n");
  const expected = [
    "Before",
    "$$",
    "\\begin{aligned} x_t &= \\sqrt{\\bar{\\alpha}_t}x_0 + \\sqrt{1-\\bar{\\alpha}_t}\\epsilon, \\\\ \\hat{x}_0 &= x_t \\end{aligned}",
    "$$",
    "After",
  ].join("\n");
  expect(normalizeStreamdownMathMarkdown(input)).toBe(expected);
});

/**
 * 覆盖“normalizeStreamdownMathMarkdown leaves fenced and indented code untouched”这一可观察行为，防止相关边界在重构后回归。

 */

test("normalizeStreamdownMathMarkdown leaves fenced and indented code untouched", () => {
  const input = [
    "Text \\(x\\)",
    "```tex",
    "\\[",
    "x^2",
    "\\]",
    "```",
    "    \\(literal\\)",
  ].join("\n");
  const expected = [
    "Text $x$",
    "```tex",
    "\\[",
    "x^2",
    "\\]",
    "```",
    "    \\(literal\\)",
  ].join("\n");
  expect(normalizeStreamdownMathMarkdown(input)).toBe(expected);
});

/**
 * 覆盖“compactDisplayMathBlocks keeps display math as display math”这一可观察行为，防止相关边界在重构后回归。

 */

test("compactDisplayMathBlocks keeps display math as display math", () => {
  const input = ["Before", "$$", "x", "=", "y", "$$", "After"].join("\n");
  const expected = ["Before", "$$", "x = y", "$$", "After"].join("\n");
  expect(compactDisplayMathBlocks(input)).toBe(expected);
});

/**
 * 覆盖“compactDisplayMathBlocks preserves TeX comments in display math”这一可观察行为，防止相关边界在重构后回归。

 */

test("compactDisplayMathBlocks preserves TeX comments in display math", () => {
  const input = ["Before", "$$", "a % step 1", "+ b", "$$", "After"].join("\n");
  expect(compactDisplayMathBlocks(input)).toBe(input);
});

/**
 * 覆盖“compactDisplayMathBlocks compacts escaped percent in display math”这一可观察行为，防止相关边界在重构后回归。

 */

test("compactDisplayMathBlocks compacts escaped percent in display math", () => {
  const input = ["Before", "$$", "a \\% step 1", "+ b", "$$", "After"].join(
    "\n",
  );
  const expected = ["Before", "$$", "a \\% step 1 + b", "$$", "After"].join(
    "\n",
  );
  expect(compactDisplayMathBlocks(input)).toBe(expected);
});

/**
 * 覆盖“compactDisplayMathBlocks leaves fenced code content untouched”这一可观察行为，防止相关边界在重构后回归。

 */

test("compactDisplayMathBlocks leaves fenced code content untouched", () => {
  const input = [
    "```md",
    "$$",
    "x = y",
    "$$",
    "```",
    "$$",
    "a",
    "=",
    "b",
    "$$",
  ].join("\n");
  const expected = [
    "```md",
    "$$",
    "x = y",
    "$$",
    "```",
    "$$",
    "a = b",
    "$$",
  ].join("\n");
  expect(compactDisplayMathBlocks(input)).toBe(expected);
});

/**
 * 覆盖“preprocessStreamdownMarkdown applies only Mermaid fixes (not math)”这一可观察行为，防止相关边界在重构后回归。

 */

test("preprocessStreamdownMarkdown applies only Mermaid fixes (not math)", () => {
  const input = [
    "Before \\(x\\)",
    "```mermaid",
    "graph TD",
    "  A -.-> B",
    "```",
  ].join("\n");
  const expected = [
    "Before \\(x\\)",
    "```mermaid",
    "graph TD",
    "  A -.-> B",
    "```",
  ].join("\n");
  expect(preprocessStreamdownMarkdown(input)).toBe(expected);
});

/**
 * 覆盖“normalizeStreamdownMathMarkdown preserves escaped backslash before parens”这一可观察行为，防止相关边界在重构后回归。

 */

test("normalizeStreamdownMathMarkdown preserves escaped backslash before parens", () => {
  // 当反斜杠本身被转义（\\）时，其后的 ( 不是数学公式起始符。
  const input = "Use \\\\( to start inline math.";
  expect(normalizeStreamdownMathMarkdown(input)).toBe(
    "Use \\\\( to start inline math.",
  );
});

/**
 * 覆盖“normalizeStreamdownMathMarkdown preserves escaped backslash before brackets”这一可观察行为，防止相关边界在重构后回归。

 */

test("normalizeStreamdownMathMarkdown preserves escaped backslash before brackets", () => {
  const input = "Escape: \\\\[ is not math.";
  expect(normalizeStreamdownMathMarkdown(input)).toBe(
    "Escape: \\\\[ is not math.",
  );
});

/**
 * 覆盖“normalizeStreamdownMathMarkdown preserves delimiters inside multi-line code spans”这一可观察行为，防止相关边界在重构后回归。

 */

test("normalizeStreamdownMathMarkdown preserves delimiters inside multi-line code spans", () => {
  // 在第 1 行开始的反引号代码跨度应保护第 2 行内容。
  const input = ["`code span", "with \\(x\\) inside`"].join("\n");
  expect(normalizeStreamdownMathMarkdown(input)).toBe(input);
});

/**
 * 覆盖“normalizeStreamdownMathMarkdown preserves delimiters inside multi-backtick code spans”这一可观察行为，防止相关边界在重构后回归。

 */

test("normalizeStreamdownMathMarkdown preserves delimiters inside multi-backtick code spans", () => {
  const input = "Use ``\\(literal\\)`` here";
  expect(normalizeStreamdownMathMarkdown(input)).toBe(input);
});

/**
 * 覆盖“normalizeStreamdownMathMarkdown requires matching backtick run to close code spans”这一可观察行为，防止相关边界在重构后回归。

 */

test("normalizeStreamdownMathMarkdown requires matching backtick run to close code spans", () => {
  const input = "Use ``\\(literal\\)` and still code`` then \\(x\\)";
  const expected = "Use ``\\(literal\\)` and still code`` then $x$";
  expect(normalizeStreamdownMathMarkdown(input)).toBe(expected);
});
