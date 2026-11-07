/** 描述 MCP 服务器的可扩展配置及其启用状态。 */
export interface MCPServerConfig extends Record<string, unknown> {
  enabled: boolean;
  description: string;
}

/** 描述按服务器名称索引的 MCP 配置集合。 */
export interface MCPConfig {
  mcp_servers: Record<string, MCPServerConfig>;
}
