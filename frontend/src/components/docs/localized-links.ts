const SUPPORTED_DOC_LANGUAGES = new Set(["en", "zh"]);
const UNLOCALIZED_DOCS_PATH = /^\/docs(?=\/|[?#]|$)/;

/** 为文档链接补齐当前语言环境的路径前缀。 */
export function localizeDocsHref(
  href: string,
  lang: string | undefined,
): string {
  if (!lang || !SUPPORTED_DOC_LANGUAGES.has(lang)) {
    return href;
  }
  if (!UNLOCALIZED_DOCS_PATH.test(href)) {
    return href;
  }
  return `/${lang}${href}`;
}
