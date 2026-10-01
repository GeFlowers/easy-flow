export const SUPPORTED_LOCALES = ["en-US", "zh-CN"] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "en-US";

/** 判断给定语言标识是否属于当前构建支持的语言集合。 */
export function isLocale(value: string): value is Locale {
  return (SUPPORTED_LOCALES as readonly string[]).includes(value);
}

/** 根据浏览器语言前缀选择项目支持的语言，未匹配时使用默认语言。 */
export function getLocaleByLang(lang: string): Locale {
  const normalizedLang = lang.toLowerCase();
  for (const locale of SUPPORTED_LOCALES) {
    if (locale.startsWith(normalizedLang)) {
      return locale;
    }
  }
  return DEFAULT_LOCALE;
}

/** 提取语言区域标识中的基础语言代码，供浏览器偏好判断使用。 */
export function getLangByLocale(locale: Locale): string {
  const parts = locale.split("-");
  if (parts.length > 0 && typeof parts[0] === "string") {
    return parts[0];
  }
  return locale;
}

/** 将缺失或不支持的语言值归一化为当前项目支持的语言。 */
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
/** 在浏览器中读取首选语言并归一化；服务端渲染时回退到默认语言。 */
export function detectLocale(): Locale {
  if (typeof window === "undefined") {
    return DEFAULT_LOCALE;
  }

  const browserLang =
    navigator.language ||
    (navigator as unknown as { userLanguage: string }).userLanguage;

  return normalizeLocale(browserLang);
}
