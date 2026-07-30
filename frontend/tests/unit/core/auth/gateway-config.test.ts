import {
  afterEach,
  beforeEach,
  describe,
  expect,
  test,
  rs,
} from "@rstest/core";

const ENV_KEYS = [
  "NODE_ENV",
  "DEER_FLOW_INTERNAL_GATEWAY_BASE_URL",
  "DEER_FLOW_TRUSTED_ORIGINS",
] as const;

type EnvSnapshot = Partial<
  Record<(typeof ENV_KEYS)[number], string | undefined>
>;

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 snapshotEnv 的约定。

 */

function snapshotEnv(): EnvSnapshot {
  const snapshot: EnvSnapshot = {};
  for (const key of ENV_KEYS) {
    snapshot[key] = process.env[key];
  }
  return snapshot;
}

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 setEnv 的约定。

 */

function setEnv(key: (typeof ENV_KEYS)[number], value: string | undefined) {
  // NODE_ENV 的类型是只读字面量联合，因此通过索引签名访问，以使测试在各场景下
  // 都能通过编译。
  const env = process.env as Record<string, string | undefined>;
  if (value === undefined) {
    delete env[key];
  } else {
    env[key] = value;
  }
}

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 restoreEnv 的约定。

 */

function restoreEnv(snapshot: EnvSnapshot) {
  for (const key of ENV_KEYS) {
    setEnv(key, snapshot[key]);
  }
}

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 loadFreshConfig 的约定。

 */

async function loadFreshConfig() {
  rs.resetModules();
  return await import("@/core/auth/gateway-config");
}

describe("getGatewayConfig", () => {
  let saved: EnvSnapshot;

  beforeEach(() => {
    saved = snapshotEnv();
    setEnv("DEER_FLOW_INTERNAL_GATEWAY_BASE_URL", undefined);
    setEnv("DEER_FLOW_TRUSTED_ORIGINS", undefined);
  });

  afterEach(() => {
    restoreEnv(saved);
  });

  /**
   * 覆盖“returns localhost defaults when env is unset in development”这一可观察行为，防止相关边界在重构后回归。

   */

  test("returns localhost defaults when env is unset in development", async () => {
    setEnv("NODE_ENV", "development");

    const { getGatewayConfig } = await loadFreshConfig();
    const cfg = getGatewayConfig();

    expect(cfg.internalGatewayUrl).toBe("http://127.0.0.1:8001");
    expect(cfg.trustedOrigins).toEqual(["http://localhost:3000"]);
  });

  /**
   * 覆盖“returns localhost defaults when env is unset in production (regression: issue #2705)”这一可观察行为，防止相关边界在重构后回归。

   */

  test("returns localhost defaults when env is unset in production (regression: issue #2705)", async () => {
    setEnv("NODE_ENV", "production");

    const { getGatewayConfig } = await loadFreshConfig();

    expect(() => getGatewayConfig()).not.toThrow();
    const cfg = getGatewayConfig();
    expect(cfg.internalGatewayUrl).toBe("http://127.0.0.1:8001");
    expect(cfg.trustedOrigins).toEqual(["http://localhost:3000"]);
  });

  /**
   * 覆盖“uses env values verbatim when set, regardless of NODE_ENV”这一可观察行为，防止相关边界在重构后回归。

   */

  test("uses env values verbatim when set, regardless of NODE_ENV", async () => {
    setEnv("NODE_ENV", "production");
    setEnv("DEER_FLOW_INTERNAL_GATEWAY_BASE_URL", "https://gw.example.com/");
    setEnv(
      "DEER_FLOW_TRUSTED_ORIGINS",
      "https://app.example.com, https://admin.example.com",
    );

    const { getGatewayConfig } = await loadFreshConfig();
    const cfg = getGatewayConfig();

    expect(cfg.internalGatewayUrl).toBe("https://gw.example.com");
    expect(cfg.trustedOrigins).toEqual([
      "https://app.example.com",
      "https://admin.example.com",
    ]);
  });

  /**
   * 覆盖“trims and filters empty entries in trustedOrigins”这一可观察行为，防止相关边界在重构后回归。

   */

  test("trims and filters empty entries in trustedOrigins", async () => {
    setEnv("NODE_ENV", "production");
    setEnv("DEER_FLOW_INTERNAL_GATEWAY_BASE_URL", "https://gw.example.com");
    setEnv(
      "DEER_FLOW_TRUSTED_ORIGINS",
      " https://a.example , ,https://b.example ",
    );

    const { getGatewayConfig } = await loadFreshConfig();
    const cfg = getGatewayConfig();

    expect(cfg.trustedOrigins).toEqual([
      "https://a.example",
      "https://b.example",
    ]);
  });
});
