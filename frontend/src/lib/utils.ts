import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** 合并条件类名，并按 Tailwind 冲突规则保留最终生效的工具类。 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** 默认带下划线的外部链接公共样式。 */
export const externalLinkClass =
  "text-primary underline underline-offset-2 hover:no-underline";
/** 默认不带下划线、悬停时强调的链接样式，适合流式或加载状态。 */
export const externalLinkClassNoUnderline = "text-primary hover:underline";
