import { useMemo } from "react";
import type { ComponentProps } from "react";
import { type Streamdown } from "streamdown";

import {
  capMarkdownNesting,
  normalizeStreamdownMathMarkdown,
} from "./preprocess";

type StreamdownChildren = ComponentProps<typeof Streamdown>["children"];

/** 预处理标记文本，确保流式渲染组件子节点可安全渲染。 */
export function getSafeStreamdownMarkdown(markdown: string): string {
  return normalizeStreamdownMathMarkdown(capMarkdownNesting(markdown));
}

/** 将安全的标记文本转换为流式渲染组件所需的子节点。 */
export function getSafeStreamdownChildren(
  children: StreamdownChildren,
): StreamdownChildren {
  if (typeof children !== "string") {
    return children;
  }

  return getSafeStreamdownMarkdown(children);
}

/** 记忆化计算可安全传给流式渲染组件的子节点。 */
export function useSafeStreamdownChildren(
  children: StreamdownChildren,
): StreamdownChildren {
  return useMemo(() => getSafeStreamdownChildren(children), [children]);
}

/** 记忆化预处理可安全渲染的标记文本。 */
export function useSafeStreamdownMarkdown(markdown: string): string {
  return useMemo(() => getSafeStreamdownMarkdown(markdown), [markdown]);
}
