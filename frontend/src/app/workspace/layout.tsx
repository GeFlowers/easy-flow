import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Toaster } from "sonner";

import { QueryClientProvider } from "@/components/query-client-provider";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { GatewayOfflineBanner } from "@/components/workspace/gateway-offline-banner";
import { GatewayOfflineFallback } from "@/components/workspace/gateway-offline-fallback";
import { WorkspaceSidebar } from "@/components/workspace/workspace-sidebar";
import { AuthProvider } from "@/features/auth/AuthProvider";
import { getServerSideUser } from "@/features/auth/server";
import { assertNever } from "@/features/auth/types";

/** 强制按请求验证工作区会话，避免静态缓存认证结果。 */
export const dynamic = "force-dynamic";

/** 在服务端校验访问工作区的用户，并按认证结果渲染或重定向。 */
export default async function WorkspaceLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const result = await getServerSideUser();

  switch (result.tag) {
    case "authenticated":
      return (
        <AuthProvider initialUser={result.user}>
          <WorkspaceContent>{children}</WorkspaceContent>
        </AuthProvider>
      );
    case "unauthenticated":
      redirect("/login");
    case "gateway_unavailable":
      // 离线兜底已提供认证上下文；工作区内容会在侧栏内挂载横幅，避免重复渲染。
      return (
        <GatewayOfflineFallback>
          <WorkspaceContent gatewayUnavailable>{children}</WorkspaceContent>
        </GatewayOfflineFallback>
      );
    case "config_error":
      throw new Error(result.message);
    default:
      assertNever(result);
  }
}

/** 装配工作区共享的查询、侧栏与通知上下文。 */
async function WorkspaceContent({
  children,
  gatewayUnavailable = false,
}: Readonly<{
  children: React.ReactNode;
  gatewayUnavailable?: boolean;
}>) {
  const cookieStore = await cookies();
  const initialSidebarOpen = parseSidebarOpenCookie(
    cookieStore.get("sidebar_state")?.value,
  );

  return (
    <QueryClientProvider>
      <SidebarProvider className="h-screen" defaultOpen={initialSidebarOpen}>
        <WorkspaceSidebar />
        <SidebarInset className="min-w-0">
          <GatewayOfflineBanner gatewayUnavailable={gatewayUnavailable} />
          {children}
        </SidebarInset>
      </SidebarProvider>
      <Toaster position="top-center" />
    </QueryClientProvider>
  );
}

/** 将侧边栏 Cookie 值转换为可供组件使用的布尔初始状态。 */
function parseSidebarOpenCookie(
  value: string | undefined,
): boolean | undefined {
  if (value === "true") return true;
  if (value === "false") return false;
  return undefined;
}
