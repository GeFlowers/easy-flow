---
name: find-skills
description: 用户询问“如何做某事”、“找一个能做某事的技能”、“有没有可以……的技能”，或希望扩展能力时，帮助发现和安装智能体技能。当用户寻找可能已有可安装技能的功能时使用。
---

# 查找技能

此技能帮助你从开放智能体技能生态中发现并安装技能。

## 使用时机

用户有以下需求时使用：

- 询问“如何做某事”，且可能已有处理这一常见任务的技能。
- 说“找一个能做某事的技能”或“有没有相关技能”。
- 询问某种专门能力“你能做吗”。
- 希望扩展智能体能力。
- 希望搜索工具、模板或工作流程。
- 希望获得某个领域的帮助，例如设计、测试或部署。

## 技能命令行是什么？

技能 CLI（Command Line Interface，命令行界面）即 `npx skills`，是开放智能体技能生态的包管理器。技能是模块化包，通过专门知识、流程和工具扩展智能体能力。

**主要命令：**

- `npx skills find [query]`：交互搜索或按关键词搜索技能。
- `npx skills check`：检查技能更新。
- `npx skills update`：更新全部已安装技能。

**浏览技能：** https://skills.sh/

## 如何帮助用户查找技能

### 第 1 步：理解需求

用户请求帮助时，识别：

1. 领域，例如 React、测试、设计、部署。
2. 具体任务，例如编写测试、制作动画、审查合并请求。
3. 是否足够常见，可能已有技能。

### 第 2 步：搜索技能

使用相关查询执行搜索命令：

```bash
npx skills find [query]
```

例如：

- 用户问“如何加速 React 应用？” → `npx skills find react performance`。
- 用户问“能帮我审查合并请求吗？” → `npx skills find pr review`。
- 用户说“需要创建更新日志” → `npx skills find changelog`。

命令返回的结果类似：

```
安装命令：bash /path/to/skill/scripts/install-skill.sh vercel-labs/agent-skills@vercel-react-best-practices

vercel-labs/agent-skills@vercel-react-best-practices
└ https://skills.sh/vercel-labs/agent-skills/vercel-react-best-practices
```

### 第 3 步：展示选项

找到相关技能后，向用户提供：

1. 技能名称和用途。
2. 可运行的安装命令。
3. skills.sh 上的详情链接。

回复示例：

```
找到了一个可能有帮助的技能！“vercel-react-best-practices”提供
Vercel 工程团队的 React 和 Next.js 性能优化指南。

安装命令：
bash /path/to/skill/scripts/install-skill.sh vercel-labs/agent-skills@vercel-react-best-practices

了解更多：https://skills.sh/vercel-labs/agent-skills/vercel-react-best-practices
```

### 第 4 步：安装技能

用户希望继续时，使用 `install-skill.sh` 安装技能并自动链接到项目：

```bash
bash /path/to/skill/scripts/install-skill.sh <owner/repo@skill-name>
```

例如安装 `vercel-react-best-practices`：

```bash
bash /path/to/skill/scripts/install-skill.sh vercel-labs/agent-skills@vercel-react-best-practices
```

脚本会将技能全局安装到 `skills/custom/`。

## 常见技能类别

搜索时可考虑：

| 类别 | 查询示例 |
| --- | --- |
| 网页开发 | react, nextjs, typescript, css, tailwind |
| 测试 | testing, jest, playwright, e2e |
| 开发运维 | deploy, docker, kubernetes, ci-cd |
| 文档 | docs, readme, changelog, api-docs |
| 代码质量 | review, lint, refactor, best-practices |
| 设计 | ui, ux, design-system, accessibility |
| 效率 | workflow, automation, git |

## 高效搜索建议

1. **关键词具体：** “react testing”优于单独“testing”。
2. **尝试近义词：** “deploy”无结果时，试试“deployment”或“ci-cd”。
3. **检查热门来源：** 许多技能来自 `vercel-labs/agent-skills` 或 `ComposioHQ/awesome-claude-skills`。

## 没找到技能时

如果不存在相关技能：

1. 说明没有找到已有技能。
2. 提出使用通用能力直接帮助完成任务。
3. 建议用户通过 `npx skills init` 创建自己的技能。

示例：

```
搜索了与“xyz”有关的技能，但没有匹配结果。
我仍然可以直接帮助你完成任务！需要继续吗？

如果经常做这件事，可以创建自己的技能：
npx skills init my-xyz-skill
```
