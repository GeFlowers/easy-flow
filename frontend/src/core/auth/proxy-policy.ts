/** LangGraph 兼容代理的路径、请求头、凭据、超时与 CSRF 策略。 */
export interface ProxyPolicy {
  /** 允许转发至上游的路径前缀。 */
  readonly allowedPaths: readonly string[];
  /** 转发前必须剥离的请求头。 */
  readonly strippedRequestHeaders: ReadonlySet<string>;
  /** 返回客户端前必须剥离的响应头。 */
  readonly strippedResponseHeaders: ReadonlySet<string>;
  /** 凭据模式：需要转发的 Cookie。 */
  readonly credential: { readonly type: "cookie"; readonly name: string };
  /** 超时时间，单位为毫秒。 */
  readonly timeoutMs: number;
  /** CSRF：非 GET/HEAD 请求是否必须校验。 */
  readonly csrf: boolean;
}

/** LangGraph 兼容代理的生产默认安全策略。 */
export const LANGGRAPH_COMPAT_POLICY: ProxyPolicy = {
  allowedPaths: [
    "threads",
    "runs",
    "assistants",
    "store",
    "models",
    "mcp",
    "skills",
    "memory",
  ],
  strippedRequestHeaders: new Set([
    "host",
    "connection",
    "keep-alive",
    "transfer-encoding",
    "te",
    "trailer",
    "upgrade",
    "authorization",
    "x-api-key",
    "origin",
    "referer",
    "proxy-authorization",
    "proxy-authenticate",
  ]),
  strippedResponseHeaders: new Set([
    "connection",
    "keep-alive",
    "transfer-encoding",
    "te",
    "trailer",
    "upgrade",
    "content-length",
    "set-cookie",
  ]),
  credential: { type: "cookie", name: "access_token" },
  timeoutMs: 120_000,
  csrf: true,
};
