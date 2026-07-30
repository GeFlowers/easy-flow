import { buildLoginUrl } from "@/core/auth/types";

/** Gateway 的 CSRFMiddleware 需要校验的 HTTP 方法。 */
export type StateChangingMethod = "POST" | "PUT" | "DELETE" | "PATCH";

/** 用于判定是否需要注入 CSRF 请求头的状态变更方法集合。 */
export const STATE_CHANGING_METHODS: ReadonlySet<StateChangingMethod> = new Set(
  ["POST", "PUT", "DELETE", "PATCH"],
);

/** 与 Gateway ``should_check_csrf`` 判定保持一致的方法检查。 */
export function isStateChangingMethod(method: string): boolean {
  return (STATE_CHANGING_METHODS as ReadonlySet<string>).has(
    method.toUpperCase(),
  );
}

const CSRF_COOKIE_PREFIX = "csrf_token=";

/**
 * 读取 Gateway 在登录时设置的 ``csrf_token`` Cookie。
 *
 * 对 SSR 安全：当 ``document`` 未定义时返回 ``null``，因此服务端组件可无需额外
 * 守卫地导入同一辅助函数。
 *
 * 使用 `String.split` 而非正则表达式，以避开 ESLint 的 `prefer-regexp-exec` 规则，
 * 并利用 Cookie 值可靠的 `; ` 分隔符（由 Gateway 而非浏览器设置，因此格式稳定）。
 */
export function readCsrfCookie(): string | null {
  if (typeof document === "undefined") return null;
  for (const pair of document.cookie.split("; ")) {
    if (pair.startsWith(CSRF_COOKIE_PREFIX)) {
      return decodeURIComponent(pair.slice(CSRF_COOKIE_PREFIX.length));
    }
  }
  return null;
}

/**
 * 发起携带凭据并自动执行 CSRF 保护的请求。
 *
 * 每个 API 调用都需要遵守的两项集中约定：
 *
 * 1. ``credentials: "include"``，确保 HttpOnly ``access_token`` Cookie
 *    会随跨源、经 SSR 路由的请求发送。
 * 2. 对状态变更方法（POST/PUT/DELETE/PATCH）设置从 ``csrf_token`` Cookie
 *    回显的 ``X-CSRF-Token`` 请求头。Gateway 的 CSRFMiddleware 强制执行
 *    双重提交 Cookie 比对；若缺少该请求头会返回 403，使用原始 ``fetch()``
 *    而未使用本包装器的所有调用点都会因此悄然失效。
 *
 * 收到 401 时自动跳转至 ``/login``。保留调用方提供的请求头；仅在 CSRF 请求头尚未
 * 存在时才添加，因此显式覆盖值优先。
 */
export async function fetch(
  input: RequestInfo | string,
  init?: RequestInit,
): Promise<Response> {
  const url = typeof input === "string" ? input : input.url;

  // 仅为状态变更方法注入 CSRF；GET/HEAD/OPTIONS/TRACE 跳过，精确复现 Gateway 的
  // ``should_check_csrf`` 逻辑。
  let headers = init?.headers;
  if (isStateChangingMethod(init?.method ?? "GET")) {
    const token = readCsrfCookie();
    if (token) {
      // 新建 Headers 实例，避免修改调用方提供的对象。
      const merged = new Headers(headers);
      if (!merged.has("X-CSRF-Token")) {
        merged.set("X-CSRF-Token", token);
      }
      headers = merged;
    }
  }

  const res = await globalThis.fetch(url, {
    ...init,
    headers,
    credentials: "include",
  });

  if (res.status === 401) {
    window.location.href = buildLoginUrl(window.location.pathname);
    throw new Error("Unauthorized");
  }

  return res;
}

/**
 * 构造受 CSRF 保护请求所需的请求头。
 *
 * 新代码应**优先使用 :func:`fetchWithAuth`**，它会在状态变更方法中自动注入请求头。
 * 本辅助函数保留给必须手动组合请求头的旧调用点（例如构造自有 ``Headers`` 对象的
 * `next/server` 路由处理程序）。
 *
 * 遵循 RFC-001 的双重提交 Cookie 模式。
 */
export function getCsrfHeaders(): HeadersInit {
  const token = readCsrfCookie();
  return token ? { "X-CSRF-Token": token } : {};
}
