import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import type { StreamdownProps } from "streamdown";

import { rehypeSplitWordsIntoSpans } from "../rehype";

const katexOptions = {
  output: "html",
  throwOnError: false,
  strict: false,
} as const;

/** 标准消息内容渲染所需的流式渲染组件插件配置。 */
export const streamdownPlugins = {
  remarkPlugins: [
    remarkGfm,
    [remarkMath, { singleDollarTextMath: true }],
  ] as StreamdownProps["remarkPlugins"],
  rehypePlugins: [
    rehypeRaw,
    [rehypeKatex, katexOptions],
  ] as StreamdownProps["rehypePlugins"],
};

/** 额外启用词语动画的流式渲染组件插件配置。 */
export const streamdownPluginsWithWordAnimation = {
  remarkPlugins: [
    remarkGfm,
    [remarkMath, { singleDollarTextMath: true }],
  ] as StreamdownProps["remarkPlugins"],
  rehypePlugins: [
    [rehypeKatex, katexOptions],
    rehypeSplitWordsIntoSpans,
  ] as StreamdownProps["rehypePlugins"],
};

/** 禁止解析原始网页标记的流式渲染组件插件配置。 */
export const streamdownPluginsWithoutRawHtml = {
  remarkPlugins: streamdownPlugins.remarkPlugins,
  rehypePlugins: streamdownPlugins.rehypePlugins?.filter(
    (p) => p !== rehypeRaw,
  ) as StreamdownProps["rehypePlugins"],
};

// 推理／思考内容沿用基础插件，但不解析原始网页标记，防止模型臆造的标签被渲染为页面元素。
/** 推理／思考内容使用的安全插件配置。 */
export const reasoningPlugins = streamdownPluginsWithoutRawHtml;
