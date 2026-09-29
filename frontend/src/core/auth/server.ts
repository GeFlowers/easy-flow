import { cookies } from "next/headers";

import { AUTH_DISABLED_USER, isAuthDisabledMode } from "./auth-disabled-user";
import { getGatewayConfig } from "./gateway-config";
import { type AuthResult, userSchema } from "./types";

const SSR_AUTH_TIMEOUT_MS = 5_000;

/**
 * 使用当前请求的 Cookie 从 Gateway 获取已认证用户。
 * 返回带标签的 AuthResult；调用方应使用穷尽式 switch，无需 try/catch。
 */
export async function getServerSideUser(): Promise<AuthResult> {
  if (isAuthDisabledMode()) {
    return {
      tag: "authenticated",
      user: AUTH_DISABLED_USER,
    };
  }

  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get("access_token");

  let internalGatewayUrl: string;
  try {
    internalGatewayUrl = getGatewayConfig().internalGatewayUrl;
  } catch (err) {
    return { tag: "config_error", message: String(err) };
  }

  if (!sessionCookie) {
    // 没有会话时，检查系统是否尚未完成初始化。
    const setupController = new AbortController();
    const setupTimeout = setTimeout(
      () => setupController.abort(),
      SSR_AUTH_TIMEOUT_MS,
    );
    try {
      const setupRes = await fetch(
        `${internalGatewayUrl}/api/v1/auth/setup-status`,
        {
          cache: "no-store",
          signal: setupController.signal,
        },
      );
      clearTimeout(setupTimeout);
      if (setupRes.ok) {
        const setupData = (await setupRes.json()) as { needs_setup?: boolean };
        if (setupData.needs_setup) {
          return { tag: "system_setup_required" };
        }
      }
    } catch {
      clearTimeout(setupTimeout);
      // setup-status 不可达或超时时，继续按未认证状态处理。
    }
    return { tag: "unauthenticated" };
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), SSR_AUTH_TIMEOUT_MS);

  try {
    const res = await fetch(`${internalGatewayUrl}/api/v1/auth/me`, {
      headers: { Cookie: `access_token=${sessionCookie.value}` },
      cache: "no-store",
      signal: controller.signal,
    });
    clearTimeout(timeout); // 立即清除，覆盖所有响应分支。

    if (res.ok) {
      const parsed = userSchema.safeParse(await res.json());
      if (!parsed.success) {
        console.error("[SSR auth] Malformed /auth/me response:", parsed.error);
        return { tag: "gateway_unavailable" };
      }
      if (parsed.data.needs_setup) {
        return { tag: "needs_setup", user: parsed.data };
      }
      return { tag: "authenticated", user: parsed.data };
    }
    if (res.status === 401 || res.status === 403) {
      return { tag: "unauthenticated" };
    }
    console.error(`[SSR auth] /api/v1/auth/me responded ${res.status}`);
    return { tag: "gateway_unavailable" };
  } catch (err) {
    clearTimeout(timeout);
    console.error("[SSR auth] Failed to reach gateway:", err);
    return { tag: "gateway_unavailable" };
  }
}
