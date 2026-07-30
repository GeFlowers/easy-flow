import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

/** 输入建议功能配置的接口响应。 */
export interface SuggestionsConfigResponse {
  enabled: boolean;
}

/** 从后端加载输入建议配置。 */
export async function loadSuggestionsConfig(): Promise<SuggestionsConfigResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/suggestions/config`);
  if (!response.ok) {
    if (response.status === 404) {
      // 兼容旧后端时默认启用。
      return { enabled: true };
    }
    throw new Error(
      `Failed to load suggestions config: ${response.statusText}`,
    );
  }
  return response.json() as Promise<SuggestionsConfigResponse>;
}
