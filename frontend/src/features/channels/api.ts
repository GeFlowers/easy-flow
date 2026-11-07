import { throwGatewayApiError } from "@/features/api/errors";
import { fetch } from "@/features/api/fetcher";
import { getBackendBaseURL } from "@/features/config";

import type {
  ChannelConnectResponse,
  ChannelConnection,
  ChannelConnectionsResponse,
  ChannelProviderId,
  ChannelProvider,
  ChannelProvidersResponse,
  ChannelRuntimeConfigValues,
  WechatLoginStatus,
} from "./types";

/** 拼接频道 API 的基础地址和指定子路径。 */
function channelsUrl(path: string): string {
  return `${getBackendBaseURL()}/api/channels${path}`;
}

/** 发起个人微信扫码登录，由后端生成二维码并等待微信确认。 */
export async function startWechatLogin(): Promise<WechatLoginStatus> {
  const response = await fetch(channelsUrl("/wechat/login"), {
    method: "POST",
  });
  if (!response.ok)
    await throwGatewayApiError(response, "无法发起微信扫码登录");
  return response.json() as Promise<WechatLoginStatus>;
}

/** 查询当前管理员发起的微信扫码进度。 */
export async function getWechatLogin(
  loginId: string,
): Promise<WechatLoginStatus> {
  const response = await fetch(
    channelsUrl(`/wechat/login/${encodeURIComponent(loginId)}`),
  );
  if (!response.ok)
    await throwGatewayApiError(response, "无法读取微信扫码状态");
  return response.json() as Promise<WechatLoginStatus>;
}

/** 关闭扫码窗口时取消尚未完成的会话，已登录通道保持运行。 */
export async function cancelWechatLogin(loginId: string): Promise<void> {
  const response = await fetch(
    channelsUrl(`/wechat/login/${encodeURIComponent(loginId)}`),
    { method: "DELETE" },
  );
  if (!response.ok && response.status !== 404)
    await throwGatewayApiError(response, "无法取消微信扫码登录");
}

/** 获取全部频道提供商及其当前配置状态。 */
export async function listChannelProviders(): Promise<ChannelProvidersResponse> {
  const response = await fetch(channelsUrl("/providers"));
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to load channel providers: ${response.statusText}`,
    );
  }
  return response.json() as Promise<ChannelProvidersResponse>;
}

/** 获取已建立的频道连接列表。 */
export async function listChannelConnections(): Promise<ChannelConnection[]> {
  const response = await fetch(channelsUrl("/connections"));
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to load channel connections: ${response.statusText}`,
    );
  }
  const data = (await response.json()) as ChannelConnectionsResponse;
  return data.connections;
}

/** 发起指定频道提供商的连接流程。 */
export async function connectChannelProvider(
  provider: ChannelProviderId,
): Promise<ChannelConnectResponse> {
  const response = await fetch(
    channelsUrl(`/${encodeURIComponent(provider)}/connect`),
    { method: "POST" },
  );
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to connect ${provider}: ${response.statusText}`,
    );
  }
  return response.json() as Promise<ChannelConnectResponse>;
}

/** 保存指定频道提供商的运行时配置。 */
export async function configureChannelProvider(
  provider: ChannelProviderId,
  values: ChannelRuntimeConfigValues,
): Promise<ChannelProvider> {
  const response = await fetch(
    channelsUrl(`/${encodeURIComponent(provider)}/runtime-config`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values }),
    },
  );
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to configure ${provider}: ${response.statusText}`,
    );
  }
  return response.json() as Promise<ChannelProvider>;
}

/** 断开指定频道连接。 */
export async function disconnectChannelConnection(
  connectionId: string,
): Promise<void> {
  const response = await fetch(
    channelsUrl(`/connections/${encodeURIComponent(connectionId)}`),
    { method: "DELETE" },
  );
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to disconnect channel: ${response.statusText}`,
    );
  }
}

/** 断开指定提供商下的全部频道连接。 */
export async function disconnectChannelProvider(
  provider: ChannelProviderId,
): Promise<ChannelProvider> {
  const response = await fetch(
    channelsUrl(`/${encodeURIComponent(provider)}/runtime-config`),
    { method: "DELETE" },
  );
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to disconnect ${provider}: ${response.statusText}`,
    );
  }
  return response.json() as Promise<ChannelProvider>;
}
