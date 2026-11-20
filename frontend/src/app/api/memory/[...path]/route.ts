import type { NextRequest } from "next/server";
import { getGatewayConfig } from "@/features/auth/gateway-config";

const BACKEND_BASE_URL = getGatewayConfig().internalGatewayUrl;

/** 构造指向后端嵌套 Memory 资源的绝对地址。 */
function buildBackendUrl(pathname: string) {
  return new URL(pathname, BACKEND_BASE_URL);
}

/** 透传嵌套 Memory 请求，并保留后端的原始响应语义。 */
async function proxyRequest(request: NextRequest, pathname: string) {
  // 逐跳请求头仅适用于当前连接，不能转发到后端服务。
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("connection");
  headers.delete("content-length");

  const hasBody = !["GET", "HEAD"].includes(request.method);
  const response = await fetch(buildBackendUrl(pathname), {
    method: request.method,
    headers,
    body: hasBody ? await request.arrayBuffer() : undefined,
  });

  return new Response(await response.arrayBuffer(), {
    status: response.status,
    headers: response.headers,
  });
}

/** 代理读取指定嵌套 Memory 资源的请求。 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, `/api/memory/${(await params).path.join("/")}`);
}

/** 代理创建指定嵌套 Memory 资源的请求。 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, `/api/memory/${(await params).path.join("/")}`);
}

/** 代理删除指定嵌套 Memory 资源的请求。 */
export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, `/api/memory/${(await params).path.join("/")}`);
}

/** 代理更新指定嵌套 Memory 资源的请求。 */
export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, `/api/memory/${(await params).path.join("/")}`);
}
