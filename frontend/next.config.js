/** 前端框架配置的类型提示。
 * @type {import("next").NextConfig}
 */
const config = {
  devIndicators: false,
  // 本机同时运行数据库和后端时限制构建并发，避免一次生成大量构建进程。
  experimental: { cpus: 2 },
  async redirects() {
    return [{ source: "/setup", destination: "/login", permanent: false }];
  },
};

export default config;
