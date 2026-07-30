import { env } from "@/env";

/** 判断当前构建是否只能展示静态网站内容。 */
export function isStaticWebsiteOnly() {
  return env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true";
}
