/** 频道提供商的标识；预置值之外允许后端扩展。 */
export type ChannelProviderId = "wechat" | "wecom";

/** 描述提供商运行时配置表单中的单个凭据字段。 */
export interface ChannelCredentialField {
  name: string;
  label: string;
  type: string;
  required: boolean;
}

/** 按字段名保存的频道运行时配置值。 */
export type ChannelRuntimeConfigValues = Record<string, string>;

/** 描述频道提供商的启用、配置和连接状态。 */
export interface ChannelProvider {
  provider: ChannelProviderId;
  display_name: string;
  enabled: boolean;
  configured: boolean;
  connectable?: boolean;
  unavailable_reason?: string | null;
  auth_mode: string;
  connection_status: string;
  credential_fields: ChannelCredentialField[];
  credential_values?: ChannelRuntimeConfigValues;
}

/** 频道提供商列表接口的响应结构。 */
export interface ChannelProvidersResponse {
  enabled: boolean;
  providers: ChannelProvider[];
}

/** 描述一个已建立的外部频道账户连接。 */
export interface ChannelConnection {
  id: string;
  provider: ChannelProviderId;
  status: string;
  external_account_id?: string | null;
  external_account_name?: string | null;
  workspace_id?: string | null;
  workspace_name?: string | null;
  scopes: string[];
  metadata: Record<string, unknown>;
}

/** 频道连接列表接口的响应结构。 */
export interface ChannelConnectionsResponse {
  connections: ChannelConnection[];
}

/** 发起频道连接后返回的授权方式、地址和有效期。 */
export interface ChannelConnectResponse {
  provider: ChannelProviderId;
  mode: string;
  url?: string | null;
  code: string;
  instruction: string;
  expires_in: number;
}
