import type { ChannelConnection, ChannelProviderId } from "./types";

/** 频道连接状态轮询的默认间隔，单位为毫秒。 */
export const CONNECT_POLL_INTERVAL_MS = 2000;
// 后端遗漏或损坏 `expires_in` 时使用的绑定时长，确保非有限值不会造成无限轮询。
const DEFAULT_CONNECT_EXPIRES_S = 600;

/** 提供取消轮询任务的控制句柄。 */
export interface ConnectPollHandle {
  /** 取消尚未执行的轮询并阻止后续调度。 */
  cancel: () => void;
}

/** 描述连接状态轮询所需的提供商、时限和回调。 */
export interface ConnectPollOptions {
  provider: ChannelProviderId;
  expiresInSeconds: number;
  /** 获取最新连接列表；它是判断“已连接”的唯一事实来源。 */
  fetchConnections: () => Promise<ChannelConnection[]>;
  /** 提供商连接变为“已连接”时仅调用一次。 */
  onConnected: () => void;
  intervalMs?: number;
  now?: () => number;
}

/**
 * 轮询连接端点，直至指定提供商报告 `connected` 或绑定时限到期。返回的句柄可
 * 通过 `cancel()` 停止循环，用于合并重复连接请求和组件卸载清理。
 *
 * 仅轮询连接端点；绑定完成时由 `onConnected` 让调用方恰好刷新一次派生的
 * 提供商状态，无需在每个轮询周期同时请求两个端点。
 */
export function startConnectionPoll(
  options: ConnectPollOptions,
): ConnectPollHandle {
  const {
    provider,
    expiresInSeconds,
    fetchConnections,
    onConnected,
    intervalMs = CONNECT_POLL_INTERVAL_MS,
    now = Date.now,
  } = options;

  const expires =
    Number.isFinite(expiresInSeconds) && expiresInSeconds > 0
      ? expiresInSeconds
      : DEFAULT_CONNECT_EXPIRES_S;
  const deadline = now() + expires * 1000;

  let timer: ReturnType<typeof setTimeout> | undefined;
  let cancelled = false;

  const cancel = () => {
    cancelled = true;
    if (timer !== undefined) {
      clearTimeout(timer);
      timer = undefined;
    }
  };

  const schedule = () => {
    timer = setTimeout(() => {
      timer = undefined;
      if (cancelled) {
        return;
      }
      void fetchConnections()
        .then((connections) => {
          if (cancelled) {
            return;
          }
          const connected = connections.some(
            (item) => item.provider === provider && item.status === "connected",
          );
          if (connected) {
            onConnected();
            return;
          }
          if (now() < deadline) {
            schedule();
          }
        })
        .catch(() => {
          if (!cancelled && now() < deadline) {
            schedule();
          }
        });
    }, intervalMs);
  };

  schedule();
  return { cancel };
}
