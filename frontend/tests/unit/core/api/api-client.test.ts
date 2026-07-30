import { afterEach, expect, test, rs } from "@rstest/core";

import {
  clearReconnectRun,
  getAPIClient,
  isInactiveRunStreamError,
  isRunNotCancellableError,
} from "@/core/api/api-client";

/**
 * 构造测试所需的稳定夹具，使调用处能够明确复用 makeSessionStorage 的约定。

 */

function makeSessionStorage() {
  const values = new Map<string, string>();
  return {
    getItem: rs.fn((key: string) => values.get(key) ?? null),
    removeItem: rs.fn((key: string) => {
      values.delete(key);
    }),
    setItem: rs.fn((key: string, value: string) => {
      values.set(key, value);
    }),
  };
}

afterEach(() => {
  rs.unstubAllGlobals();
});

/**
 * 覆盖“identifies inactive run stream errors”这一可观察行为，防止相关边界在重构后回归。

 */

test("identifies inactive run stream errors", () => {
  const error = Object.assign(
    new Error(
      'HTTP 409: {"detail":"Run run-1 is not active on this worker and cannot be streamed"}',
    ),
    { status: 409 },
  );

  expect(isInactiveRunStreamError(error)).toBe(true);
});

/**
 * 覆盖“does not classify unrelated conflict errors as inactive streams”这一可观察行为，防止相关边界在重构后回归。

 */

test("does not classify unrelated conflict errors as inactive streams", () => {
  const error = Object.assign(new Error("HTTP 409: run is still active"), {
    status: 409,
  });

  expect(isInactiveRunStreamError(error)).toBe(false);
});

/**
 * 覆盖“clears matching reconnect metadata”这一可观察行为，防止相关边界在重构后回归。

 */

test("clears matching reconnect metadata", () => {
  const sessionStorage = makeSessionStorage();
  sessionStorage.setItem("lg:stream:thread-1", "run-1");
  rs.stubGlobal("window", { sessionStorage });

  clearReconnectRun("thread-1", "run-1");

  expect(sessionStorage.removeItem).toHaveBeenCalledWith("lg:stream:thread-1");
});

/**
 * 覆盖“keeps newer reconnect metadata”这一可观察行为，防止相关边界在重构后回归。

 */

test("keeps newer reconnect metadata", () => {
  const sessionStorage = makeSessionStorage();
  sessionStorage.setItem("lg:stream:thread-1", "newer-run");
  rs.stubGlobal("window", { sessionStorage });

  clearReconnectRun("thread-1", "stale-run");

  expect(sessionStorage.removeItem).not.toHaveBeenCalled();
});

/**
 * 覆盖“ignores reconnect metadata storage access failures”这一可观察行为，防止相关边界在重构后回归。

 */

test("ignores reconnect metadata storage access failures", () => {
  rs.stubGlobal("window", {
    get sessionStorage() {
      throw new DOMException("Blocked", "SecurityError");
    },
  });

  expect(() => clearReconnectRun("thread-1", "run-1")).not.toThrow();
});

/**
 * 覆盖“clears stale reconnect metadata when join stream cannot be resumed”这一可观察行为，防止相关边界在重构后回归。

 */

test("clears stale reconnect metadata when join stream cannot be resumed", async () => {
  const sessionStorage = makeSessionStorage();
  sessionStorage.setItem("lg:stream:thread-1", "run-1");
  rs.stubGlobal("window", {
    location: { origin: "http://localhost:2026" },
    sessionStorage,
  });
  rs.stubGlobal(
    "fetch",
    rs.fn(async () => {
      return new Response(
        JSON.stringify({
          detail:
            "Run run-1 is not active on this worker and cannot be streamed",
        }),
        { status: 409 },
      );
    }),
  );

  await expect(
    getAPIClient(true).runs.joinStream("thread-1", "run-1").next(),
  ).resolves.toMatchObject({ done: true });

  expect(sessionStorage.removeItem).toHaveBeenCalledWith("lg:stream:thread-1");
});

/**
 * 覆盖“rethrows unrelated streaming errors”这一可观察行为，防止相关边界在重构后回归。

 */

test("rethrows unrelated streaming errors", async () => {
  const sessionStorage = makeSessionStorage();
  sessionStorage.setItem("lg:stream:thread-1", "run-1");
  rs.stubGlobal("window", {
    location: { origin: "http://localhost:2026" },
    sessionStorage,
  });
  rs.stubGlobal(
    "fetch",
    rs.fn(async () => {
      return new Response(JSON.stringify({ detail: "run is still active" }), {
        status: 409,
      });
    }),
  );

  await expect(
    getAPIClient(true).runs.joinStream("thread-1", "run-1").next(),
  ).rejects.toThrow("HTTP 409");

  expect(sessionStorage.removeItem).not.toHaveBeenCalled();
});

