/** 后端请求通过当前站点同源代理发送。 */
export function getBackendBaseURL() {
  return "";
}

/** 解析 LangGraph SDK 的完整基础地址，并处理服务端渲染回退。 */
export function getLangGraphBaseURL() {
  if (typeof window !== "undefined") {
    return `${window.location.origin}/api/langgraph`;
  }
  return "http://localhost:2026/api/langgraph";
}
