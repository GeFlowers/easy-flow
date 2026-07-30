import { expect, test } from "@playwright/test";

/**
 * 第 2 层（跨栈契约）：复现上游问题 #3352——检查点不再保存较旧消息（上下文压缩后）时，
 * 前端会从按运行划分的端点重建线程历史，且重建顺序必须保持时间先后。
 *
 * 本测试防护的危险类别是：后端对运行排序的变更会悄然破坏前端假设。后端 `list_by_thread`
 * 按最新优先返回运行（PR #2932）；#3354 之前的前端从末尾遍历运行，并将每个已加载页面
 * 前置（`core/threads/hooks.ts`），从而反转顺序。在 #3352 存在期间，仅后端的排序测试始终
 * 通过，而前端回归单元测试在 mock 中硬编码“backend returns newest-first”——因此只有真实
 * 前端连接真实后端才能发现这种不同步。
 *
 * 本测试使用两个预置运行和无检查点的真实 Gateway 驱动真实前端（预置器强制按运行重载路径成为
 * 唯一事实来源），随后断言第一个运行的消息渲染在第二个运行消息的上方。无需模型、录制或 API
 * key——通过仅挂载在回放 Gateway 上的测试专用端点预置运行。
 */
const APP =
  process.env.E2E_APP_URL ??
  `http://localhost:${process.env.E2E_FRONTEND_PORT ?? "3000"}`;

// 使用明显不同的标记，避免 getByText 与 UI 框架元素发生冲突。
const ALPHA = "ALPHA-FIRST-QUESTION-7f3a2c";
const OMEGA = "OMEGA-SECOND-QUESTION-9b21d4";

test.describe("multi-run thread renders chronologically (replay, no API key)", () => {
  /**
   * 覆盖“first run renders above second run after history rebuild (#3352)”这一可观察行为，防止相关边界在重构后回归。
   */
  test("first run renders above second run after history rebuild (#3352)", async ({
    page,
    context,
  }) => {
    const uniq = `${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
    const threadId = `e2e-multi-run-${uniq}`;
    const email = `e2e-${uniq}@example.com`;

    // 通过前端来源（同源代理）注册，使鉴权 cookie 存储于 localhost，并通过 next.config rewrite
    // 转发至 Gateway——浏览器绝不跨源请求。
    const reg = await context.request.post(`${APP}/api/v1/auth/register`, {
      data: { email, password: "very-strong-password-123" },
    });
    expect(reg.status(), await reg.text()).toBe(201);

    const cookies = await context.cookies();
    const csrf = cookies.find((c) => c.name === "csrf_token")?.value;
    expect(csrf, "register must set csrf_token cookie").toBeTruthy();

    // 在同一线程中预置两个运行：run-1（ALPHA）较旧，run-2（OMEGA）较新，因此真实后端的
    // list_by_thread 按最新优先返回它们。未预置检查点——这是 #3352 的前置条件。
    const seed = await context.request.post(`${APP}/api/test-only/seed-runs`, {
      headers: { "X-CSRF-Token": csrf! },
      data: {
        thread_id: threadId,
        runs: [
          {
            run_id: `${threadId}-r1`,
            created_at: "2026-01-01T00:00:00+00:00",
            messages: [
              { role: "human", content: ALPHA, id: `${threadId}-a-h` },
              { role: "ai", content: "ALPHA reply", id: `${threadId}-a-a` },
            ],
          },
          {
            run_id: `${threadId}-r2`,
            created_at: "2026-01-01T00:01:00+00:00",
            messages: [
              { role: "human", content: OMEGA, id: `${threadId}-o-h` },
              { role: "ai", content: "OMEGA reply", id: `${threadId}-o-a` },
            ],
          },
        ],
      },
    });
    expect(seed.status(), await seed.text()).toBe(200);

    // 全新加载线程——触发 useThreadHistory 的按运行重载路径。
    await page.goto(`/workspace/chats/${threadId}`);

    const alpha = page.getByText(ALPHA, { exact: false });
    const omega = page.getByText(OMEGA, { exact: false });
    await expect(alpha).toBeVisible({ timeout: 60_000 });
    await expect(omega).toBeVisible({ timeout: 30_000 });
    // 每个标记恰好渲染一次（防止意外的重复匹配）。
    expect(await alpha.count(), "ALPHA should render exactly once").toBe(1);
    expect(await omega.count(), "OMEGA should render exactly once").toBe(1);

    // 契约：ALPHA（第一个运行）必须渲染在 OMEGA（第二个运行）上方。存在 #3352 bug 时，
    // 按运行重建会反转此顺序，使 OMEGA 先渲染。
    const alphaBox = await alpha.first().boundingBox();
    const omegaBox = await omega.first().boundingBox();
    expect(alphaBox, "ALPHA must have a layout box").toBeTruthy();
    expect(omegaBox, "OMEGA must have a layout box").toBeTruthy();
    expect(
      alphaBox!.y,
      `chronological order broken: ALPHA(first run) rendered at y=${alphaBox!.y}, OMEGA(second run) at y=${omegaBox!.y} — backend list_by_thread ordering and frontend history rebuild are out of sync (#3352)`,
    ).toBeLessThan(omegaBox!.y);
  });
});
