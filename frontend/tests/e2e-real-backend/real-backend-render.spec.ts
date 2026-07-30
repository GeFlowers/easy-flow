import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

const here = dirname(fileURLToPath(import.meta.url));

/**
 * 第 2 层：使用真实 Gateway 驱动真实前端（回放模型，无需 API key），并断言浏览器正确渲染
 * 后端数据。
 *
 * 提示词从 Gateway 回放的同一夹具中读取，因此输入哈希匹配且已录制的模型轮次可确定性复现。默认
 * 自动标题是本地回退状态，而非回放的模型轮次。
 */
// 通过前端来源（同源代理）注册，使鉴权 cookie 为浏览器来源存储并发送——Gateway 经由 next.config
// rewrite 访问，浏览器绝不跨源请求。
const APP =
  process.env.E2E_APP_URL ??
  `http://localhost:${process.env.E2E_FRONTEND_PORT ?? "3000"}`;
const fixture = JSON.parse(
  readFileSync(
    join(
      here,
      "../../../backend/tests/fixtures/replay/write_read_file.ultra.json",
    ),
    "utf-8",
  ),
) as {
  prompt: string;
  turns: Array<{ output: { data: { content?: unknown } } }>;
};

const PROMPT = fixture.prompt;
const FALLBACK_TITLE_MAX_CHARS = 50;

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 fallbackTitle 的约定。

 */

function fallbackTitle(userMsg: string): string {
  if (!userMsg) return "New Conversation";
  if (userMsg.length <= FALLBACK_TITLE_MAX_CHARS) return userMsg;
  return `${userMsg.slice(0, FALLBACK_TITLE_MAX_CHARS).trimEnd()}...`;
}

// 建议仍来自已录制的模型夹具；默认标题不再如此：title.model_name 未设置时，TitleMiddleware
// 使用本地回退值，因此从提示词推导预期标题。
const textTurns = fixture.turns
  .map((t) => t.output?.data?.content)
  .filter((c): c is string => typeof c === "string" && c.trim().length > 0);
const suggestionsRaw = textTurns.find((c) => c.trim().startsWith("["));
// 受保护的解析：以方括号开头、却不是有效 JSON 字符串数组的轮次会回退为 ""，使下方的
// `not.toBe("")` 断言以明确消息失败，而非抛出普通的 JSON.parse 异常。
const EXPECTED_SUGGESTION = ((): string => {
  if (!suggestionsRaw) return "";
  try {
    const arr: unknown = JSON.parse(suggestionsRaw);
    return Array.isArray(arr) && typeof arr[0] === "string" ? arr[0] : "";
  } catch {
    return "";
  }
})();
const EXPECTED_TITLE = fallbackTitle(PROMPT);

test.describe("real backend render (replay, no API key)", () => {
  test.beforeEach(async ({ context }) => {
    // 一次性测试账户：注册会在浏览器上下文中设置 access_token + csrf_token cookie（作用域为
    // localhost 主机并跨端口共享），从而让前端 SDK（credentials:include + X-CSRF-Token）完成鉴权。
    const email = `e2e-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
    const resp = await context.request.post(`${APP}/api/v1/auth/register`, {
      data: { email, password: "very-strong-password-123" },
    });
    expect(resp.status(), await resp.text()).toBe(201);
  });

  /**
   * 覆盖“renders the local auto-title + replayed suggestions from a real backend”这一可观察行为，防止相关边界在重构后回归。

   */

  test("renders the local auto-title + replayed suggestions from a real backend", async ({
    page,
  }) => {
    // 使用 ultra 模式，使前端发送的上下文（is_plan_mode + subagent_enabled）与已录制夹具
    // 匹配；否则回放输入哈希将无法命中。
    await page.addInitScript(() => {
      window.localStorage.setItem(
        "deerflow.local-settings",
        JSON.stringify({ context: { mode: "ultra" } }),
      );
    });

    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 30_000 });
    await textarea.fill(PROMPT);
    await textarea.press("Enter");

    // 标题是默认本地回退值，而建议是提示词中不存在的回放模型输出。二者共同证明后端状态更新和
    // 回答后的回放模型调用都经由真实前端完成渲染。
    expect(
      EXPECTED_TITLE,
      "default local fallback title should be derived from the prompt",
    ).not.toBe("");
    expect(
      EXPECTED_SUGGESTION,
      "fixture should contain a suggestions turn (re-record; the record spec waits for /suggestions)",
    ).not.toBe("");
    const chat = page.locator("#chat");
    await expect(chat.getByText(EXPECTED_TITLE)).toBeVisible({
      timeout: 60_000,
    });
    await expect(chat.getByText(EXPECTED_SUGGESTION)).toBeVisible({
      timeout: 30_000,
    });

    // 视觉回归依赖操作系统（macOS 基线无法匹配 CI 的 Linux 渲染），因此它仅是本地开发门禁；
    // 在 CI 中将渲染结果捕获为供人工审阅的产物，而不强制断言跨操作系统基线。以上 DOM 断言才是
    // CI 门禁。
    if (process.env.CI) {
      await page.screenshot({
        path: "test-results/real-backend-render.png",
        fullPage: true,
      });
    } else {
      await expect(page).toHaveScreenshot("real-backend-render.png", {
        maxDiffPixelRatio: 0.02,
        fullPage: true,
      });
    }
  });
});
