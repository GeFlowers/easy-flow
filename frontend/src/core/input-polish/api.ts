import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

/** 输入润色接口接受的草稿、区域设置和可选线程标识。 */
export type InputPolishRequest = {
  text: string;
  locale?: string;
  thread_id?: string;
};

/** 输入润色接口返回的改写结果与变更标记。 */
export type InputPolishResponse = {
  rewritten_text: string;
  changed: boolean;
};

/** 调用输入润色接口，并支持通过 AbortSignal 取消请求。 */
export async function polishInputDraft(
  request: InputPolishRequest,
  options?: { signal?: AbortSignal },
): Promise<InputPolishResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/input-polish`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal: options?.signal,
  });

  if (!response.ok) {
    await throwGatewayApiError(response, "Failed to polish input");
  }

  return response.json() as Promise<InputPolishResponse>;
}
