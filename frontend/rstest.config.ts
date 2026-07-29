/** 配置基于 Rsbuild 的前端单元测试编译与依赖打包。 */
import { resolve } from "path";

import { pluginReact } from "@rsbuild/plugin-react";
import { defineConfig } from "@rstest/core";

export default defineConfig({
  plugins: [pluginReact()],
  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
  output: {
    // Streamdown 以副作用方式导入 KaTeX CSS，必须打包依赖交给 Rsbuild 处理，不能
    // 让 Node 直接尝试加载样式文件。
    bundleDependencies: ["streamdown", "katex"],
  },
  include: ["tests/unit/**/*.test.ts"],
});
