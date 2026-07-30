import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

const C_SOURCE = `#include <stdio.h>
#include <signal.h>

static volatile int connected = 0;

static void daemon_handle_signal(int sig) {
    if (sig == SIGTERM) {
        connected = 0;

        printf("daemon stop requested\\n");
        return;
    }

    printf("ignored signal %d\\n", sig);
}`;

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 threadWithMessages 的约定。

 */

function threadWithMessages(
  humanText: string,
  aiText = "ack",
): Parameters<typeof mockLangGraphAPI>[1] {
  return {
    threads: [
      {
        thread_id: MOCK_THREAD_ID,
        title: "Plain text rendering",
        updated_at: "2025-06-01T12:00:00Z",
        messages: [
          {
            type: "human",
            id: "msg-human-plain-text",
            content: [{ type: "text", text: humanText }],
          },
          {
            type: "ai",
            id: "msg-ai-plain-text",
            content: aiText,
          },
        ],
      },
    ],
  };
}

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 collectPageErrors 的约定。

 */

function collectPageErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (error) => {
    errors.push(`${error.name}: ${error.message}`);
  });
  return errors;
}

test.describe("User message plain-text rendering", () => {
  /**
   * 覆盖“pasted source code renders verbatim as one block”这一可观察行为，防止相关边界在重构后回归。
   */
  test("pasted source code renders verbatim as one block", async ({ page }) => {
    mockLangGraphAPI(page, threadWithMessages(C_SOURCE));

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(page.getByText("ack")).toBeVisible({ timeout: 15_000 });

    // 粘贴的文件不得被拆分为 Markdown 代码块组件。
    await expect(
      page.locator('[data-code-block-container="true"]'),
    ).toHaveCount(0);

    // 必须逐字保留缩进和行结构。
    const bubble = page.locator(".is-user");
    const text = await bubble.innerText();
    expect(text).toContain("#include <stdio.h>");
    expect(text).toContain("    if (sig == SIGTERM) {");
    expect(text).toContain('        printf("daemon stop requested\\n");');
  });

  /**
   * 覆盖“dollar signs are not parsed as math”这一可观察行为，防止相关边界在重构后回归。

   */

  test("dollar signs are not parsed as math", async ({ page }) => {
    const message = "this costs $5 and $10 in total";
    mockLangGraphAPI(page, threadWithMessages(message));

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(page.getByText("ack")).toBeVisible({ timeout: 15_000 });

    await expect(page.locator(".is-user")).toContainText(message);
    await expect(page.locator(".is-user .katex")).toHaveCount(0);
  });

  /**
   * 覆盖“deeply nested blockquote markers in a user message do not crash the page”这一可观察行为，防止相关边界在重构后回归。

   */

  test("deeply nested blockquote markers in a user message do not crash the page", async ({
    page,
  }) => {
    const pageErrors = collectPageErrors(page);
    mockLangGraphAPI(page, threadWithMessages("> ".repeat(3000) + "hi"));

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(page.getByText("ack")).toBeVisible({ timeout: 15_000 });

    expect(pageErrors).toEqual([]);
    await expect(page.locator(".is-user")).toContainText("> > >");
  });

  /**
   * 覆盖“deeply nested blockquote markers in an AI message do not crash the page”这一可观察行为，防止相关边界在重构后回归。

   */

  test("deeply nested blockquote markers in an AI message do not crash the page", async ({
    page,
  }) => {
    const pageErrors = collectPageErrors(page);
    mockLangGraphAPI(
      page,
      threadWithMessages("hello", "> ".repeat(3000) + "deep"),
    );

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(page.getByText("hello")).toBeVisible({ timeout: 15_000 });

    expect(pageErrors).toEqual([]);
    // 已限制深度的引用链仍可渲染（100 层缩进可能将最内层元素压缩至零宽度，因此断言其存在，
    // 而非可见性）。
    await expect(page.getByText("deep")).toBeAttached();
  });

  /**
   * 覆盖“list-prefixed deep nesting in an AI message falls back to plain text instead of crashing”这一可观察行为，防止相关边界在重构后回归。

   */

  test("list-prefixed deep nesting in an AI message falls back to plain text instead of crashing", async ({
    page,
  }) => {
    // marked 的列表和引用分词器会相互递归，因此引用链前的列表标记会绕过嵌套上限；渲染错误边界
    // 必须吸收该错误。
    const pageErrors = collectPageErrors(page);
    mockLangGraphAPI(
      page,
      threadWithMessages("hello", "- " + "> ".repeat(3000) + "deep-list"),
    );

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(page.getByText("hello")).toBeVisible({ timeout: 15_000 });

    expect(pageErrors).toEqual([]);
    await expect(page.getByText("deep-list")).toBeAttached();
  });
});
