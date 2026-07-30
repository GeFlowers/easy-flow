/**
 * 用于管理语言区域的 Cookie 工具，兼容客户端与服务端。
 */

const LOCALE_COOKIE_NAME = "locale";

/**
 * 从客户端 Cookie 读取语言区域。
 */
export function getLocaleFromCookie(): string | null {
  if (typeof document === "undefined") {
    return null;
  }

  const cookies = document.cookie.split(";");
  for (const cookie of cookies) {
    const [name, value] = cookie.trim().split("=");
    if (name === LOCALE_COOKIE_NAME) {
      return decodeURIComponent(value ?? "");
    }
  }
  return null;
}

/**
 * 将语言区域写入客户端 Cookie。
 */
export function setLocaleInCookie(locale: string): void {
  if (typeof document === "undefined") {
    return;
  }

  // Cookie 有效期为一年。
  const maxAge = 365 * 24 * 60 * 60; // 一年对应的秒数。
  document.cookie = `${LOCALE_COOKIE_NAME}=${encodeURIComponent(locale)}; max-age=${maxAge}; path=/; SameSite=Lax`;
}

/**
 * 从服务端 Cookie 读取语言区域，供服务端组件或 API 路由使用。
 */
export async function getLocaleFromCookieServer(): Promise<string | null> {
  try {
    const { cookies } = await import("next/headers");
    const cookieStore = await cookies();
    return cookieStore.get(LOCALE_COOKIE_NAME)?.value ?? null;
  } catch {
    // cookies() 不可用时（例如中间件中）返回回退值。
    return null;
  }
}
