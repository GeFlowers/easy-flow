import type { KeyboardEvent } from "react";

type IMEKeyboardEvent = KeyboardEvent<HTMLElement>;

/** 兼容 React 状态、原生事件及旧 keyCode，判断输入法组合输入是否仍在进行。 */
export function isIMEComposing(
  event: IMEKeyboardEvent,
  isComposing = false,
): boolean {
  return isComposing || event.nativeEvent.isComposing || event.keyCode === 229;
}