/**
 * 覆盖“identifies terminal-state cancel conflicts”这一可观察行为，防止相关边界在重构后回归。

 */

test("identifies terminal-state cancel conflicts", () => {
  const error = Object.assign(
    new Error(
      'HTTP 409: {"detail":"Run run-1 is not cancellable (status: success)"}',
    ),
    { status: 409 },
  );

  expect(isRunNotCancellableError(error)).toBe(true);
});

/**
 * 覆盖“does not classify not-active-on-worker cancel as terminal”这一可观察行为，防止相关边界在重构后回归。

 */

test("does not classify not-active-on-worker cancel as terminal", () => {
  // 仍在另一工作节点上等待/运行的任务是真正的取消失败——
  // 必须保持可见，绝不能被吞掉。
  const error = Object.assign(
    new Error(
      'HTTP 409: {"detail":"Run run-1 is not active on this worker and cannot be cancelled"}',
    ),
    { status: 409 },
  );

  expect(isRunNotCancellableError(error)).toBe(false);
});

/**
 * 覆盖“swallows terminal-state cancel 409 and clears stale key”这一可观察行为，防止相关边界在重构后回归。

 */

test("swallows terminal-state cancel 409 and clears stale key", async () => {
  const sessionStorage = makeSessionStorage();
  sessionStorage.setItem("lg:stream:thread-1", "run-1");
  rs.stubGlobal("window", {
    location: { origin: "http://localhost:2026" },
    sessionStorage,
  });
  rs.stubGlobal(
    "fetch",
    rs.fn(async () => {
      return new Response(
        JSON.stringify({
          detail: "Run run-1 is not cancellable (status: success)",
        }),
        { status: 409 },
      );
    }),
  );

  // 正常完成（不抛出异常）——取消已结束的任务应为无操作。
  await expect(
    getAPIClient(true).runs.cancel("thread-1", "run-1"),
  ).resolves.toBeUndefined();

  expect(sessionStorage.removeItem).toHaveBeenCalledWith("lg:stream:thread-1");
});

/**
 * 覆盖“rethrows not-active-on-worker cancel 409”这一可观察行为，防止相关边界在重构后回归。

 */

test("rethrows not-active-on-worker cancel 409", async () => {
  const sessionStorage = makeSessionStorage();
  sessionStorage.setItem("lg:stream:thread-1", "run-1");
  rs.stubGlobal("window", {
    location: { origin: "http://localhost:2026" },
    sessionStorage,
  });
  rs.stubGlobal(
    "fetch",
    rs.fn(async () => {
      return new Response(
        JSON.stringify({
          detail:
            "Run run-1 is not active on this worker and cannot be cancelled",
        }),
        { status: 409 },
      );
    }),
  );

  await expect(
    getAPIClient(true).runs.cancel("thread-1", "run-1"),
  ).rejects.toThrow("HTTP 409");

  expect(sessionStorage.removeItem).not.toHaveBeenCalled();
});

/**
 * 覆盖“short-circuits reconnect to a terminal run”这一可观察行为，防止相关边界在重构后回归。

 */

test("short-circuits reconnect to a terminal run", async () => {
  const sessionStorage = makeSessionStorage();
  sessionStorage.setItem("lg:stream:thread-1", "run-1");
  const fetchFn = rs.fn(async (url: string | URL) => {
    const path = url.toString();
    // 预检 GET /threads/{tid}/runs/{runId} 报告任务已结束。
    if (path.endsWith("/runs/run-1")) {
      return new Response(JSON.stringify({ status: "success" }), {
        status: 200,
      });
    }
    // 若尝试 join，则其绝不能执行；一旦执行应明确失败。
    return new Response(JSON.stringify({ detail: "unexpected join" }), {
      status: 500,
    });
  });
  rs.stubGlobal("window", {
    location: { origin: "http://localhost:2026" },
    sessionStorage,
  });
  rs.stubGlobal("fetch", fetchFn);

  const gen = getAPIClient(true).runs.joinStream("thread-1", "run-1");
  await expect(gen.next()).resolves.toMatchObject({ done: true });

  // 仅执行预检——除 GET 外不应发出 stream/join 请求。
  expect(fetchFn).toHaveBeenCalledTimes(1);
  expect(sessionStorage.removeItem).toHaveBeenCalledWith("lg:stream:thread-1");
});

