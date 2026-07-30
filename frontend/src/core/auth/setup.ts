import { parseAuthError } from "./types";

/** 后端初始化状态接口的响应数据。 */
export type SetupStatusResponse = {
  needs_setup?: boolean;
};

/** 初始化状态查询是否完成及其结果。 */
export type SetupStatusCheck = {
  checked: boolean;
  status: SetupStatusResponse | null;
};

/** 查询初始化状态时禁用缓存并携带会话凭据的请求配置。 */
export const setupStatusFetchInit = {
  cache: "no-store",
  credentials: "include",
} satisfies RequestInit;

/** 从服务端查询系统初始化状态。 */
export async function fetchSetupStatus(): Promise<SetupStatusResponse> {
  const response = await fetch(
    "/api/v1/auth/setup-status",
    setupStatusFetchInit,
  );
  if (!response.ok) {
    throw new Error(`setup-status failed: ${response.status}`);
  }
  return (await response.json()) as SetupStatusResponse;
}

/** 判断未知错误响应是否表示系统已经完成初始化。 */
export function isSystemAlreadyInitializedError(data: unknown): boolean {
  return parseAuthError(data).code === "system_already_initialized";
}

/** 判断状态检查完成后是否允许创建普通账号。 */
export function canCreateRegularAccount(check: SetupStatusCheck): boolean {
  return check.checked && check.status?.needs_setup !== true;
}
