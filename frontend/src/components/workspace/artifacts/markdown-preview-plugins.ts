import rehypeSlug from "rehype-slug";

import { type ClipboardSafeStreamdownProps } from "@/components/ai-elements/streamdown";
import { streamdownPlugins } from "@/core/streamdown";

const baseRehypePlugins = streamdownPlugins.rehypePlugins ?? [];

/** 集中声明产物 Markdown 预览所需插件，保证预览与消息渲染的能力边界可追踪。 */
export const artifactMarkdownPlugins = {
  ...streamdownPlugins,
  rehypePlugins: [
    ...baseRehypePlugins.slice(0, 1),
    rehypeSlug,
    ...baseRehypePlugins.slice(1),
  ] as ClipboardSafeStreamdownProps["rehypePlugins"],
};
