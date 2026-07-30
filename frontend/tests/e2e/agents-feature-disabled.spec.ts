import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.describe("Agents feature disabled", () => {
  /**
   * 覆盖“shows disabled message and issues no /api/agents requests when feature is off”这一可观察行为，防止相关边界在重构后回归。
   */
  test("shows disabled message and issues no /api/agents requests when feature is off", async ({
    page,
  }) => {
    // 跟踪所有对 agents API 的请求——不应存在任何请求。使用锚定匹配，确保仅捕获真实的
    // agents 路由（/api/agents、/api/agents/check、/api/agents/{name}），绝不匹配未来仅
    // 包含该子字符串的无关路径。
    const AGENTS_API = /\/api\/agents(\/|$)/;
    const agentRequests: string[] = [];
    page.on("request", (req) => {
      if (AGENTS_API.test(new URL(req.url()).pathname)) {
        agentRequests.push(req.url());
      }
    });

    // Shell/鉴权端点及 agents API mock（后者不应被命中）。
    mockLangGraphAPI(page, { agents: [] });

    // 功能开关表明 agents API 已禁用。
    await page.route("**/api/features", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ agents_api: { enabled: false } }),
      }),
    );

    await page.goto("/workspace/agents");

    // 渲染禁用提示并引导用户联系管理员（en-US 或 zh-CN 文案），且不泄露后端配置细节。
    await expect(
      page.getByText(/contact your administrator|联系管理员/i),
    ).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/config\.yaml|agents_api/i)).toHaveCount(0);

    // 防护逻辑阻止了所有 agents API 调用，包括直接导航。
    expect(agentRequests).toEqual([]);
  });

  /**
   * 覆盖“stays disabled (no 403 storm) when /api/features goes down after a known-disabled result”这一可观察行为，防止相关边界在重构后回归。

   */

  test("stays disabled (no 403 storm) when /api/features goes down after a known-disabled result", async ({
    page,
  }) => {
    const AGENTS_API = /\/api\/agents(\/|$)/;
    const agentRequests: string[] = [];
    page.on("request", (req) => {
      if (AGENTS_API.test(new URL(req.url()).pathname)) {
        agentRequests.push(req.url());
      }
    });

    mockLangGraphAPI(page, { agents: [] });

    // /api/features 先报告禁用，随后开始失败——模拟已知该开关状态后的 features 端点故障。
    let featuresUp = true;
    await page.route("**/api/features", (route) =>
      featuresUp
        ? route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ agents_api: { enabled: false } }),
          })
        : route.fulfill({
            status: 500,
            contentType: "application/json",
            body: "{}",
          }),
    );

    // 首次访问观察到明确的“disabled”状态并将其持久化。
    await page.goto("/workspace/agents");
    await expect(
      page.getByText(/contact your administrator|联系管理员/i),
    ).toBeVisible({ timeout: 15_000 });

    // features 端点现在失败。重新加载绝不能开放失败并重新挂载 agents 页面（否则会再次触发
    // #3757 中的 403 风暴）；最后已知的“disabled”值必须保持不变。
    featuresUp = false;
    agentRequests.length = 0;
    await page.goto("/workspace/agents");
    await expect(
      page.getByText(/contact your administrator|联系管理员/i),
    ).toBeVisible({ timeout: 15_000 });
    expect(agentRequests).toEqual([]);
  });
});
