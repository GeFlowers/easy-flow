import { createEnv } from "@t3-oss/env-nextjs";
import { z } from "zod";

export const env = createEnv({
  /**
   * 服务端环境变量模式在构建前拒绝无效配置。
   */
  server: {
    NODE_ENV: z
      .enum(["development", "test", "production"])
      .default("development"),
  },

  /**
   * 客户端环境变量必须使用 `NEXT_PUBLIC_` 前缀，并在构建期完成模式校验。
   */
  client: {
    NEXT_PUBLIC_BACKEND_BASE_URL: z.string().optional(),
    NEXT_PUBLIC_LANGGRAPH_BASE_URL: z.string().optional(),
  },

  /**
   * Edge Runtime 与浏览器构建不能把 `process.env` 当普通对象展开，因此逐项声明
   * 运行时可访问的变量，确保 Next.js 能静态替换。
   */
  runtimeEnv: {
    NODE_ENV: process.env.NODE_ENV,

    NEXT_PUBLIC_BACKEND_BASE_URL: process.env.NEXT_PUBLIC_BACKEND_BASE_URL,
    NEXT_PUBLIC_LANGGRAPH_BASE_URL: process.env.NEXT_PUBLIC_LANGGRAPH_BASE_URL,
  },
  /**
   * Docker 等分阶段构建可通过 `SKIP_ENV_VALIDATION` 跳过当前阶段无法满足的校验。
   */
  skipValidation: !!process.env.SKIP_ENV_VALIDATION,
  /**
   * 将空字符串视为未定义，避免看似存在但实际不可用的凭据通过字符串校验。
   */
  emptyStringAsUndefined: true,
});
