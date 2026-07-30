import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.describe("Sidebar navigation", () => {
  /**
   * 覆盖“sidebar contains Chats and Agents nav links”这一可观察行为，防止相关边界在重构后回归。
   */
  test("sidebar contains Chats and Agents nav links", async ({ page }) => {
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");

    // 侧边栏使用 data-sidebar="menu-button"，并通过 asChild 渲染到 <Link> 上。
    const sidebar = page.locator("[data-sidebar='sidebar']");
    await expect(sidebar.locator("a[href='/workspace/chats']")).toBeVisible({
      timeout: 15_000,
    });
    await expect(sidebar.locator("a[href='/workspace/agents']")).toBeVisible();
  });

  /**
   * 覆盖“Agents link navigates to agents page”这一可观察行为，防止相关边界在重构后回归。

   */

  test("Agents link navigates to agents page", async ({ page }) => {
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");

    const sidebar = page.locator("[data-sidebar='sidebar']");
    const agentsLink = sidebar.locator("a[href='/workspace/agents']");
    await expect(agentsLink).toBeVisible({ timeout: 15_000 });
    await agentsLink.click();

    await page.waitForURL("**/workspace/agents");
    await expect(page).toHaveURL(/\/workspace\/agents/);
  });

  /**
   * 覆盖“Agents button is disabled with a hover tooltip when agents_api is off”这一可观察行为，防止相关边界在重构后回归。

   */

  test("Agents button is disabled with a hover tooltip when agents_api is off", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await page.route("**/api/features", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ agents_api: { enabled: false } }),
      }),
    );

    await page.goto("/workspace/chats/new");

    const sidebar = page.locator("[data-sidebar='sidebar']");
    // Chats 仍是真实链接；Agents 不再是可导航链接。
    await expect(sidebar.locator("a[href='/workspace/chats']")).toBeVisible({
      timeout: 15_000,
    });
    await expect(sidebar.locator("a[href='/workspace/agents']")).toHaveCount(0);

    // 渲染禁用的 Agents 按钮，并声明其禁用状态。
    const agentsButton = sidebar.getByRole("button", { name: "Agents" });
    await expect(agentsButton).toHaveAttribute("aria-disabled", "true");

    // 按钮自身禁用了 pointer-events；强制悬停，以便事件到达显示工具提示的外层 tooltip-trigger span。
    await agentsButton.hover({ force: true });
    await expect(page.getByText("Feature not enabled").first()).toBeVisible({
      timeout: 5_000,
    });

    // 键盘/屏幕阅读器用户同样能获知原因：禁用项仍位于 Tab 顺序中（可聚焦），并关联一个
    // 视觉隐藏的说明，而非仅依赖悬停工具提示。
    const describedById = await agentsButton.getAttribute("aria-describedby");
    expect(describedById).toBeTruthy();
    await expect(page.locator(`#${describedById}`)).toHaveText(
      "Feature not enabled",
    );
    await agentsButton.focus();
    await expect(agentsButton).toBeFocused();
  });

  /**
   * 覆盖“mobile welcome layout stays within viewport and opens sidebar”这一可观察行为，防止相关边界在重构后回归。

   */

  test("mobile welcome layout stays within viewport and opens sidebar", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");

    const viewportWidth = page.viewportSize()?.width ?? 390;
    const expectInsideViewport = async (
      locator: ReturnType<typeof page.locator>,
    ) => {
      await expect(locator).toBeVisible({ timeout: 15_000 });
      const box = await locator.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x).toBeGreaterThanOrEqual(-1);
      expect(box!.x + box!.width).toBeLessThanOrEqual(viewportWidth + 1);
    };

    await expectInsideViewport(page.getByText(/Welcome to|欢迎使用/).first());
    await expectInsideViewport(page.getByRole("textbox").first());
    await expectInsideViewport(page.locator("[data-slot='suggestions-list']"));

    const mobileSidebarTrigger = page
      .locator("[data-sidebar='trigger']:visible")
      .first();
    await expect(mobileSidebarTrigger).toBeVisible();
    await mobileSidebarTrigger.click();

    const mobileSidebar = page.locator(
      "[data-mobile='true'][data-sidebar='sidebar']",
    );
    await expect(mobileSidebar).toBeVisible();
    await expect(
      mobileSidebar.locator("a[href='/workspace/chats']"),
    ).toBeVisible();
    await expect(
      mobileSidebar.locator("a[href='/workspace/agents']"),
    ).toBeVisible();
  });
});