/**
 * 覆盖“falls back to join when preflight cannot resolve the run”这一可观察行为，防止相关边界在重构后回归。

 */

test("falls back to join when preflight cannot resolve the run", async () => {
  const sessionStorage = makeSessionStorage();
  sessionStorage.setItem("lg:stream:thread-1", "run-1");
  const fetchFn = rs.fn(async (url: string | URL) => {
    const path = url.toString();
    // 预检 GET 返回 404（记录已被驱逐）——必须回退到 join。
    if (path.endsWith("/runs/run-1")) {
      return new Response(JSON.stringify({ detail: "Run run-1 not found" }), {
        status: 404,
      });
    }
    // 随后 join 会暴露 inactive-stream 409 并清除该键。
    return new Response(
      JSON.stringify({
        detail: "Run run-1 is not active on this worker and cannot be streamed",
      }),
      { status: 409 },
    );
  });
  rs.stubGlobal("window", {
    location: { origin: "http://localhost:2026" },
    sessionStorage,
  });
  rs.stubGlobal("fetch", fetchFn);

  await expect(
    getAPIClient(true).runs.joinStream("thread-1", "run-1").next(),
  ).resolves.toMatchObject({ done: true });

  expect(sessionStorage.removeItem).toHaveBeenCalledWith("lg:stream:thread-1");
});

/**
 * 覆盖“proceeds to join when the run is still active”这一可观察行为，防止相关边界在重构后回归。

 */

test("proceeds to join when the run is still active", async () => {
  // 正常路径：运行中/等待中的任务绝不能被短路——预检必须放行真实 join，
  // 以便重新接入进行中的流。这证明该保护不会过度跳过活跃任务。
  const sessionStorage = makeSessionStorage();
  sessionStorage.setItem("lg:stream:thread-1", "run-1");
  const fetchFn = rs.fn(async (url: string | URL) => {
    const path = url.toString();
    // 预检 GET 报告任务处于活跃状态。
    if (path.endsWith("/runs/run-1")) {
      return new Response(JSON.stringify({ status: "running" }), {
        status: 200,
      });
    }
    // 尝试真实 join（此处暴露 inactive-stream 409，包装器会捕获它并清除该键，
    // 与生产环境路径一致）。
    return new Response(
      JSON.stringify({
        detail: "Run run-1 is not active on this worker and cannot be streamed",
      }),
      { status: 409 },
    );
  });
  rs.stubGlobal("window", {
    location: { origin: "http://localhost:2026" },
    sessionStorage,
  });
  rs.stubGlobal("fetch", fetchFn);

  await expect(
    getAPIClient(true).runs.joinStream("thread-1", "run-1").next(),
  ).resolves.toMatchObject({ done: true });

  // 两个请求：预检 GET 加真实 join。若短路则只会有一个请求。
  expect(fetchFn).toHaveBeenCalledTimes(2);
  expect(sessionStorage.removeItem).toHaveBeenCalledWith("lg:stream:thread-1");
});

/**
 * 覆盖“short-circuits reconnect to an interrupted (user-cancelled) run”这一可观察行为，防止相关边界在重构后回归。

 */

test("short-circuits reconnect to an interrupted (user-cancelled) run", async () => {
  // 回归场景：interrupted 是由 RunManager.cancel() 写入的持久化终态。
  // 重新连接它时必须像其他终态一样短路；否则桥接层被清理后，joinStream 会
  // 永久阻塞，且 isLoading 一直卡住。此项使前端状态集合与后端 RunStatus
  // 契约保持一致。
  const sessionStorage = makeSessionStorage();
  sessionStorage.setItem("lg:stream:thread-1", "run-1");
  const fetchFn = rs.fn(async (url: string | URL) => {
    const path = url.toString();
    if (path.endsWith("/runs/run-1")) {
      return new Response(JSON.stringify({ status: "interrupted" }), {
        status: 200,
      });
    }
    return new Response(JSON.stringify({ detail: "unexpected join" }), {
      status: 500,
    });
  });
  rs.stubGlobal("window", {
    location: { origin: "http://localhost:2026" },
    sessionStorage,
  });
  rs.stubGlobal("fetch", fetchFn);

  const gen = getAPIClient(true).runs.joinStream("thread-1", "run-1");
  await expect(gen.next()).resolves.toMatchObject({ done: true });

  expect(fetchFn).toHaveBeenCalledTimes(1);
  expect(sessionStorage.removeItem).toHaveBeenCalledWith("lg:stream:thread-1");
});
