import { defineConfig, devices } from "@playwright/test";

/**
 * 浏览器录制配置：让真实前端连接真实模型 Gateway，并捕获每次模型调用，保证生成的
 * fixture 输入与前端实际请求完全一致。该流程只供人工执行，依赖
 * `OPENAI_API_KEY`、`OPENAI_API_BASE` 和 `DEERFLOW_RECORD_OUT`，不得在 CI 中运行。
 *
 * `tests/e2e-record/` 保存驱动用例，本配置本身不属于常规测试套件。
 */
export default defineConfig({
  testDir: "./tests/e2e-record",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  timeout: 200_000,
  use: { baseURL: "http://localhost:3000", trace: "off" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "uv run python scripts/record_gateway.py",
      cwd: "../backend",
      url: "http://localhost:8012/health",
      reuseExistingServer: false,
      timeout: 180_000,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        RECORD_PORT: "8012",
        RECORD_MODEL: process.env.RECORD_MODEL ?? "gpt-5.5",
        // 仅转发调用 shell 中真实存在的值，避免空字符串让 record_gateway.py
        // 误写 Path("")，并保留其明确的“缺少环境变量”错误。
        ...(process.env.DEERFLOW_RECORD_OUT
          ? { DEERFLOW_RECORD_OUT: process.env.DEERFLOW_RECORD_OUT }
          : {}),
        ...(process.env.OPENAI_API_KEY
          ? { OPENAI_API_KEY: process.env.OPENAI_API_KEY }
          : {}),
        ...(process.env.OPENAI_API_BASE
          ? { OPENAI_API_BASE: process.env.OPENAI_API_BASE }
          : {}),
      },
    },
    {
      command: "pnpm build && pnpm start",
      url: "http://localhost:3000",
      reuseExistingServer: false,
      timeout: 240_000,
      env: {
        SKIP_ENV_VALIDATION: "1",
        DEER_FLOW_AUTH_DISABLED: "1",
        BETTER_AUTH_SECRET: "local-dev-secret",
        DEER_FLOW_INTERNAL_GATEWAY_BASE_URL: "http://127.0.0.1:8012",
      },
    },
  ],
});
