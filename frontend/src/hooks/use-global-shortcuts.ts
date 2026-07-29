"use client";

import { useEffect } from "react";

type ShortcutAction = () => void;

interface Shortcut {
  key: string;
  meta: boolean;
  shift?: boolean;
  action: ShortcutAction;
}

/**
 * 在 window 上注册全局快捷键。焦点位于输入控件时抑制普通快捷键，但保留
 * Cmd/Ctrl+K，以符合命令面板的通用交互习惯。
 */
export function useGlobalShortcuts(shortcuts: Shortcut[]) {
  useEffect(() => {
    /** 规范化平台修饰键并执行首个精确匹配的快捷键。 */
    function handleKeyDown(event: KeyboardEvent) {
      if (typeof event.key !== "string" || event.key.length === 0) {
        return;
      }

      const meta = event.metaKey || event.ctrlKey;
      const eventKey = event.key.toLowerCase();

      for (const shortcut of shortcuts) {
        const shortcutKey = shortcut.key.toLowerCase();
        if (
          eventKey === shortcutKey &&
          meta === shortcut.meta &&
          (shortcut.shift ?? false) === event.shiftKey
        ) {
          // 命令面板快捷键在输入框内仍应可用，其他快捷键不得打断文本编辑。
          if (shortcutKey !== "k") {
            const target = event.target as HTMLElement;
            const tag = target.tagName;
            if (
              tag === "INPUT" ||
              tag === "TEXTAREA" ||
              target.isContentEditable
            ) {
              continue;
            }
          }

          event.preventDefault();
          shortcut.action();
          return;
        }
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [shortcuts]);
}
