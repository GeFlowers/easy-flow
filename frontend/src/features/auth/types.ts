import { z } from "zod";

// ── 用户 Schema（唯一事实来源）────────────────────────────────────

/** 用户认证数据的运行时校验 Schema。 */
export const userSchema = z.object({
  id: z.string(),
  email: z.string().email(),
  system_role: z.enum(["admin", "user"]),
  needs_setup: z.boolean().optional().default(false),
  oauth_provider: z.string().nullable().optional().default(null),
});

/** 前端使用的已认证用户数据，其中 OAuth 提供方字段可选。 */
export type User = Omit<z.infer<typeof userSchema>, "oauth_provider"> & {
  oauth_provider?: string | null;
};

// ── SSR 认证结果（带标签联合）──────────────────────────────────────

/** 服务端认证守卫的全部可判别结果。 */
export type AuthResult =
  | { tag: "authenticated"; user: User }
  | { tag: "needs_setup"; user: User }
  | { tag: "system_setup_required" }
  | { tag: "unauthenticated" }
  | { tag: "gateway_unavailable" }
  | { tag: "config_error"; message: string };

/** 在穷尽式认证结果处理遗漏分支时抛出错误。 */
export function assertNever(x: never): never {
  throw new Error(`Unexpected auth result: ${JSON.stringify(x)}`);
}

/** 为指定返回路径构造登录地址，并对路径进行 URL 编码。 */
export function buildLoginUrl(returnPath: string): string {
  return `/login?next=${encodeURIComponent(returnPath)}`;
}

// ── 后端错误响应解析 ──────────────────────────────────────────────

const AUTH_ERROR_CODES = [
  "invalid_credentials",
  "token_expired",
  "token_invalid",
  "user_not_found",
  "email_already_exists",
  "provider_not_found",
  "not_authenticated",
  "system_already_initialized",
] as const;

/** 后端认证接口可能返回的规范错误码。 */
export type AuthErrorCode = (typeof AUTH_ERROR_CODES)[number];

/** 解析后的后端认证错误响应。 */
export interface AuthErrorResponse {
  code: AuthErrorCode;
  message: string;
}

const AuthErrorSchema = z.object({
  code: z.enum(AUTH_ERROR_CODES),
  message: z.string(),
});

const ErrorDetailSchema = z.object({
  msg: z.string(),
  type: z.enum(["value_error"]),
  loc: z.array(z.string()),
});

/** 解析多种 FastAPI 错误信封，并归一化为认证错误响应。 */
export function parseAuthError(data: unknown): AuthErrorResponse {
  // 优先尝试顶层 {code, message}。
  const parsed = AuthErrorSchema.safeParse(data);
  if (parsed.success) return parsed.data;

  // 解开 FastAPI 的 {detail: {code, message}} 信封。
  if (typeof data === "object" && data !== null && "detail" in data) {
    const detail = (data as Record<string, unknown>).detail;
    const nested = AuthErrorSchema.safeParse(detail);
    if (nested.success) return nested.data;
    // 兼容旧版字符串 detail 响应。
    if (typeof detail === "string") {
      return { code: "invalid_credentials", message: detail };
    } else if (Array.isArray(detail)) {
      // 处理错误详情列表（例如 Pydantic 校验产生的列表）。
      const firstDetail = detail[0];
      if (typeof firstDetail === "object" && firstDetail !== null) {
        const errorDetail = ErrorDetailSchema.safeParse(firstDetail);
        if (errorDetail.success) {
          return { code: "invalid_credentials", message: errorDetail.data.msg };
        }
      }
    } else if (typeof detail === "object" && detail !== null) {
      const errorDetail = ErrorDetailSchema.safeParse(detail);
      if (errorDetail.success) {
        return { code: "invalid_credentials", message: errorDetail.data.msg };
      }
    }
  }

  return { code: "invalid_credentials", message: "Authentication failed" };
}
