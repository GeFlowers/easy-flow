import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

// Issue #3482：侧边栏的“Recent chats”和 /workspace/chats 列表页过去停在前 50 个线程，
// 没有加载更多的方式。现在 `useInfiniteThreads()` 加上各列表底部附近的哨兵元素会
// 通过后端继续分页。

const TOTAL_THREADS = 120;
const PAGE_SIZE = 50;

const THREADS = Array.from({ length: TOTAL_THREADS }, (_, i) => {
  // 补齐索引位数，使标题按字符串排序时具有确定性。thread-search mock 按给定顺序返回线程，
  // 因而分页边界在各次运行间稳定。
  const index = String(i + 1).padStart(3, "0");
  return {
    thread_id: `00000000-0000-0000-0000-0000000${index.padStart(5, "0")}`,
    title: `Conversation ${index}`,
    updated_at: `2025-06-${String((i % 28) + 1).padStart(2, "0")}T12:00:00Z`,
  };
});

const FIRST_PAGE_LAST = `Conversation ${String(PAGE_SIZE).padStart(3, "0")}`;
const SECOND_PAGE_FIRST = `Conversation ${String(PAGE_SIZE + 1).padStart(3, "0")}`;

test.describe("Thread list infinite scroll (issue #3482)", () => {
  /**
   * 覆盖“chats list page loads more threads when scrolling to the bottom”这一可观察行为，防止相关边界在重构后回归。
   */
  test("chats list page loads more threads when scrolling to the bottom", async ({
    page,
  }) => {
    mockLangGraphAPI(page, { threads: THREADS });

    await page.goto("/workspace/chats");

    const main = page.locator("main");

    // 首页已渲染。
    await expect(main.getByText(FIRST_PAGE_LAST)).toBeVisible({
      timeout: 15_000,
    });
    // 首页之后的项目尚未获取。
    await expect(main.getByText(SECOND_PAGE_FIRST)).toHaveCount(0);

    // 将哨兵滚入视野会触发下一页。
    const sentinel = page.getByTestId("chats-page-sentinel");
    await sentinel.scrollIntoViewIfNeeded();

    await expect(main.getByText(SECOND_PAGE_FIRST)).toBeVisible({
      timeout: 15_000,
    });
  });

  /**
   * 覆盖“sidebar recent chats loads more threads when scrolling to the bottom”这一可观察行为，防止相关边界在重构后回归。

   */

  test("sidebar recent chats loads more threads when scrolling to the bottom", async ({
    page,
  }) => {
    mockLangGraphAPI(page, { threads: THREADS });

    await page.goto("/workspace/chats/new");

    // 第 50 个线程（首页末尾）显示在侧边栏中。
    await expect(page.getByText(FIRST_PAGE_LAST).first()).toBeVisible({
      timeout: 15_000,
    });
    // 第 51 个线程尚未获取。
    await expect(page.getByText(SECOND_PAGE_FIRST)).toHaveCount(0);

    // 将侧边栏哨兵滚入视野以触发下一页。
    const sentinel = page.getByTestId("recent-chat-list-sentinel");
    await sentinel.scrollIntoViewIfNeeded();

    await expect(page.getByText(SECOND_PAGE_FIRST).first()).toBeVisible({
      timeout: 15_000,
    });
  });

  /**
   * 覆盖“chats list page does NOT auto-paginate while a search filter is active”这一可观察行为，防止相关边界在重构后回归。

   */

  test("chats list page does NOT auto-paginate while a search filter is active", async ({
    page,
  }) => {
    // 通过被动请求观察器统计搜索请求。此处使用 page.route() 会与 mockLangGraphAPI 的
    // fulfill 路由竞争（Playwright 按注册逆序匹配路由），计数器可能漏掉真实请求。
    // page.on('request') 是纯观察器，绝不会干扰路由。
    let searchRequestCount = 0;
    page.on("request", (request) => {
      if (request.url().includes("/api/langgraph/threads/search")) {
        searchRequestCount += 1;
      }
    });

    mockLangGraphAPI(page, { threads: THREADS });

    await page.goto("/workspace/chats");

    // 等待首页渲染，以获得基准计数。
    await expect(page.locator("main").getByText(FIRST_PAGE_LAST)).toBeVisible({
      timeout: 15_000,
    });
    const baselineRequests = searchRequestCount;

    // 输入一个与首页及全部项目都不匹配的查询（标题是确定性的）。
    await page
      .getByPlaceholder("Search chats")
      .fill("zzz-no-such-conversation");

    // 自动哨兵必须消失，由显式按钮接替。
    await expect(page.getByTestId("chats-page-sentinel")).toHaveCount(0);
    await expect(page.getByTestId("chats-page-load-more")).toBeVisible();

    // 若保护逻辑回归，给 IntersectionObserver 几帧时间暴露异常；不应再发起额外的
    // /threads/search 调用。
    await page.waitForTimeout(500);
    expect(searchRequestCount).toBe(baselineRequests);

    // 显式按钮仍可作为兜底入口。
    await page.getByTestId("chats-page-load-more").click();
    await expect
      .poll(() => searchRequestCount, { timeout: 10_000 })
      .toBeGreaterThan(baselineRequests);
  });
});
