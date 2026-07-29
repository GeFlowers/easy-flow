/**
 * 界面展示的应用版本。优先采用构建期 `NEXT_PUBLIC_APP_VERSION`；夜间 CI 使用
 * `<base>-nightly.<YYYYMMDD>-<short_sha>`。本地开发和标签发布回退到
 * package.json，版本一致性由发布校验脚本保证。
 */
import pkg from "../package.json";

// 此处刻意使用 `||`：Dockerfile 会把发布/本地构建变量设为空字符串，该值必须像
// 未设置一样回退；`??` 会错误保留空字符串。
// eslint-disable-next-line @typescript-eslint/prefer-nullish-coalescing
export const APP_VERSION = process.env.NEXT_PUBLIC_APP_VERSION || pkg.version;
