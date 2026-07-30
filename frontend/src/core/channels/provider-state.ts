import type { ChannelProvider } from "./types";

/** 判断提供商是否满足发起连接的条件。 */
export function providerCanConnect(provider: ChannelProvider): boolean {
  return (
    (provider.connectable ?? (provider.enabled && provider.configured)) &&
    provider.connection_status !== "connected"
  );
}

/** 判断提供商是否仍缺少连接所需的运行时配置。 */
export function providerNeedsRuntimeConfig(provider: ChannelProvider): boolean {
  return (
    provider.enabled &&
    !provider.configured &&
    (provider.credential_fields?.length ?? 0) > 0
  );
}

/** 判断提供商是否允许在界面中编辑运行时配置。 */
export function providerCanEditRuntimeConfig(
  provider: ChannelProvider,
): boolean {
  return provider.enabled && (provider.credential_fields?.length ?? 0) > 0;
}
