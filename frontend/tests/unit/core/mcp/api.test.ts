/**
 * 测试 MCP 配置 API 客户端的错误处理行为。
 *
 * 问题 #3527：当非管理员用户打开 Settings → Tools 时，网关会为
 * `GET /api/mcp/config` 返回 403 `{detail: "Admin privileges required to manage MCP
 * configuration."}`。此前客户端将 403 响应体静默视为有效的 `MCPConfig`，因此 UI
 * 尝试 `Object.entries(config.mcp_servers)` 时会因 `Cannot convert undefined or null to object`
 * 崩溃。
 *
 * 这些测试固化如下契约：非 2xx 响应会作为携带 HTTP 状态和后端 `detail` 的
 * `MCPConfigRequestError` 暴露，使 React Query hook 的 `error` 分支能渲染
 * 友好的空状态（403 时提示需要管理员），而不是崩溃。
 */
import { beforeEach, describe, expect, test, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "",
}));

import { fetch as fetcher } from "@/core/api/fetcher";
import {
  MCPConfigRequestError,
  loadMCPConfig,
  updateMCPConfig,
} from "@/core/mcp/api";

const mockedFetch = rs.mocked(fetcher);

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 jsonResponse 的约定。

 */

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("loadMCPConfig", () => {
  /**
   * 覆盖“returns parsed config on 200”这一可观察行为，防止相关边界在重构后回归。
   */
  test("returns parsed config on 200", async () => {
    const config = { mcp_servers: { foo: { enabled: true } } };
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, config));
    await expect(loadMCPConfig()).resolves.toEqual(config);
  });

  /**
   * 覆盖“throws MCPConfigRequestError with isAdminRequired on 403 (issue #3527)”这一可观察行为，防止相关边界在重构后回归。

   */

  test("throws MCPConfigRequestError with isAdminRequired on 403 (issue #3527)", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(403, {
        detail: "Admin privileges required to manage MCP configuration.",
      }),
    );
    await expect(loadMCPConfig()).rejects.toMatchObject({
      name: "MCPConfigRequestError",
      status: 403,
      isAdminRequired: true,
      message: "Admin privileges required to manage MCP configuration.",
    });
  });

  /**
   * 覆盖“throws MCPConfigRequestError with isAdminRequired=false on non-403 errors”这一可观察行为，防止相关边界在重构后回归。

   */

  test("throws MCPConfigRequestError with isAdminRequired=false on non-403 errors", async () => {
    mockedFetch.mockResolvedValueOnce(
      new Response("", { status: 500, statusText: "Internal Server Error" }),
    );
    await expect(loadMCPConfig()).rejects.toMatchObject({
      name: "MCPConfigRequestError",
      status: 500,
      isAdminRequired: false,
      message: "Failed to load MCP configuration",
    });
  });

  /**
   * 覆盖“the rejected value is an instance of MCPConfigRequestError”这一可观察行为，防止相关边界在重构后回归。

   */

  test("the rejected value is an instance of MCPConfigRequestError", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(403, { detail: "nope" }));
    await expect(loadMCPConfig()).rejects.toBeInstanceOf(MCPConfigRequestError);
  });
});

describe("updateMCPConfig", () => {
  /**
   * 覆盖“returns parsed body on 200”这一可观察行为，防止相关边界在重构后回归。
   */
  test("returns parsed body on 200", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, { ok: true }));
    await expect(updateMCPConfig({ mcp_servers: {} })).resolves.toEqual({
      ok: true,
    });
  });

  /**
   * 覆盖“throws MCPConfigRequestError with isAdminRequired on 403”这一可观察行为，防止相关边界在重构后回归。

   */

  test("throws MCPConfigRequestError with isAdminRequired on 403", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(403, {
        detail: "Admin privileges required to manage MCP configuration.",
      }),
    );
    await expect(updateMCPConfig({ mcp_servers: {} })).rejects.toMatchObject({
      name: "MCPConfigRequestError",
      status: 403,
      isAdminRequired: true,
      message: "Admin privileges required to manage MCP configuration.",
    });
  });

  /**
   * 覆盖“falls back to generic message on non-403 errors”这一可观察行为，防止相关边界在重构后回归。

   */

  test("falls back to generic message on non-403 errors", async () => {
    mockedFetch.mockResolvedValueOnce(
      new Response("", { status: 500, statusText: "Internal Server Error" }),
    );
    await expect(updateMCPConfig({ mcp_servers: {} })).rejects.toMatchObject({
      name: "MCPConfigRequestError",
      status: 500,
      isAdminRequired: false,
      message: "Failed to update MCP configuration",
    });
  });
});
