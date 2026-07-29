import { defineConfig, devices } from "@playwright/test";

const frontendPort = process.env.E2E_FRONTEND_PORT ?? "3000";
const gatewayPort = process.env.E2E_GATEWAY_PORT ?? "8011";
const frontendUrl = `http://localhost:${frontendPort}`;
const gatewayUrl = `http://localhost:${gatewayPort}`;
const gatewayInternalUrl = `http://127.0.0.1:${gatewayPort}`;

/**
 * 录制/回放端到端测试的第二层：真实 Next.js 前端连接真实 Gateway，但 LLM 使用
 * 无需 API Key 的确定性 `ReplayChatModel`。它与模拟后端的常规配置隔离，避免改变
 * 原有测试语义。
 *
 * 配置同时启动回放 Gateway 与指向它的前端。两端默认关闭认证以覆盖无 Cookie
 * 契约，需要会话 Cookie 的用例会在运行时注册一次性测试账号。
 */
export default defineConfig({
  testDir: "./tests/e2e-real-backend",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? "github" : "html",
  timeout: 90_000,

  use: {
    baseURL: frontendUrl,
    trace: "on-first-retry",
  },

  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  webServer: [
    {
      command: `uv run python scripts/run_replay_gateway.py --port ${gatewayPort} --cors ${frontendUrl}`,
      cwd: "../backend",
      url: `${gatewayUrl}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      stdout: "pipe",
      stderr: "pipe",
      // 只在回放 Gateway 挂载多运行顺序用例需要的数据播种端点，生产应用不会暴露。
      env: {
        DEERFLOW_ENABLE_TEST_SEED: "1",
        DEER_FLOW_AUTH_DISABLED: "1",
      },
    },
    {
      command: "pnpm build && pnpm start",
      url: frontendUrl,
      reuseExistingServer: !process.env.CI,
      timeout: 240_000,
      env: {
        PORT: frontendPort,
        SKIP_ENV_VALIDATION: "1",
        DEER_FLOW_AUTH_DISABLED: "1",
        BETTER_AUTH_SECRET: "local-dev-secret",
        // 保持 NEXT_PUBLIC_* 未设置，让前端通过同源代理访问回放 Gateway；跨源请求
        // 会丢失认证 Cookie，不能复现生产访问边界。
        DEER_FLOW_INTERNAL_GATEWAY_BASE_URL: gatewayInternalUrl,
      },
    },
  ],
});
