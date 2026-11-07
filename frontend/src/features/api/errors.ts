/**
 * 根据失败的 Gateway REST 响应抛出异常。
 *
 * 解析 FastAPI 错误信封（`{ detail: string }`）；当响应体缺失或不符合该形状时，
 * 回退使用调用方提供的消息。频道、定时任务等领域 API 模块共用此函数，确保错误信封
 * 格式只在一处解释。
 */
export async function throwGatewayApiError(
  response: Response,
  fallback: string,
): Promise<never> {
  const body = (await response.json().catch(() => ({}))) as {
    detail?: unknown;
  };
  throw new Error(typeof body.detail === "string" ? body.detail : fallback);
}
