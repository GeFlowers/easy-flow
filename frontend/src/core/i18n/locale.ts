export const SUPPORTED_LOCALES = ["en-US", "zh-CN"] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "en-US";

/** 判断 isLocale 所表达的条件是否成立。 */
export function isLocale(value: string): value is Locale {
  return (SUPPORTED_LOCALES as readonly string[]).includes(value);
}

/** 获取 getLocaleByLang 所需的结果或配置。 */
export function getLocaleByLang(lang: string): Locale {
  const normalizedLang = lang.toLowerCase();
  for (const locale of SUPPORTED_LOCALES) {
    if (locale.startsWith(normalizedLang)) {
      return locale;
    }
  }
  return DEFAULT_LOCALE;
}

/** 获取 getLangByLocale 所需的结果或配置。 */
export function getLangByLocale(locale: Locale): string {
  const parts = locale.split("-");
  if (parts.length > 0 && typeof parts[0] === "string") {
    return parts[0];
  }
  return locale;
}

/** 将输入规范化为 normalizeLocale 所需的形式。 */
export function normalizeLocale(locale: string | null | undefined): Locale {
  if (!locale) {
    return DEFAULT_LOCALE;
  }

  if (isLocale(locale)) {
    return locale;
  }

  if (locale.toLowerCase().startsWith("zh")) {
    return "zh-CN";
  }

  return DEFAULT_LOCALE;
}

// 用于检测浏览器语言区域的辅助函数。
/** 实现 detectLocale 的受限辅助逻辑。 */
export function detectLocale(): Locale {
  if (typeof window === "undefined") {
    return DEFAULT_LOCALE;
  }

  const browserLang =
    navigator.language ||
    (navigator as unknown as { userLanguage: string }).userLanguage;

  return normalizeLocale(browserLang);
}
