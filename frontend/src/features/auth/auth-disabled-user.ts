import type { User } from "./types";

/** 仅在非生产环境显式关闭认证时使用的管理员用户。 */
export const AUTH_DISABLED_USER: User = {
  id: "default",
  email: "default@test.local",
  system_role: "admin",
  needs_setup: false,
  oauth_provider: null,
};

const PRODUCTION_ENV_VALUES = new Set(["prod", "production"]);

/** 判断环境变量是否明确标识当前为生产环境。 */
function isExplicitProductionEnvironment() {
  return ["DEER_FLOW_ENV", "ENVIRONMENT"].some((name) =>
    PRODUCTION_ENV_VALUES.has((process.env[name] ?? "").trim().toLowerCase()),
  );
}

/** 判断是否允许启用认证关闭模式；生产环境始终禁止该模式。 */
export function isAuthDisabledMode() {
  return (
    process.env.DEER_FLOW_AUTH_DISABLED === "1" &&
    !isExplicitProductionEnvironment()
  );
}
