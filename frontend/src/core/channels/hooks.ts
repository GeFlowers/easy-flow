import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import {
  configureChannelProvider,
  connectChannelProvider,
  disconnectChannelConnection,
  disconnectChannelProvider,
  listChannelConnections,
  listChannelProviders,
} from "./api";
import { startConnectionPoll, type ConnectPollHandle } from "./connect-poll";
import type { ChannelProviderId, ChannelRuntimeConfigValues } from "./types";

/** 频道提供商查询使用的稳定缓存键。 */
export const channelProviderQueryKey = ["channelProviders"] as const;
/** 频道连接查询使用的稳定缓存键。 */
export const channelConnectionsQueryKey = ["channelConnections"] as const;

/** 查询频道提供商列表，并提供查询状态。 */
export function useChannelProviders() {
  const { data, isLoading, error } = useQuery({
    queryKey: channelProviderQueryKey,
    queryFn: () => listChannelProviders(),
  });
  return {
    enabled: data?.enabled ?? false,
    providers: data?.providers ?? [],
    isLoading,
    error,
  };
}

/** 查询已建立的频道连接，并提供查询状态。 */
export function useChannelConnections() {
  const { data, isLoading, error } = useQuery({
    queryKey: channelConnectionsQueryKey,
    queryFn: () => listChannelConnections(),
  });
  return { connections: data ?? [], isLoading, error };
}

/** 发起频道连接，并在连接完成前管理每个提供商唯一的轮询任务。 */
export function useConnectChannelProvider() {
  const queryClient = useQueryClient();
  const pollersRef = useRef<Map<ChannelProviderId, ConnectPollHandle>>(
    new Map(),
  );

  // 使用该 Hook 的组件卸载时取消所有进行中的轮询。
  useEffect(() => {
    const pollers = pollersRef.current;
    return () => {
      pollers.forEach((handle) => handle.cancel());
      pollers.clear();
    };
  }, []);

  return useMutation({
    mutationFn: (provider: ChannelProviderId) =>
      connectChannelProvider(provider),
    onSuccess: (result, provider) => {
      void queryClient.invalidateQueries({ queryKey: channelProviderQueryKey });
      void queryClient.invalidateQueries({
        queryKey: channelConnectionsQueryKey,
      });

      // 替换该提供商已有轮询，避免重复点击连接后产生竞争同一查询键的并行轮询链。
      pollersRef.current.get(provider)?.cancel();
      pollersRef.current.set(
        provider,
        startConnectionPoll({
          provider,
          expiresInSeconds: result.expires_in,
          fetchConnections: () =>
            queryClient.fetchQuery({
              queryKey: channelConnectionsQueryKey,
              queryFn: () => listChannelConnections(),
            }),
          onConnected: () => {
            // 绑定成功后只刷新一次派生的提供商状态。
            void queryClient.invalidateQueries({
              queryKey: channelProviderQueryKey,
            });
          },
        }),
      );
    },
  });
}

/** 返回保存频道运行时配置的变更操作，并在成功后刷新提供商缓存。 */
export function useConfigureChannelProvider() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      provider,
      values,
    }: {
      provider: ChannelProviderId;
      values: ChannelRuntimeConfigValues;
    }) => configureChannelProvider(provider, values),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: channelProviderQueryKey });
      void queryClient.invalidateQueries({
        queryKey: channelConnectionsQueryKey,
      });
    },
  });
}

/** 返回断开单个频道连接的变更操作，并在成功后刷新连接与提供商缓存。 */
export function useDisconnectChannelConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (connectionId: string) =>
      disconnectChannelConnection(connectionId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: channelProviderQueryKey });
      void queryClient.invalidateQueries({
        queryKey: channelConnectionsQueryKey,
      });
    },
  });
}

/** 返回断开某提供商全部连接的变更操作，并在成功后刷新相关缓存。 */
export function useDisconnectChannelProvider() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (provider: ChannelProviderId) =>
      disconnectChannelProvider(provider),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: channelProviderQueryKey });
      void queryClient.invalidateQueries({
        queryKey: channelConnectionsQueryKey,
      });
    },
  });
}
