import { expect, test } from "@playwright/test";

import { handleRunStream, mockLangGraphAPI } from "./utils/mock-api";

/**
 * https://github.com/bytedance/deer-flow/issues/2746 的回归测试。
 *
 * 在全新聊天中，LangGraph SDK 的 useStream 收到线程 ID 后会立即获取
 * `/threads/{id}/history`，前端自身的 `useThreadRuns` 也会基于同一原因发起
 * `GET /threads/{id}/runs`。两端点都假定后端已有该线程；若前端在
 * `POST /runs/stream` 真正创建线程前转发客户端生成的线程 ID，生产环境中两次调用都会 404。
 * 本测试固定请求顺序，防止回归悄然重现。
 */
test.describe("Chat: thread API request ordering on first send", () => {
  /**
   * 覆盖“does not call /history or GET /runs before /runs/stream is initiated”这一可观察行为，防止相关边界在重构后回归。
   */
  test("does not call /history or GET /runs before /runs/stream is initiated", async ({
    page,
  }) => {
    type EventLog = {
      phase: "sent" | "done";
      url: string;
      method: string;
      seq: number;
    };
    const events: EventLog[] = [];
    // 单调递增序号：Date.now() 只有毫秒精度，两个请求可能共享时间戳，从而破坏下方的
    // 严格顺序断言。
    let nextSeq = 0;

    page.on("request", (req) => {
      events.push({
        phase: "sent",
        url: req.url(),
        method: req.method(),
        seq: nextSeq++,
      });
    });
    page.on("requestfinished", (req) => {
      events.push({
        phase: "done",
        url: req.url(),
        method: req.method(),
        seq: nextSeq++,
      });
    });

    mockLangGraphAPI(page);

    // 放慢 /runs/stream，使任何创建前的 /history 或 /runs 请求都会在流返回元数据前很早
    // 到达，从而扩大该缺陷曾利用的竞态窗口。
    await page.route(
      "**/api/langgraph/threads/*/runs/stream",
      async (route) => {
        await new Promise((r) => setTimeout(r, 250));
        return handleRunStream(route);
      },
    );
    await page.route("**/api/langgraph/runs/stream", async (route) => {
      await new Promise((r) => setTimeout(r, 250));
      return handleRunStream(route);
    });

    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });
    await textarea.fill("Hello");
    await textarea.press("Enter");

    // 等待流式响应，确保所有初始化请求都有机会发出。
    await expect(page.getByText("Hello from DeerFlow!")).toBeVisible({
      timeout: 15_000,
    });

    /**
     * 封装局部测试或脚本流程中的具名操作，避免调用处重复实现 isHistory 约定的逻辑。

     */

    const isHistory = (url: string) =>
      /\/api\/langgraph\/threads\/[^/]+\/history/.test(url);
    /**
     * 封装局部测试或脚本流程中的具名操作，避免调用处重复实现 isRunsList 约定的逻辑。
     */
    const isRunsList = (url: string, method: string) =>
      method === "GET" &&
      /\/api\/langgraph\/threads\/[^/]+\/runs(\?|$)/.test(url);
    /**
     * 封装局部测试或脚本流程中的具名操作，避免调用处重复实现 isRunsStream 约定的逻辑。
     */
    const isRunsStream = (url: string, method: string) =>
      method === "POST" && /\/runs\/stream(\?|$)/.test(url);

    const runsStreamSent = events.find(
      (e) => e.phase === "sent" && isRunsStream(e.url, e.method),
    );
    expect(
      runsStreamSent,
      "Expected POST /runs/stream to be issued during send",
    ).toBeDefined();

    const earlyHistory = events.filter(
      (e) =>
        e.phase === "sent" && isHistory(e.url) && e.seq < runsStreamSent!.seq,
    );
    const earlyRunsList = events.filter(
      (e) =>
        e.phase === "sent" &&
        isRunsList(e.url, e.method) &&
        e.seq < runsStreamSent!.seq,
    );

    expect(
      earlyHistory.map((e) => e.url),
      "GET /history must not be issued before POST /runs/stream — see issue #2746",
    ).toEqual([]);
    expect(
      earlyRunsList.map((e) => e.url),
      "GET /runs must not be issued before POST /runs/stream — see issue #2746",
    ).toEqual([]);
  });
});
