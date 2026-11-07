/** 描述后端可选模型及其能力的配置项。 */
export interface Model {
  id: string;
  name: string;
  model: string;
  display_name: string;
  description?: string | null;
  supports_thinking?: boolean;
  supports_reasoning_effort?: boolean;
}

/** 控制令牌用量展示功能的设置。 */
export interface TokenUsageSettings {
  enabled: boolean;
}

/** 模型列表与令牌用量设置的接口响应。 */
export interface ModelsResponse {
  models: Model[];
  token_usage: TokenUsageSettings;
}
