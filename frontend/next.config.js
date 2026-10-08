/**
 * 导入环境变量模式，使构建和开发启动在加载 Next.js 配置时即完成校验。
 * Docker 构建可通过 `SKIP_ENV_VALIDATION` 显式跳过该步骤。
 */
import "./src/env.js";

/**
 * 解析仅供服务端代理使用的内部地址，并去除尾部斜杠以稳定拼接规则。
 */
function getInternalServiceURL(envKey, fallbackURL) {
  const configured = process.env[envKey]?.trim();
  return configured && configured.length > 0
    ? configured.replace(/\/+$/, "")
    : fallbackURL;
}
import nextra from "nextra";

const withNextra = nextra({});

/** 前端框架配置的类型提示。
 * @type {import("next").NextConfig}
 */
const config = {
  i18n: {
    locales: ["en", "zh"],
    defaultLocale: "en",
  },
  devIndicators: false,
  /**
   * 在未指定浏览器直连地址时建立同源代理，统一 Cookie、CSRF 与流式请求边界。
   */
  async rewrites() {
    const rewrites = [];
    const gatewayURL = getInternalServiceURL(
      "DEER_FLOW_INTERNAL_GATEWAY_BASE_URL",
      "http://127.0.0.1:8001",
    );

    if (!process.env.NEXT_PUBLIC_LANGGRAPH_BASE_URL) {
      rewrites.push({
        source: "/api/langgraph",
        destination: `${gatewayURL}/api`,
      });
      rewrites.push({
        source: "/api/langgraph/:path*",
        destination: `${gatewayURL}/api/:path*`,
      });
    }

    if (!process.env.NEXT_PUBLIC_BACKEND_BASE_URL) {
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
    }

    return rewrites;
  },
};

export default withNextra(config);
