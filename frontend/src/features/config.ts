/** 浏览器使用同源路径，由 Nginx 转发后端请求。 */
export function getBackendBaseURL() {
  return "";
}

/** 对话客户端使用站点同源的后端接口基础地址。 */
export function getAPIBaseURL() {
  const origin =
    typeof window === "undefined"
      ? "http://localhost:2026"
      : window.location.origin;
  return `${origin}/api`;
}
