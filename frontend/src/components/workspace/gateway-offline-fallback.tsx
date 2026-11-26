"use client";

import { AuthProvider } from "@/features/auth/AuthProvider";

import { GatewayOfflineBanner } from "./gateway-offline-banner";

interface GatewayOfflineFallbackProps {
  /** 登录页布局通过此属性渲染横幅，工作区在 WorkspaceContent 中渲染横幅。 */
  renderBanner?: boolean;
  children?: React.ReactNode;
}

/** 供工作区和登录页布局使用的网关离线容器，为横幅提供认证和查询上下文。 */
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
