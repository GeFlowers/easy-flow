import { expect, test } from "@rstest/core";

import { normalizeMermaidMarkdown } from "@/core/streamdown/mermaid";
import { preprocessStreamdownMarkdown } from "@/core/streamdown/preprocess";

/**
 * 覆盖“normalizes labelled dotted arrows inside mermaid fences”这一可观察行为，防止相关边界在重构后回归。

 */

test("normalizes labelled dotted arrows inside mermaid fences", () => {
  const markdown = [
    "```mermaid",
    "flowchart TD",
    '    A -- "sealed memory" -.-> F',
    '    B -- "resonance" -.-> A',
    "```",
  ].join("\n");

  expect(normalizeMermaidMarkdown(markdown)).toBe(
    [
      "```mermaid",
      "flowchart TD",
      '    A -. "sealed memory" .-> F',
      '    B -. "resonance" .-> A',
      "```",
    ].join("\n"),
  );
});

/**
 * 覆盖“does not rewrite non-mermaid code fences”这一可观察行为，防止相关边界在重构后回归。

 */

test("does not rewrite non-mermaid code fences", () => {
  const markdown = ["```text", 'A -- "sealed memory" -.-> F', "```"].join("\n");

  expect(normalizeMermaidMarkdown(markdown)).toBe(markdown);
});

/**
 * 覆盖“preserves mermaid fence metadata”这一可观察行为，防止相关边界在重构后回归。

 */

test("preserves mermaid fence metadata", () => {
  const markdown = [
    '```mermaid title="relationships"',
    'A -- "sealed memory" -.-> F',
    "```",
  ].join("\n");

  expect(normalizeMermaidMarkdown(markdown)).toBe(
    [
      '```mermaid title="relationships"',
      'A -. "sealed memory" .-> F',
      "```",
    ].join("\n"),
  );
});

/**
 * 覆盖“normalizes labelled dotted arrows with inconsistent spacing”这一可观察行为，防止相关边界在重构后回归。

 */

test("normalizes labelled dotted arrows with inconsistent spacing", () => {
  const markdown = [
    "```mermaid",
    'A--"sealed memory"-.->F',
    'B --"resonance"-.-> A',
    'C-- "handoff" -.->D',
    "```",
  ].join("\n");

  expect(normalizeMermaidMarkdown(markdown)).toBe(
    [
      "```mermaid",
      'A -. "sealed memory" .-> F',
      'B -. "resonance" .-> A',
      'C -. "handoff" .-> D',
      "```",
    ].join("\n"),
  );
});

/**
 * 覆盖“normalizes mermaid fences with CRLF line endings”这一可观察行为，防止相关边界在重构后回归。

 */

test("normalizes mermaid fences with CRLF line endings", () => {
  const markdown = ["```mermaid", 'A--"sealed memory"-.->F', "```"].join(
    "\r\n",
  );

  expect(normalizeMermaidMarkdown(markdown)).toBe(
    ["```mermaid", 'A -. "sealed memory" .-> F', "```"].join("\n"),
  );
});

/**
 * 覆盖“preserves empty mermaid fences”这一可观察行为，防止相关边界在重构后回归。

 */

test("preserves empty mermaid fences", () => {
  const markdown = ["```mermaid", "```"].join("\n");

  expect(normalizeMermaidMarkdown(markdown)).toBe(markdown);
});

/**
 * 覆盖“normalizes labelled dotted arrows inside tilde mermaid fences”这一可观察行为，防止相关边界在重构后回归。

 */

test("normalizes labelled dotted arrows inside tilde mermaid fences", () => {
  const markdown = ["~~~mermaid", 'A -- "sealed memory" -.-> F', "~~~"].join(
    "\n",
  );

  expect(normalizeMermaidMarkdown(markdown)).toBe(
    ["~~~mermaid", 'A -. "sealed memory" .-> F', "~~~"].join("\n"),
  );
});

/**
 * 覆盖“normalizes mermaid fences with longer backtick closing fences”这一可观察行为，防止相关边界在重构后回归。

 */

test("normalizes mermaid fences with longer backtick closing fences", () => {
  const markdown = ["```mermaid", 'A -- "sealed memory" -.-> F', "````"].join(
    "\n",
  );

  expect(normalizeMermaidMarkdown(markdown)).toBe(
    ["```mermaid", 'A -. "sealed memory" .-> F', "````"].join("\n"),
  );
});

/**
 * 覆盖“normalizes mermaid fences with longer tilde closing fences”这一可观察行为，防止相关边界在重构后回归。

 */

test("normalizes mermaid fences with longer tilde closing fences", () => {
  const markdown = ["~~~mermaid", 'A -- "sealed memory" -.-> F', "~~~~"].join(
    "\n",
  );

  expect(normalizeMermaidMarkdown(markdown)).toBe(
    ["~~~mermaid", 'A -. "sealed memory" .-> F', "~~~~"].join("\n"),
  );
});

/**
 * 覆盖“preprocesses markdown only when mermaid normalization can apply”这一可观察行为，防止相关边界在重构后回归。

 */

test("preprocesses markdown only when mermaid normalization can apply", () => {
  const textOnlyMarkdown = 'A -- "sealed memory" -.-> F';
  const plainMermaidMarkdown = ["```mermaid", "A --> F", "```"].join("\n");
  const labelledMermaidMarkdown = [
    "```mermaid",
    'A -- "sealed memory" -.-> F',
    "```",
  ].join("\n");

  expect(preprocessStreamdownMarkdown(textOnlyMarkdown)).toBe(textOnlyMarkdown);
  expect(preprocessStreamdownMarkdown(plainMermaidMarkdown)).toBe(
    plainMermaidMarkdown,
  );
  expect(preprocessStreamdownMarkdown(labelledMermaidMarkdown)).toBe(
    ["```mermaid", 'A -. "sealed memory" .-> F', "```"].join("\n"),
  );
});
