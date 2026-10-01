"use client";

import { useEffect, useRef } from "react";

import { useAuth } from "@/core/auth/AuthProvider";
import { userSchema, type User } from "@/core/auth/types";
import { useI18n } from "@/core/i18n/hooks";

import {
  OFFLINE_BANNER_RETRY_INTERVAL_MS,
  classifyProbe,
  decideProbeAction,
  shouldShowOfflineBanner,
} from "./gateway-offline-banner-helpers";

interface GatewayOfflineBannerProps {
  /** 服务端 `/api/v1/auth/me` 探测无法连通网关时为 true；横幅会保留到客户端探测恢复并填充 `user`。 */
  gatewayUnavailable: boolean;
}

/** 网关暂不可用时轮询认证状态，并在恢复或会话过期时交接给认证系统。 */
/** 在网关暂不可达时提供恢复中的可见反馈，并在认证恢复后自动撤销轮询。 */
export function GatewayOfflineBanner({
  gatewayUnavailable,
}: GatewayOfflineBannerProps) {
  const { t } = useI18n();
  const { user, applyUser, refreshUser, logout } = useAuth();
  // 网关仍然缓慢响应时，避免堆积重复的探测请求。
  const inFlightRef = useRef(false);
  // 记录连续 401，以区分“启动预热中的短暂 401”和“会话确已过期”，
  // 防止横幅给出错误提示。
  const authFailuresRef = useRef(0);

  useEffect(() => {
    if (!gatewayUnavailable) return;
    // AuthProvider 恢复用户后横幅已完成使命，停止轮询，避免在整个页面
    // 生命周期内每 10 秒继续探测（gatewayUnavailable 是服务端渲染的属性，
    // 完整刷新前会一直为 true）。
    if (user !== null) return;

    /** 低频探测认证接口，确认网关恢复后更新横幅状态并停止轮询。 */
    const probe = async () => {
      if (inFlightRef.current) return;
      inFlightRef.current = true;
      let res: Response | null = null;
      let errored = false;
      let parsedUser: User | null = null;
      try {
        res = await fetch("/api/v1/auth/me", {
          credentials: "include",
          cache: "no-store",
        });
        // 复用当前探测的响应体，不通过 refreshUser() 再发一次 /auth/me；
        // 这样能将本就负载较高的网关在恢复瞬间承受的请求量减半。
        if (res.ok) {
          try {
            const data = await res.json();
            const parsed = userSchema.safeParse(data);
            if (parsed.success) parsedUser = parsed.data;
          } catch (err) {
            console.warn(
              "[gateway-offline-banner] probe body parse failed:",
              err,
            );
          }
        }
      } catch (err) {
        console.warn("[gateway-offline-banner] probe failed:", err);
        errored = true;
      } finally {
        inFlightRef.current = false;
      }

      const action = decideProbeAction(
        authFailuresRef.current,
        classifyProbe(res, errored, parsedUser),
      );

      if (action.type === "apply-user") {
        authFailuresRef.current = 0;
        applyUser(action.user);
        return;
      }
      if (action.type === "delegate-refresh") {
        // 交由 AuthProvider 处理；它会在 401 时重定向至 /login。
        authFailuresRef.current = 0;
        await refreshUser();
        return;
      }
      authFailuresRef.current = action.nextFailureCount;
    };

    void probe();
    const handle = window.setInterval(() => {
      void probe();
    }, OFFLINE_BANNER_RETRY_INTERVAL_MS);
    return () => {
      window.clearInterval(handle);
    };
  }, [gatewayUnavailable, user, applyUser, refreshUser]);

  if (!shouldShowOfflineBanner(user, gatewayUnavailable)) {
    return null;
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className="bg-muted text-muted-foreground flex items-center justify-between gap-3 border-b px-4 py-2 text-sm"
    >
      <span>
        {t.workspace.gatewayUnavailable}{" "}
        {t.workspace.gatewayUnavailableRetrying}
      </span>
      <button
        type="button"
        onClick={() => {
          void logout();
        }}
        className="hover:bg-background rounded-md border px-3 py-1 text-xs"
      >
        {t.workspace.logout}
      </button>
    </div>
  );
}
