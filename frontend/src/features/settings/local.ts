import type { TokenUsageInlineMode } from "../messages/usage-model";
import type { AgentThreadContext } from "../threads";

/** 默认的浏览器本地设置。 */
export const DEFAULT_LOCAL_SETTINGS: LocalSettings = {
  notification: {
    enabled: true,
  },
  tokenUsage: {
    headerTotal: true,
    inlineMode: "per_turn",
  },
  context: {
    model_name: undefined,
    mode: undefined,
    reasoning_effort: undefined,
  },
};

/** 保存全部本地设置的浏览器存储键。 */
export const LOCAL_SETTINGS_KEY = "deerflow.local-settings";
/** 保存线程模型覆盖值所用浏览器存储键的前缀。 */
export const THREAD_MODEL_KEY_PREFIX = "deerflow.thread-model.";

/** 判断当前代码是否运行在浏览器环境。 */
function isBrowser(): boolean {
  return typeof window !== "undefined";
}

/** 定义浏览器本地持久化的用户设置结构。 */
export interface LocalSettings {
  notification: {
    enabled: boolean;
  };
  tokenUsage: {
    headerTotal: boolean;
    inlineMode: TokenUsageInlineMode;
  };
  context: Omit<
    AgentThreadContext,
    | "thread_id"
    | "is_plan_mode"
    | "thinking_enabled"
    | "subagent_enabled"
    | "model_name"
    | "reasoning_effort"
  > & {
    model_name?: string | undefined;
    mode: "flash" | "thinking" | "pro" | "ultra" | undefined;
    reasoning_effort?: "minimal" | "low" | "medium" | "high";
  };
}

/** 将不完整的本地设置与默认值合并为完整配置。 */
function mergeLocalSettings(settings?: Partial<LocalSettings>): LocalSettings {
  return {
    ...DEFAULT_LOCAL_SETTINGS,
    context: {
      ...DEFAULT_LOCAL_SETTINGS.context,
      ...settings?.context,
    },
    tokenUsage: {
      ...DEFAULT_LOCAL_SETTINGS.tokenUsage,
      ...settings?.tokenUsage,
    },
    notification: {
      ...DEFAULT_LOCAL_SETTINGS.notification,
      ...settings?.notification,
    },
  };
}

/** 构造线程模型覆盖项的本地存储键。 */
function getThreadModelStorageKey(threadId: string): string {
  return `${THREAD_MODEL_KEY_PREFIX}${threadId}`;
}

/** 读取指定线程保存的模型覆盖值。 */
export function getThreadModelName(threadId: string): string | undefined {
  if (!isBrowser()) {
    return undefined;
  }
  return localStorage.getItem(getThreadModelStorageKey(threadId)) ?? undefined;
}

/** 保存或清除指定线程的模型覆盖值。 */
export function saveThreadModelName(
  threadId: string,
  modelName: string | undefined,
) {
  if (!isBrowser()) {
    return;
  }
  const key = getThreadModelStorageKey(threadId);
  if (!modelName) {
    localStorage.removeItem(key);
    return;
  }
  localStorage.setItem(key, modelName);
}

/** 将线程模型覆盖值应用到基础本地设置。 */
export function applyThreadModelOverride(
  settings: LocalSettings,
  threadModelName: string | undefined,
): LocalSettings {
  if (!threadModelName) {
    return settings;
  }
  return {
    ...settings,
    context: {
      ...settings.context,
      model_name: threadModelName,
    },
  };
}

/** 从本地存储读取设置，并在缺失或异常时返回默认值。 */
export function getLocalSettings(): LocalSettings {
  if (!isBrowser()) {
    return DEFAULT_LOCAL_SETTINGS;
  }
  const json = localStorage.getItem(LOCAL_SETTINGS_KEY);
  try {
    if (json) {
      const settings = JSON.parse(json) as Partial<LocalSettings>;
      return mergeLocalSettings(settings);
    }
  } catch {}
  return DEFAULT_LOCAL_SETTINGS;
}

/** 将完整本地设置写入浏览器存储。 */
export function saveLocalSettings(settings: LocalSettings) {
  if (!isBrowser()) {
    return;
  }
  localStorage.setItem(LOCAL_SETTINGS_KEY, JSON.stringify(settings));
}
