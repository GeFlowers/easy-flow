import { describe, expect, it } from "@rstest/core";

import {
  providerCanConnect,
  providerCanEditRuntimeConfig,
  providerNeedsRuntimeConfig,
} from "@/core/channels/provider-state";
import type { ChannelProvider } from "@/core/channels/types";

/**
 * 构造测试所需的稳定夹具，使调用处能够明确复用 makeProvider 的约定。

 */

function makeProvider(overrides: Partial<ChannelProvider>): ChannelProvider {
  return {
    provider: "slack",
    display_name: "Slack",
    enabled: true,
    configured: true,
    connectable: true,
    auth_mode: "binding_code",
    connection_status: "not_connected",
    credential_fields: [
      {
        name: "bot_token",
        label: "Bot token",
        type: "password",
        required: true,
      },
    ],
    ...overrides,
  };
}

describe("providerCanConnect", () => {
  /**
   * 覆盖“allows connecting a configured, not yet connected provider”这一可观察行为，防止相关边界在重构后回归。
   */
  it("allows connecting a configured, not yet connected provider", () => {
    expect(providerCanConnect(makeProvider({}))).toBe(true);
  });

  /**
   * 覆盖“rejects an already connected provider”这一可观察行为，防止相关边界在重构后回归。

   */

  it("rejects an already connected provider", () => {
    expect(
      providerCanConnect(makeProvider({ connection_status: "connected" })),
    ).toBe(false);
  });

  /**
   * 覆盖“rejects a non-connectable provider”这一可观察行为，防止相关边界在重构后回归。

   */

  it("rejects a non-connectable provider", () => {
    expect(providerCanConnect(makeProvider({ connectable: false }))).toBe(
      false,
    );
  });

  /**
   * 覆盖“falls back to enabled+configured when connectable is missing”这一可观察行为，防止相关边界在重构后回归。

   */

  it("falls back to enabled+configured when connectable is missing", () => {
    expect(providerCanConnect(makeProvider({ connectable: undefined }))).toBe(
      true,
    );
    expect(
      providerCanConnect(
        makeProvider({ connectable: undefined, configured: false }),
      ),
    ).toBe(false);
  });
});

describe("providerNeedsRuntimeConfig", () => {
  /**
   * 覆盖“requires setup only when enabled and unconfigured with fields”这一可观察行为，防止相关边界在重构后回归。
   */
  it("requires setup only when enabled and unconfigured with fields", () => {
    expect(
      providerNeedsRuntimeConfig(makeProvider({ configured: false })),
    ).toBe(true);
    expect(providerNeedsRuntimeConfig(makeProvider({}))).toBe(false);
    expect(
      providerNeedsRuntimeConfig(
        makeProvider({ configured: false, enabled: false }),
      ),
    ).toBe(false);
    expect(
      providerNeedsRuntimeConfig(
        makeProvider({ configured: false, credential_fields: [] }),
      ),
    ).toBe(false);
  });
});

describe("providerCanEditRuntimeConfig", () => {
  /**
   * 覆盖“is editable whenever enabled with credential fields”这一可观察行为，防止相关边界在重构后回归。
   */
  it("is editable whenever enabled with credential fields", () => {
    expect(providerCanEditRuntimeConfig(makeProvider({}))).toBe(true);
    expect(providerCanEditRuntimeConfig(makeProvider({ enabled: false }))).toBe(
      false,
    );
    expect(
      providerCanEditRuntimeConfig(makeProvider({ credential_fields: [] })),
    ).toBe(false);
  });
});
