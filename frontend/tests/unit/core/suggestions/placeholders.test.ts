import { describe, expect, test } from "@rstest/core";

import { findSuggestionTemplatePlaceholder } from "@/core/suggestions/placeholders";

describe("findSuggestionTemplatePlaceholder", () => {
  /**
   * 覆盖“finds Chinese [主题] and returns correct range”这一可观察行为，防止相关边界在重构后回归。
   */
  test("finds Chinese [主题] and returns correct range", () => {
    const result = findSuggestionTemplatePlaceholder(
      "深入浅出的研究一下[主题]，并总结发现。",
    );
    expect(result).toEqual({ start: 9, end: 13 });
  });

  /**
   * 覆盖“finds English [topic] and returns correct range”这一可观察行为，防止相关边界在重构后回归。

   */

  test("finds English [topic] and returns correct range", () => {
    const result = findSuggestionTemplatePlaceholder(
      "Write a blog post about the latest trends on [topic]",
    );
    expect(result).toEqual({ start: 45, end: 52 });
  });

  /**
   * 覆盖“finds Chinese [来源] placeholder”这一可观察行为，防止相关边界在重构后回归。

   */

  test("finds Chinese [来源] placeholder", () => {
    const result =
      findSuggestionTemplatePlaceholder("从[来源]收集数据并创建报告。");
    expect(result).not.toBeNull();
  });

  /**
   * 覆盖“finds English [source] placeholder”这一可观察行为，防止相关边界在重构后回归。

   */

  test("finds English [source] placeholder", () => {
    const result = findSuggestionTemplatePlaceholder(
      "Collect data from [source] and create a report.",
    );
    expect(result).not.toBeNull();
  });

  /**
   * 覆盖“returns null for normal text without brackets”这一可观察行为，防止相关边界在重构后回归。

   */

  test("returns null for normal text without brackets", () => {
    expect(
      findSuggestionTemplatePlaceholder("研究一下2025年最流行的Python框架"),
    ).toBeNull();
  });

  /**
   * 覆盖“returns null for text with unrelated brackets”这一可观察行为，防止相关边界在重构后回归。

   */

  test("returns null for text with unrelated brackets", () => {
    expect(
      findSuggestionTemplatePlaceholder("check [this link] for details"),
    ).toBeNull();
  });

  /**
   * 覆盖“returns null for empty text”这一可观察行为，防止相关边界在重构后回归。

   */

  test("returns null for empty text", () => {
    expect(findSuggestionTemplatePlaceholder("")).toBeNull();
  });

  /**
   * 覆盖“detects placeholder case-insensitively for English”这一可观察行为，防止相关边界在重构后回归。

   */

  test("detects placeholder case-insensitively for English", () => {
    expect(
      findSuggestionTemplatePlaceholder("Research [Topic] deeply"),
    ).not.toBeNull();
    expect(
      findSuggestionTemplatePlaceholder("Research [TOPIC] deeply"),
    ).not.toBeNull();
  });
});
