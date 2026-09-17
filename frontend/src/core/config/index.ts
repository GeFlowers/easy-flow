import { env } from "@/env";

/** 获取当前浏览器源；服务端渲染时使用本地开发源作为回退。 */
function getBaseOrigin() {
  if (typeof window !== "undefined") {
    return window.location.origin;
  }
  // 服务端渲染期间没有浏览器位置对象，使用稳定回退值。
  return "http://localhost:3000";
}

/** 解析配置的后端基础地址；未配置时保留相对请求路径。 */
export function getBackendBaseURL() {
  if (env.NEXT_PUBLIC_BACKEND_BASE_URL) {
    return new URL(env.NEXT_PUBLIC_BACKEND_BASE_URL, getBaseOrigin())
      .toString()
      .replace(/\/+$/, "");
  } else {
    return "";
  }
}

/** 解析 LangGraph SDK 的完整基础地址，并处理模拟与服务端渲染回退。 */
export function getLangGraphBaseURL(isMock?: boolean) {
  console.log(
    "env.NEXT_PUBLIC_LANGGRAPH_BASE_URL",
    env.NEXT_PUBLIC_LANGGRAPH_BASE_URL,
  );
  if (env.NEXT_PUBLIC_LANGGRAPH_BASE_URL) {
    return new URL(
      env.NEXT_PUBLIC_LANGGRAPH_BASE_URL,
      getBaseOrigin(),
    ).toString();
  } else if (isMock) {
    if (typeof window !== "undefined") {
      return `${window.location.origin}/mock/api`;
    }
    return "http://localhost:3000/mock/api";
  } else {
    // 所用客户端开发工具包要求完整地址，因此基于当前源拼接默认接口地址。
    if (typeof window !== "undefined") {
      return `${window.location.origin}/api/langgraph`;
    }
    // 服务端渲染时使用稳定的默认地址。
    return "http://localhost:3000/api/langgraph";
  }
}
