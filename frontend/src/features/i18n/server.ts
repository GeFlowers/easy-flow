import { cookies } from "next/headers";

import { DEFAULT_LOCALE, normalizeLocale, type Locale } from "./locale";
import { translations } from "./translations";

/** 从服务端请求 Cookie 读取语言偏好，并规范化为项目支持的语言。 */
export async function detectLocaleServer(): Promise<Locale> {
  const cookieStore = await cookies();
  let locale = cookieStore.get("locale")?.value;
  if (locale !== undefined) {
    try {
      locale = decodeURIComponent(locale);
    } catch {
      // 解码失败时保留原始 Cookie 值。
    }
  }

  return normalizeLocale(locale);
}

/** 规范化语言标识并写入服务端响应 Cookie，供后续请求复用。 */
export async function setLocale(locale: string | Locale): Promise<Locale> {
  const normalizedLocale = normalizeLocale(locale);
  const cookieStore = await cookies();
  cookieStore.set("locale", encodeURIComponent(normalizedLocale), {
    maxAge: 365 * 24 * 60 * 60,
    path: "/",
    sameSite: "lax",
  });

  return normalizedLocale;
}

/** 使用显式语言或请求 Cookie 选择翻译表，并返回语言与翻译对象。 */
export async function getI18n(localeOverride?: string | Locale) {
  const locale = localeOverride
    ? normalizeLocale(localeOverride)
    : await detectLocaleServer();
  const t = translations[locale] ?? translations[DEFAULT_LOCALE];
  return {
    locale,
    t,
  };
}
