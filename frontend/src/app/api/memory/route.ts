import type { NextRequest } from "next/server";

const BACKEND_BASE_URL =
  process.env.NEXT_PUBLIC_BACKEND_BASE_URL ?? "http://127.0.0.1:8001";

/** 构造指向后端 Memory API 的绝对地址。 */
function buildBackendUrl(pathname: string) {
  return new URL(pathname, BACKEND_BASE_URL);
}

/** 将前端 Memory API 请求透传至后端，并保留响应状态与响应头。 */
async function proxyRequest(request: NextRequest, pathname: string) {
  // 移除逐跳请求头，避免将浏览器到 Next.js 的连接信息错误转发给后端。
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

/** 代理读取根 Memory 资源的请求。 */
export async function GET(request: NextRequest) {
  return proxyRequest(request, "/api/memory");
}

/** 代理删除根 Memory 资源的请求。 */
export async function DELETE(request: NextRequest) {
  return proxyRequest(request, "/api/memory");
}
