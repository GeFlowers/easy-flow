/**
 * 解析仅供服务端代理使用的内部地址，并去除尾部斜杠以稳定拼接规则。
 */
function getInternalServiceURL(envKey, fallbackURL) {
  const configured = process.env[envKey]?.trim();
  return configured && configured.length > 0
    ? configured.replace(/\/+$/, "")
    : fallbackURL;
}
/** 前端框架配置的类型提示。
 * @type {import("next").NextConfig}
 */
const config = {
  devIndicators: false,
  // 本机同时运行数据库和后端时限制构建并发，避免一次生成大量构建进程。
  experimental: { cpus: 2 },
  /**
   * 建立同源代理，统一请求和流式连接的访问边界。
   */
  async rewrites() {
    const rewrites = [];
    const gatewayURL = getInternalServiceURL(
      "DEER_FLOW_INTERNAL_GATEWAY_BASE_URL",
      "http://127.0.0.1:8001",
    );

    rewrites.push({
      source: "/api/langgraph",
      destination: `${gatewayURL}/api`,
    });
    rewrites.push({
      source: "/api/langgraph/:path*",
      destination: `${gatewayURL}/api/:path*`,
    });
    rewrites.push({
      source: "/api/agents",
      destination: `${gatewayURL}/api/agents`,
    });
    rewrites.push({
      source: "/api/agents/:path*",
      destination: `${gatewayURL}/api/agents/:path*`,
    });
    rewrites.push({
      source: "/api/skills",
      destination: `${gatewayURL}/api/skills`,
    });
    rewrites.push({
      source: "/api/skills/:path*",
      destination: `${gatewayURL}/api/skills/:path*`,
    });

    // 兜底规则必须位于 /api/langgraph 之后，否则会提前吞掉兼容前缀，导致 Gateway
    // 无法收到改写后的原生 /api/* 路径。
    rewrites.push({
      source: "/api/:path*",
      destination: `${gatewayURL}/api/:path*`,
    });
    return rewrites;
  },
};

export default config;
