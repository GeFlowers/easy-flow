import { getBackendBaseURL } from "../config";

import type { ModelsResponse } from "./types";

/** 获取后端可用模型及令牌用量开关。 */
export async function loadModels(): Promise<ModelsResponse> {
  const res = await fetch(`${getBackendBaseURL()}/api/models`);
  const data = (await res.json()) as Partial<ModelsResponse>;
  return {
    models: data.models ?? [],
    token_usage: data.token_usage ?? { enabled: false },
  };
}
