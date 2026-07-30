/**
 * 测试 `checkAgentName` 的错误分类行为。
 *
 * 问题 #3041：当后端返回非 200 响应（例如带数据库错误的 500、路由异常导致的
 * 422，或不属于 502/503/504 集合的其他 4xx/5xx）时，UI 曾将后端 detail
 * 吞并为通用的 “Could not verify name availability” 回退提示，因为页面级
 * catch 块只处理 `reason === "backend_unreachable"`。
 *
 * 修复后会将原始后端 detail 携带为 `AgentNameCheckError.detail`（它不同于
 * `message`；后者始终非空，因为当后端未发送 detail 时，`checkAgentName` 会
 * 替换为生成的回退值）。UI 使用 `detail` 判断应展示真实后端字符串，还是
 * 回退为本地化的 “could not verify” 文案。
 *
 * 这些测试固化了契约的两部分，避免未来重构悄悄丢失 detail，或将生成的
 * 回退值泄漏到 UI。
 */
import { beforeEach, describe, expect, test, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "",
}));

import { AgentsApiDisabledError, checkAgentName } from "@/core/agents/api";
import { fetch as fetcher } from "@/core/api/fetcher";

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

describe("checkAgentName", () => {
  /**
   * 覆盖“returns availability payload on 200”这一可观察行为，防止相关边界在重构后回归。
   */
  test("returns availability payload on 200", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, { available: true, name: "dealagent" }),
    );
    const result = await checkAgentName("dealagent");
    expect(result).toEqual({ available: true, name: "dealagent" });
  });

  /**
   * 覆盖“treats network-layer fetch rejection as backend_unreachable”这一可观察行为，防止相关边界在重构后回归。

   */

  test("treats network-layer fetch rejection as backend_unreachable", async () => {
    mockedFetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(checkAgentName("dealagent")).rejects.toMatchObject({
      name: "AgentNameCheckError",
      reason: "backend_unreachable",
    });
  });

  test.each([502, 503, 504])(
    "treats HTTP %i as backend_unreachable",
    async (status) => {
      mockedFetch.mockResolvedValueOnce(
        jsonResponse(status, { detail: "Bad Gateway" }),
      );
      await expect(checkAgentName("dealagent")).rejects.toMatchObject({
        name: "AgentNameCheckError",
        reason: "backend_unreachable",
      });
    },
  );

  /**
   * 覆盖“recognises agents_api disabled detail and throws AgentsApiDisabledError”这一可观察行为，防止相关边界在重构后回归。

   */

  test("recognises agents_api disabled detail and throws AgentsApiDisabledError", async () => {
    const detail =
      "Custom-agent management API is disabled. Set agents_api.enabled=true to expose agent and user-profile routes over HTTP.";
    mockedFetch.mockResolvedValueOnce(jsonResponse(403, { detail }));
    await expect(checkAgentName("dealagent")).rejects.toBeInstanceOf(
      AgentsApiDisabledError,
    );
  });

  /**
   * 覆盖“carries backend 422 detail through AgentNameCheckError.detail (issue #3041)”这一可观察行为，防止相关边界在重构后回归。

   */

  test("carries backend 422 detail through AgentNameCheckError.detail (issue #3041)", async () => {
    // 这是用户提交含禁止字符的名称时 `_validate_agent_name` 生成的准确响应
    // 形状——例如尾随空格、点号、中文字符，或从其他窗口粘贴的不可见空白。
    const detail =
      "Invalid agent name 'deal agent'. Must match ^[A-Za-z0-9-]+$ (letters, digits, and hyphens only).";
    mockedFetch.mockResolvedValueOnce(jsonResponse(422, { detail }));

    await expect(checkAgentName("deal agent")).rejects.toMatchObject({
      name: "AgentNameCheckError",
      reason: "request_failed",
      // 完整 detail 同时保留在 `detail`（供 UI 识别“真实后端 detail 与生成的
      // 回退值”）和 `message`（供堆栈跟踪/日志使用）中。
      detail,
      message: detail,
    });
  });

  /**
   * 覆盖“falls back to statusText in message but leaves detail null when backend returns no detail”这一可观察行为，防止相关边界在重构后回归。

   */

  test("falls back to statusText in message but leaves detail null when backend returns no detail", async () => {
    // 回退消息绝不能掩盖真实后端 detail 的缺失——页面级 catch 依赖
    // `detail === null` 选择本地化通用回退值，而不是渲染裸露的
    // “Failed to check agent name: Internal Server Error” 字符串。
    mockedFetch.mockResolvedValueOnce(
      new Response("", { status: 500, statusText: "Internal Server Error" }),
    );
    await expect(checkAgentName("dealagent")).rejects.toMatchObject({
      name: "AgentNameCheckError",
      reason: "request_failed",
      detail: null,
      message: expect.stringContaining("Internal Server Error"),
    });
  });

  /**
   * 覆盖“treats non-string detail as null (defence against future schema drift)”这一可观察行为，防止相关边界在重构后回归。

   */

  test("treats non-string detail as null (defence against future schema drift)", async () => {
    // 若后端将来在此端点返回 `{detail: {code, message}}`（当前认证错误使用的
    // 形状），我们绝不能展示 `[object Object]` 字符串。`detail` 应回退为 null，
    // 以便页面使用其本地化回退值。
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(500, { detail: { code: "x", message: "y" } }),
    );
    await expect(checkAgentName("dealagent")).rejects.toMatchObject({
      name: "AgentNameCheckError",
      reason: "request_failed",
      detail: null,
    });
  });

  /**
   * 覆盖“does not misclassify a 422 with unrelated detail as agents_api disabled”这一可观察行为，防止相关边界在重构后回归。

   */

  test("does not misclassify a 422 with unrelated detail as agents_api disabled", async () => {
    // 深度防御：禁用检测器按子串 "agents_api.enabled" 匹配，因此 detail 偶然包含
    // 同一子串的 422 会被错误分类。`_validate_agent_name` 生成的校验 detail
    // 从不包含它；本测试仅断言 “Invalid agent name ...” 仍留在 request_failed
    // 分支中，而页面现会在该分支展示它。
    const detail =
      "Invalid agent name 'deal.agent'. Must match ^[A-Za-z0-9-]+$ (letters, digits, and hyphens only).";
    mockedFetch.mockResolvedValueOnce(jsonResponse(422, { detail }));
    await expect(checkAgentName("deal.agent")).rejects.not.toBeInstanceOf(
      AgentsApiDisabledError,
    );
  });
});
