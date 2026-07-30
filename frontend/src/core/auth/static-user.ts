import type { User } from "./types";

/** 静态网站演示模式下使用的管理员用户。 */
export const STATIC_WEBSITE_USER: User = {
  id: "static-website-user",
  email: "static@example.local",
  system_role: "admin",
  needs_setup: false,
  oauth_provider: null,
};
