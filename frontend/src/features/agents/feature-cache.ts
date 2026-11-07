// 持久化 agents_api 功能开关最后一次确认的值。
// /api/features 按设计采用故障开放，避免服务故障隐藏本可用的功能。相应风险是，
// 当功能实际被禁用且接口不可用时，故障开放会重新挂载智能体 UI 并重现 403 风暴
// （#3757）。持久化最后的确定结果可让冷启动在故障时回退至该值。

const AGENTS_API_ENABLED_KEY = "deerflow.features.agents_api";

/** 判断当前运行环境是否为浏览器。 */
function isBrowser(): boolean {
  return typeof window !== "undefined";
}

/** 返回从 /api/features 获取的最后一个确定值；尚未获取时返回 undefined。 */
export function readCachedAgentsApiEnabled(): boolean | undefined {
  if (!isBrowser()) {
    return undefined;
  }
  try {
    const raw = window.localStorage.getItem(AGENTS_API_ENABLED_KEY);
    if (raw === "true") return true;
    if (raw === "false") return false;
  } catch {}
  return undefined;
}

/** 将确定的智能体 API 开关值写入本地缓存。 */
export function writeCachedAgentsApiEnabled(value: boolean): void {
  if (!isBrowser()) {
    return;
  }
  try {
    window.localStorage.setItem(AGENTS_API_ENABLED_KEY, String(value));
  } catch {}
}

/**
 * 由实时查询值和最后一次缓存值归并出有效开关：实时值优先；否则使用最近成功
 * 获取的粘滞缓存，防止短暂故障重新启用已禁用功能；仅从未获得确定值时故障开放。
 */
export function resolveAgentsApiEnabled(
  live: boolean | undefined,
  cached: boolean | undefined,
): boolean {
  return live ?? cached ?? true;
}
