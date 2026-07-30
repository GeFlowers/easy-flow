import { beforeEach, describe, expect, test, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "",
}));

import { fetchAgentsApiEnabled } from "@/core/agents/api";
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

describe("fetchAgentsApiEnabled", () => {
  /**
   * 覆盖“returns true when backend reports agents_api enabled”这一可观察行为，防止相关边界在重构后回归。
   */
  test("returns true when backend reports agents_api enabled", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, { agents_api: { enabled: true } }),
    );
    await expect(fetchAgentsApiEnabled()).resolves.toBe(true);
    expect(mockedFetch).toHaveBeenCalledWith("/api/features");
  });

  /**
   * 覆盖“returns false when backend reports agents_api disabled”这一可观察行为，防止相关边界在重构后回归。

   */

  test("returns false when backend reports agents_api disabled", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, { agents_api: { enabled: false } }),
    );
    await expect(fetchAgentsApiEnabled()).resolves.toBe(false);
  });

  /**
   * 覆盖“throws when the features request fails”这一可观察行为，防止相关边界在重构后回归。

   */

  test("throws when the features request fails", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(500, {}));
    await expect(fetchAgentsApiEnabled()).rejects.toThrow();
  });
});
