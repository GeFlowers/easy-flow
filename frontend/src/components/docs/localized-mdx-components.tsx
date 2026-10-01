"use client";

import { useParams } from "next/navigation";
import { Anchor, Cards as NextraCards } from "nextra/components";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

import { localizeDocsHref } from "./localized-links";

const DOCS_LINK_CLASS_NAME =
  "x:text-primary-600 x:underline x:hover:no-underline x:decoration-from-font x:[text-underline-position:from-font]";

/** 从当前文档路由参数读取语言代码，供链接组件保持语言路径一致。 */
function useDocumentLanguage(): string | undefined {
  const { lang } = useParams<{ lang?: string }>();
  return lang;
}

/** 将文档内链接补齐当前语言前缀，同时保留原有锚点和链接属性。 */
export function LocalizedDocsLink({
  href,
  className,
  ...props
}: ComponentProps<typeof Anchor>) {
  const lang = useDocumentLanguage();
  const localizedHref =
    typeof href === "string" ? localizeDocsHref(href, lang) : href;

  return (
    <Anchor
      {...props}
      className={cn(DOCS_LINK_CLASS_NAME, className)}
      href={localizedHref}
    />
  );
}

/** 为文档卡片链接补齐当前语言路径，避免点击后离开本地化文档。 */
export function LocalizedCard({
  href,
  ...props
}: ComponentProps<typeof NextraCards.Card>) {
  const lang = useDocumentLanguage();
  return <NextraCards.Card {...props} href={localizeDocsHref(href, lang)} />;
}
