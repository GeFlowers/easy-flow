---
name: vercel-deploy
description: 将应用和网站部署到 Vercel。用户要求“部署我的应用”、“部署到生产环境”、“创建预览部署”、“部署并给我链接”或“上线”时使用。无需身份验证，返回预览地址和可认领的部署链接。
metadata:
  author: vercel
  version: "1.0.0"
---

# Vercel 部署

立即将任意项目部署到 Vercel，无需身份验证。

## 工作方式

1. 将项目打包为归档文件，排除 `node_modules` 和 `.git`。
2. 根据 `package.json` 自动识别框架。
3. 上传至部署服务。
4. 返回**预览地址**（在线网站）与**认领地址**（转移到你的 Vercel 账户）。

## 用法

```bash
bash /mnt/skills/user/vercel-deploy/scripts/deploy.sh [path]
```

**参数：**

- `path`：待部署目录或 `.tgz` 文件，默认当前目录。

**示例：**

```bash
# 部署当前目录
bash /mnt/skills/user/vercel-deploy/scripts/deploy.sh

# 部署指定项目
bash /mnt/skills/user/vercel-deploy/scripts/deploy.sh /path/to/project

# 部署已有归档文件
bash /mnt/skills/user/vercel-deploy/scripts/deploy.sh /path/to/project.tgz
```

## 输出

```
正在准备部署……
检测到框架：nextjs
正在创建部署包……
正在部署……
✓ 部署成功！

预览地址：https://skill-deploy-abc123.vercel.app
认领地址：https://vercel.com/claim-deployment?code=...
```

脚本也会向标准输出写出 JSON（JavaScript Object Notation，JavaScript 对象表示法），供程序使用：

```json
{
  "previewUrl": "https://skill-deploy-abc123.vercel.app",
  "claimUrl": "https://vercel.com/claim-deployment?code=...",
  "deploymentId": "dpl_...",
  "projectId": "prj_..."
}
```

## 框架检测

脚本根据 `package.json` 自动识别框架，支持：

- **React：** Next.js、Gatsby、Create React App、Remix、React Router。
- **Vue：** Nuxt、Vitepress、Vuepress、Gridsome。
- **Svelte：** SvelteKit、Svelte、Sapper。
- **其他前端：** Astro、Solid Start、Angular、Ember、Preact、Docusaurus。
- **后端：** Express、Hono、Fastify、NestJS、Elysia、h3、Nitro。
- **构建工具：** Vite、Parcel。
- **更多：** Blitz、Hydrogen、RedwoodJS、Storybook、Sanity 等。

静态 HTML（HyperText Markup Language，超文本标记语言）项目没有 `package.json`，框架设置为 `null`。

## 静态网页项目

对于没有 `package.json` 的项目：

- 如果只有一个 `.html` 文件且不叫 `index.html`，自动将其重命名。
- 这样页面即可通过根路径 `/` 访问。

## 向用户展示结果

始终展示两个地址：

```
✓ 部署成功！

- [预览地址](https://skill-deploy-abc123.vercel.app)
- [认领地址](https://vercel.com/claim-deployment?code=...)

访问预览地址查看网站。
如需将此次部署转移到你的 Vercel 账户，请访问认领地址。
```

## 排错

### 网络出站错误

如果因为网络限制部署失败（claude.ai 上较常见），告知用户：

```
由于网络限制，部署失败。请按以下方式处理：

1. 访问 https://claude.ai/settings/capabilities
2. 将 *.vercel.com 添加到允许的域名
3. 再次尝试部署
```
