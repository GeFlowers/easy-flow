"use client";

import { AuthProvider } from "@/core/auth/AuthProvider";

import { GatewayOfflineBanner } from "./gateway-offline-banner";

interface GatewayOfflineFallbackProps {
  /** 为 true 时由本组件渲染横幅；workspace 布局已在 WorkspaceContent 的侧栏布局中挂载横幅，故传 false；`(auth)` 布局的普通子节点没有横幅，故传 true。 */
  renderBanner?: boolean;
  children?: React.ReactNode;
}

/** 服务端认证探测无法连通网关时，供 workspace 与 `(auth)` 布局共用的降级容器。它以 AuthProvider 包裹子节点，使横幅的探测、退出和刷新 Hook 可用，避免 `(auth)/layout.tsx` 的静态 HTML 缺少 AuthProvider / QueryClientProvider 而必须手动刷新才能恢复。 */
/** 为网关离线页面装配认证与查询上下文，允许横幅执行恢复操作。 */
export function GatewayOfflineFallback({
  renderBanner = false,
  children,
}: GatewayOfflineFallbackProps) {
  return (
    <AuthProvider initialUser={null}>
      {renderBanner && <GatewayOfflineBanner gatewayUnavailable />}
      {children}
    </AuthProvider>
  );
}
