import { useState, useEffect, useCallback, useRef } from "react";

import { useLocalSettings } from "../settings";

/** 浏览器通知创建时可传入的选项。 */
interface NotificationOptions {
  body?: string;
  icon?: string;
  badge?: string;
  tag?: string;
  data?: unknown;
  requireInteraction?: boolean;
  silent?: boolean;
}

/** 通知钩子向调用方提供的状态和操作。 */
interface UseNotificationReturn {
  permission: NotificationPermission;
  isSupported: boolean;
  requestPermission: () => Promise<NotificationPermission>;
  showNotification: (title: string, options?: NotificationOptions) => void;
}

/** 提供浏览器通知权限状态与发送能力。 */
export function useNotification(): UseNotificationReturn {
  const [permission, setPermission] =
    useState<NotificationPermission>("default");
  const [isSupported, setIsSupported] = useState(false);

  const lastNotificationTime = useRef<number | null>(null);

  useEffect(() => {
    // 检查浏览器是否支持通知接口。
    if ("Notification" in window) {
      setIsSupported(true);
      setPermission(Notification.permission);
    }
  }, []);

  /** 请求浏览器通知权限并同步权限结果到 Hook 状态。 */
  const requestPermission =
    useCallback(async (): Promise<NotificationPermission> => {
      if (!isSupported) {
        console.warn("Notification API is not supported in this browser");
        return "denied";
      }

      const result = await Notification.requestPermission();
      setPermission(result);
      return result;
    }, [isSupported]);

  const [settings] = useLocalSettings();

  /** 在功能受支持、已启用且获准时展示通知，并执行频率限制。 */
  const showNotification = useCallback(
    (title: string, options?: NotificationOptions) => {
      if (!isSupported) {
        console.warn("Notification API is not supported");
        return;
      }

      if (!settings.notification.enabled) {
        console.warn("Notification is disabled");
        return;
      }

      const currentPermission = Notification.permission;
      if (currentPermission !== permission) {
        setPermission(currentPermission);
      }

      if (currentPermission !== "granted") {
        console.warn("Notification permission not granted");
        return;
      }

      const now = Date.now();
      if (
        lastNotificationTime.current !== null &&
        now - lastNotificationTime.current < 1000
      ) {
        console.warn("Notification sent too soon");
        return;
      }
      lastNotificationTime.current = now;

      const notification = new Notification(title, options);

      // 注册点击和错误事件处理器。
      notification.onclick = () => {
        window.focus();
        notification.close();
      };

      notification.onerror = (error) => {
        console.error("Notification error:", error);
      };
    },
    [isSupported, settings.notification.enabled, permission],
  );

  return {
    permission,
    isSupported,
    requestPermission,
    showNotification,
  };
}
