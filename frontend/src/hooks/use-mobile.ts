import * as React from "react";

const MOBILE_BREAKPOINT = 768;
const MOBILE_QUERY = `(max-width: ${MOBILE_BREAKPOINT - 1}px)`;

/** 订阅媒体查询变化，并返回与 useSyncExternalStore 匹配的清理函数。 */
function subscribe(callback: () => void) {
  const mql = window.matchMedia(MOBILE_QUERY);
  mql.addEventListener("change", callback);
  return () => mql.removeEventListener("change", callback);
}

/** 返回浏览器当前是否命中移动端媒体查询。 */
function getSnapshot() {
  return window.matchMedia(MOBILE_QUERY).matches;
}

/** 服务端固定采用桌面快照，避免访问 window 并保持水合结果稳定。 */
function getServerSnapshot() {
  return false;
}

/** 通过并发安全的外部存储订阅返回当前是否为移动端视口。 */
export function useIsMobile() {
  return React.useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
