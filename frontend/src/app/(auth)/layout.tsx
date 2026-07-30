import { redirect } from "next/navigation";
import { type ReactNode } from "react";

import { GatewayOfflineFallback } from "@/components/workspace/gateway-offline-fallback";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { getServerSideUser } from "@/core/auth/server";
import { assertNever } from "@/core/auth/types";

/** 强制按请求解析认证状态，避免静态缓存用户会话。 */
export const dynamic = "force-dynamic";

/** 根据服务端认证状态提供登录相关页面，或重定向已登录用户。 */
export default async function AuthLayout({
  children,
}: {
  children: ReactNode;
}) {
  const result = await getServerSideUser();

  switch (result.tag) {
    case "authenticated":
      redirect("/workspace");
    case "needs_setup":
      // 初始化管理员时需要保留当前用户信息以完成设置。
      return <AuthProvider initialUser={result.user}>{children}</AuthProvider>;
    case "system_setup_required":
    case "unauthenticated":
      return <AuthProvider initialUser={null}>{children}</AuthProvider>;
    case "gateway_unavailable":
      // 认证页没有独立横幅，离线兜底在此提供可重试、可退出的认证上下文。
      return (
        <GatewayOfflineFallback renderBanner>
          <div className="flex h-screen flex-col items-center justify-center gap-4">
            <p className="text-muted-foreground">
              Service temporarily unavailable.
            </p>
          </div>
        </GatewayOfflineFallback>
      );
    case "config_error":
      throw new Error(result.message);
    default:
      assertNever(result);
  }
}
