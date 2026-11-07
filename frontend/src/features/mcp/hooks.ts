import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { loadMCPConfig, MCPConfigRequestError, updateMCPConfig } from "./api";

/** 查询 MCP 配置；权限错误不重试，其他请求错误最多重试三次。 */
export function useMCPConfig() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["mcpConfig"],
    queryFn: () => loadMCPConfig(),
    retry: (count, error) =>
      !(error instanceof MCPConfigRequestError) && count < 3,
  });
  return { config: data, isLoading, error };
}

/** 返回切换单个 MCP 服务器启用状态的变更操作。 */
export function useEnableMCPServer() {
  const queryClient = useQueryClient();
  const { config } = useMCPConfig();
  return useMutation({
    mutationFn: async ({
      serverName,
      enabled,
    }: {
      serverName: string;
      enabled: boolean;
    }) => {
      if (!config) {
        throw new Error("MCP config not found");
      }
      if (!config.mcp_servers[serverName]) {
        throw new Error(`MCP server ${serverName} not found`);
      }
      await updateMCPConfig({
        mcp_servers: {
          ...config.mcp_servers,
          [serverName]: {
            ...config.mcp_servers[serverName],
            enabled,
          },
        },
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["mcpConfig"] });
    },
  });
}
