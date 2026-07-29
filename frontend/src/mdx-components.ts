import { useMDXComponents as getThemeComponents } from "nextra-theme-docs";

import { LocalizedCards } from "@/components/docs/localized-cards";
import { LocalizedDocsLink } from "@/components/docs/localized-mdx-components";

// 保留主题默认组件，只覆盖需要本地化路由行为的元素。
const themeComponents = getThemeComponents();

/** 合并 Nextra 默认 MDX 组件与 DeerFlow 的本地化链接、卡片实现。 */
export function useMDXComponents() {
  return {
    ...themeComponents,
    a: LocalizedDocsLink,
    Cards: LocalizedCards,
  };
}
