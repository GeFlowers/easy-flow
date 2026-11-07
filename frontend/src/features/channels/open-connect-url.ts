/** 表示频道授权流程打开的窗口，未打开时为 `null`。 */
export type ChannelConnectWindow = Window | null;

/** 在打开授权窗口前复用并聚焦仍可用的现有窗口。 */
export function prepareConnectWindow(): ChannelConnectWindow {
  const opened = window.open("about:blank", "_blank");
  if (opened) {
    opened.opener = null;
  }
  return opened;
}

/** 在新窗口中打开连接授权地址，并返回窗口引用。 */
export function openConnectUrl(
  url: string,
  connectWindow: ChannelConnectWindow = prepareConnectWindow(),
) {
  if (connectWindow && !connectWindow.closed) {
    connectWindow.location.replace(url);
    return;
  }

  window.location.assign(url);
}

/** 安全关闭已打开的连接授权窗口。 */
export function closeConnectWindow(connectWindow: ChannelConnectWindow) {
  if (connectWindow && !connectWindow.closed) {
    connectWindow.close();
  }
}
