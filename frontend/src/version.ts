/**
 * 界面展示的学习版版本号；构建时可覆盖，未指定时采用 package.json。
 */
import pkg from "../package.json";

// 此处刻意使用 `||`：Dockerfile 会把发布/本地构建变量设为空字符串，该值必须像
// 未设置一样回退；`??` 会错误保留空字符串。
// eslint-disable-next-line @typescript-eslint/prefer-nullish-coalescing
export const APP_VERSION = process.env.NEXT_PUBLIC_APP_VERSION || pkg.version;
