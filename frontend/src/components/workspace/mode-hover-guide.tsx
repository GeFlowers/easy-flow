"use client";

import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";

import { Tooltip } from "./tooltip";

export type AgentMode = "flash" | "thinking" | "pro" | "ultra";

/** 把模式标识映射到本地化标签键，供输入框显示当前模式名称。 */
function getModeLabelKey(
  mode: AgentMode,
): keyof Pick<
  Translations["inputBox"],
  "flashMode" | "reasoningMode" | "proMode" | "ultraMode"
> {
  switch (mode) {
    case "flash":
      return "flashMode";
    case "thinking":
      return "reasoningMode";
    case "pro":
      return "proMode";
    case "ultra":
      return "ultraMode";
  }
}

/** 把模式标识映射到对应的本地化说明键，避免界面散落条件判断。 */
function getModeDescriptionKey(
  mode: AgentMode,
): keyof Pick<
  Translations["inputBox"],
  | "flashModeDescription"
  | "reasoningModeDescription"
  | "proModeDescription"
  | "ultraModeDescription"
> {
  switch (mode) {
    case "flash":
      return "flashModeDescription";
    case "thinking":
      return "reasoningModeDescription";
    case "pro":
      return "proModeDescription";
    case "ultra":
      return "ultraModeDescription";
  }
}

/** 为代理模式提供悬停说明，兼顾图标化控件的可发现性与读屏标签。 */
export function ModeHoverGuide({
  mode,
  children,
  showTitle = true,
}: {
  mode: AgentMode;
  children: React.ReactNode;
  /** 为 true 时提示显示“模式名：说明”；否则仅显示说明，避免在紧凑界面重复模式名。 */
  showTitle?: boolean;
}) {
  const { t } = useI18n();
  const label = t.inputBox[getModeLabelKey(mode)];
  const description = t.inputBox[getModeDescriptionKey(mode)];
  const content = showTitle ? `${label}: ${description}` : description;

  return <Tooltip content={content}>{children}</Tooltip>;
}
