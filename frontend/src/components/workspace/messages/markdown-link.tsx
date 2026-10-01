import type { AnchorHTMLAttributes } from "react";

import { resolveArtifactURL } from "@/core/artifacts/utils";
import { cn } from "@/lib/utils";

import { CitationLink } from "../citations/citation-link";

/** 识别外部 HTTP(S) 地址，以便为新窗口链接补充安全属性。 */
function isExternalUrl(href: string | undefined): boolean {
  return !!href && /^https?:\/\//.test(href);
}

/** 创建消息内容和通用 Markdown 共用的 `a` 渲染器；传入 `threadId` 时还会解析 `/mnt/` 产物链接，未传入时则沿用默认外链处理。 */
export function createMarkdownLinkComponent(threadId?: string) {
  return function MarkdownLink({
    href,
    ...props
  }: AnchorHTMLAttributes<HTMLAnchorElement>) {
    if (typeof props.children === "string") {
      const match = /^citation:(.+)$/.exec(props.children);
      if (match) {
        const [, text] = match;
        return (
          <CitationLink {...props} href={href}>
            {text}
          </CitationLink>
        );
      }
    }
    if (threadId && href?.startsWith("/mnt/")) {
      return (
        <a
          {...props}
          href={resolveArtifactURL(href, threadId)}
          target="_blank"
          rel="noopener noreferrer"
        />
      );
    }
    const { className, target, rel, ...rest } = props;
    const external = isExternalUrl(href);
    return (
      <a
        {...rest}
        href={href}
        className={cn(
          "text-primary decoration-primary/30 hover:decoration-primary/60 underline underline-offset-2 transition-colors",
          className,
        )}
        target={target ?? (external ? "_blank" : undefined)}
        rel={rel ?? (external ? "noopener noreferrer" : undefined)}
      />
    );
  };
}
