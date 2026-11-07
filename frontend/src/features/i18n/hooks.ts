"use client";

import { useEffect } from "react";

import { useI18nContext } from "./context";
import { getLocaleFromCookie, setLocaleInCookie } from "./cookies";
import { translations } from "./translations";

import {
  DEFAULT_LOCALE,
  detectLocale,
  normalizeLocale,
  type Locale,
} from "./index";

/** 返回当前语言、翻译表和切换方法，并在挂载时恢复或检测语言偏好。 */
export function useI18n() {
  const { locale, setLocale } = useI18nContext();

  const t = translations[locale] ?? translations[DEFAULT_LOCALE];

  /** 同步更新上下文语言及 Cookie 中保存的语言设置。 */
  const changeLocale = (newLocale: Locale) => {
    setLocale(newLocale);
    setLocaleInCookie(newLocale);
  };

  // 组件挂载时再读取并初始化语言设置，避免服务端渲染阶段访问浏览器状态。
  useEffect(() => {
    const saved = getLocaleFromCookie();
    if (saved) {
      const normalizedSaved = normalizeLocale(saved);
      setLocale(normalizedSaved);
      if (saved !== normalizedSaved) {
        setLocaleInCookie(normalizedSaved);
      }
      return;
    }

    const detected = detectLocale();
    setLocale(detected);
    setLocaleInCookie(detected);
  }, [setLocale]);

  return {
    locale,
    t,
    changeLocale,
  };
}
