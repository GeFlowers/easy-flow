import type { NextRequest } from "next/server";

import { getGatewayConfig } from "@/features/auth/gateway-config";

async function proxyRequest(request: NextRequest) {
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("connection");
  headers.delete("content-length");

  const response = await fetch(
    new URL("/api/global-instructions", getGatewayConfig().internalGatewayUrl),
    {
      method: request.method,
      headers,
      body: request.method === "GET" ? undefined : await request.arrayBuffer(),
    },
  );
  return new Response(await response.arrayBuffer(), {
    status: response.status,
    headers: response.headers,
  });
}

export const GET = proxyRequest;
export const PUT = proxyRequest;
