import { existsSync, readFileSync, writeFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

/**
 * RECORD 驱动器（方案 A）：通过真实模型 Gateway 驱动真实前端完成写入/读取文件场景。Gateway
 * 会将每次模型调用捕获到 DEERFLOW_RECORD_OUT；这里仅需驱动流程并等待捕获停止到达（主轮次和后续建议
 * 均已触发；默认自动标题属于本地状态）。它不对内容作断言：只生成 fixture，不验证 fixture。
 */
const APP = "http://localhost:3000";
const SCENARIO = "write_read_file";
const MODE = "ultra";
const PROMPT =
  "Using your own file tools directly, create the file /mnt/user-data/outputs/note.txt " +
  "with exactly this content: hi from replay. Then read that same file back and reply with its " +
  "exact contents. Do NOT delegate to a subagent and do NOT use the task tool — do it yourself. " +
  "Do not ask any clarifying questions.";

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 countLines 的约定。

 */

function countLines(path: string): number {
  return existsSync(path)
    ? readFileSync(path, "utf-8")
        .split("\n")
        .filter((l) => l.trim()).length
    : 0;
}

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 waitForCaptureStable 的约定。

 */

async function waitForCaptureStable(
  path: string,
  { stableMs = 12_000, maxMs = 160_000 } = {},
): Promise<number> {
  const start = Date.now();
  let last = -1;
  let lastChange = Date.now();
  while (Date.now() - start < maxMs) {
    const n = countLines(path);
    if (n !== last) {
      last = n;
      lastChange = Date.now();
    } else if (n > 0 && Date.now() - lastChange > stableMs) {
      return n;
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  // 超时必须硬失败：在此返回最后一次计数会让截断/不完整录制静默通过（captured > 0）。
  // 录制必须稳定，否则不可信。
  throw new Error(
    `[record] captures never stabilized within ${maxMs}ms (last count=${last}); ` +
      `the recording may be truncated — raise maxMs or check the record gateway.`,
  );
}

test.describe.configure({ timeout: 220_000 });

/**
 * 覆盖“record write/read-file run through the real frontend”这一可观察行为，防止相关边界在重构后回归。

 */

test("record write/read-file run through the real frontend", async ({
  page,
  context,
}) => {
  const out = process.env.DEERFLOW_RECORD_OUT;
  expect(out, "DEERFLOW_RECORD_OUT must be set").toBeTruthy();
  // 前端为 ultra 模式推导的上下文（core/threads/hooks.ts）。后端直连黄金测试（第 1 层）会 POST
  // 此对象，使其 prompt（进而录制输入哈希）与浏览器运行一致。thinking/reasoning 不影响 prompt；
  // is_plan_mode + subagent_enabled 会增加 todo/task 工具。
  const CONTEXT = {
    is_bootstrap: false,
    mode: MODE,
    thinking_enabled: true,
    is_plan_mode: true,
    subagent_enabled: true,
  };
  writeFileSync(
    `${out}.meta.json`,
    JSON.stringify({
      scenario: SCENARIO,
      mode: MODE,
      prompt: PROMPT,
      context: CONTEXT,
    }),
    "utf-8",
  );

  const reg = await context.request.post(`${APP}/api/v1/auth/register`, {
    data: {
      email: `rec-${Date.now()}@example.com`,
      password: "very-strong-password-123",
    },
  });
  expect(reg.status(), await reg.text()).toBe(201);

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

  // 建议仅在运行完成后触发（input-box.tsx POST /suggestions）。等待该响应，确保其模型调用在检查
  // 稳定性前进入捕获；否则稳定窗口可能先返回，录制 fixture 会缺少建议轮次。
  await page
    .waitForResponse((r) => r.url().includes("/suggestions"), {
      timeout: 90_000,
    })
    .catch(() => undefined);

  const captured = await waitForCaptureStable(out!);
  console.log(
    `[record] captures stabilized at ${captured} model call(s) -> ${out}`,
  );
  expect(
    captured,
    "expected at least the agent turns to be captured",
  ).toBeGreaterThan(0);
});
