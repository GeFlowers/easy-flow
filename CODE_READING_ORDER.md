# DeerFlow 代码阅读顺序


> 本文档覆盖仓库内全部代码、测试、部署脚本和构建配置，并按照“用户可见功能 → 应用编排 → Agent 核心 → 底层基础设施 → 测试与工程化”的顺序阅读。

- 纳入文件：1458 个
- 编号分组：188 个
- 每个编号代表一个职责文件夹或关键单文件；组内仍逐一列出具体文件超链接。
- Markdown/MDX 说明文档、纯数据样例、图片、字体、锁文件和生成物不纳入；可执行演示页面、测试及 CI/构建配置纳入。

## 阅读方法

先读每组的“作用”和“阅读重点”，再按文件列表自上而下阅读。遇到接口调用时，优先沿后续阶段继续下钻，不必先读测试和工程脚本。

## 第一阶段：产品入口与用户可见功能

### 1. `Makefile`

- 作用：提供整个 monorepo 的统一安装、开发、启动、检查和 Docker 编排入口。
- 阅读重点：先了解一条命令如何拉起 Gateway、前端与 Nginx。
- 文件：
  - [`Makefile`](<Makefile>)

### 2. `frontend/src/app/layout.tsx`

- 作用：定义前端应用的全局布局、Provider 和页面外壳。
- 阅读重点：从这里确认所有页面共享的运行环境与样式入口。
- 文件：
  - [`frontend/src/app/layout.tsx`](<frontend/src/app/layout.tsx>)

### 3. `frontend/src/app/page.tsx`

- 作用：实现产品首页入口并把用户引导到主要工作区功能。
- 阅读重点：观察最上层用户入口如何连接到工作区。
- 文件：
  - [`frontend/src/app/page.tsx`](<frontend/src/app/page.tsx>)

### 4. `frontend/src/app/workspace`

- 作用：实现聊天、Agent、定时任务等工作区页面，是用户主要操作路径。
- 阅读重点：按页面路由追踪用户操作如何进入前端领域逻辑。
- 文件：
  - [`frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/layout.tsx`](<frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/layout.tsx>)
  - [`frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx`](<frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx>)
  - [`frontend/src/app/workspace/agents/layout.tsx`](<frontend/src/app/workspace/agents/layout.tsx>)
  - [`frontend/src/app/workspace/agents/new/page.tsx`](<frontend/src/app/workspace/agents/new/page.tsx>)
  - [`frontend/src/app/workspace/agents/page.tsx`](<frontend/src/app/workspace/agents/page.tsx>)
  - [`frontend/src/app/workspace/chats/[thread_id]/layout.tsx`](<frontend/src/app/workspace/chats/[thread_id]/layout.tsx>)
  - [`frontend/src/app/workspace/chats/[thread_id]/page.tsx`](<frontend/src/app/workspace/chats/[thread_id]/page.tsx>)
  - [`frontend/src/app/workspace/chats/[thread_id]/providers.tsx`](<frontend/src/app/workspace/chats/[thread_id]/providers.tsx>)
  - [`frontend/src/app/workspace/chats/page.tsx`](<frontend/src/app/workspace/chats/page.tsx>)
  - [`frontend/src/app/workspace/layout.tsx`](<frontend/src/app/workspace/layout.tsx>)
  - [`frontend/src/app/workspace/page.tsx`](<frontend/src/app/workspace/page.tsx>)
  - [`frontend/src/app/workspace/scheduled-tasks/page.tsx`](<frontend/src/app/workspace/scheduled-tasks/page.tsx>)
  - [`frontend/src/app/workspace/workspace-content.tsx`](<frontend/src/app/workspace/workspace-content.tsx>)

### 5. `frontend/src/app/(auth)`

- 作用：实现登录、初始化和认证回调页面。
- 阅读重点：关注认证状态建立后如何进入主应用。
- 文件：
  - [`frontend/src/app/(auth)/auth/callback/page.tsx`](<frontend/src/app/(auth)/auth/callback/page.tsx>)
  - [`frontend/src/app/(auth)/layout.tsx`](<frontend/src/app/(auth)/layout.tsx>)
  - [`frontend/src/app/(auth)/login/page.tsx`](<frontend/src/app/(auth)/login/page.tsx>)
  - [`frontend/src/app/(auth)/setup/page.tsx`](<frontend/src/app/(auth)/setup/page.tsx>)

### 6. `frontend/src/app/blog`

- 作用：实现博客文章、标签和列表页面。
- 阅读重点：了解内容路由与 MDX 渲染入口。
- 文件：
  - [`frontend/src/app/blog/[[...mdxPath]]/page.tsx`](<frontend/src/app/blog/[[...mdxPath]]/page.tsx>)
  - [`frontend/src/app/blog/layout.tsx`](<frontend/src/app/blog/layout.tsx>)
  - [`frontend/src/app/blog/posts/page.tsx`](<frontend/src/app/blog/posts/page.tsx>)
  - [`frontend/src/app/blog/tags/[tag]/page.tsx`](<frontend/src/app/blog/tags/[tag]/page.tsx>)

### 7. `frontend/src/app/[lang]`

- 作用：实现多语言文档路由与文档页面布局。
- 阅读重点：关注语言参数和文档路径的解析。
- 文件：
  - [`frontend/src/app/[lang]/docs/[[...mdxPath]]/page.tsx`](<frontend/src/app/[lang]/docs/[[...mdxPath]]/page.tsx>)
  - [`frontend/src/app/[lang]/docs/layout.tsx`](<frontend/src/app/[lang]/docs/layout.tsx>)

### 8. `frontend/src/app/api`

- 作用：提供 Next.js 服务端路由，衔接浏览器请求与后端服务。
- 阅读重点：阅读各 route handler 如何代理或补充 Gateway API。
- 文件：
  - [`frontend/src/app/api/memory/[...path]/route.ts`](<frontend/src/app/api/memory/[...path]/route.ts>)
  - [`frontend/src/app/api/memory/route.ts`](<frontend/src/app/api/memory/route.ts>)

### 9. `frontend/src/app`

- 作用：包含 App Router 的其余页面级入口和全局路由文件。
- 阅读重点：补齐页面装配和路由边界。
- 文件：
  - [`frontend/src/app/mock/api/mcp/config/route.ts`](<frontend/src/app/mock/api/mcp/config/route.ts>)
  - [`frontend/src/app/mock/api/models/route.ts`](<frontend/src/app/mock/api/models/route.ts>)
  - [`frontend/src/app/mock/api/skills/route.ts`](<frontend/src/app/mock/api/skills/route.ts>)
  - [`frontend/src/app/mock/api/threads/[thread_id]/artifacts/[[...artifact_path]]/route.ts`](<frontend/src/app/mock/api/threads/[thread_id]/artifacts/[[...artifact_path]]/route.ts>)
  - [`frontend/src/app/mock/api/threads/[thread_id]/history/route.ts`](<frontend/src/app/mock/api/threads/[thread_id]/history/route.ts>)
  - [`frontend/src/app/mock/api/threads/search/route.ts`](<frontend/src/app/mock/api/threads/search/route.ts>)

### 10. `frontend/src/components/query-client-provider.tsx`

- 作用：创建并注入 TanStack Query 客户端，为全站服务端状态缓存提供运行环境。
- 阅读重点：关注默认缓存策略以及 Provider 在应用布局中的装配位置。
- 文件：
  - [`frontend/src/components/query-client-provider.tsx`](<frontend/src/components/query-client-provider.tsx>)

### 11. `frontend/src/components/theme-provider.tsx`

- 作用：管理全局明暗主题并把主题状态注入 React 组件树。
- 阅读重点：关注主题持久化、系统主题跟随和页面挂载时机。
- 文件：
  - [`frontend/src/components/theme-provider.tsx`](<frontend/src/components/theme-provider.tsx>)

### 12. `frontend/src/components/workspace`

- 作用：实现工作区场景的 React 展示组件与交互控件。
- 阅读重点：先识别组件接收的数据，再回溯到对应 core 领域模块。
- 文件：
  - [`frontend/src/components/workspace/agent-welcome.tsx`](<frontend/src/components/workspace/agent-welcome.tsx>)
  - [`frontend/src/components/workspace/agents/agent-card.tsx`](<frontend/src/components/workspace/agents/agent-card.tsx>)
  - [`frontend/src/components/workspace/agents/agent-gallery.tsx`](<frontend/src/components/workspace/agents/agent-gallery.tsx>)
  - [`frontend/src/components/workspace/agents/agents-feature-disabled.tsx`](<frontend/src/components/workspace/agents/agents-feature-disabled.tsx>)
  - [`frontend/src/components/workspace/artifacts/artifact-file-detail.tsx`](<frontend/src/components/workspace/artifacts/artifact-file-detail.tsx>)
  - [`frontend/src/components/workspace/artifacts/artifact-file-list.tsx`](<frontend/src/components/workspace/artifacts/artifact-file-list.tsx>)
  - [`frontend/src/components/workspace/artifacts/artifact-trigger.tsx`](<frontend/src/components/workspace/artifacts/artifact-trigger.tsx>)
  - [`frontend/src/components/workspace/artifacts/context.tsx`](<frontend/src/components/workspace/artifacts/context.tsx>)
  - [`frontend/src/components/workspace/artifacts/index.ts`](<frontend/src/components/workspace/artifacts/index.ts>)
  - [`frontend/src/components/workspace/artifacts/markdown-preview-plugins.ts`](<frontend/src/components/workspace/artifacts/markdown-preview-plugins.ts>)
  - [`frontend/src/components/workspace/changes/index.ts`](<frontend/src/components/workspace/changes/index.ts>)
  - [`frontend/src/components/workspace/changes/workspace-change-badge.tsx`](<frontend/src/components/workspace/changes/workspace-change-badge.tsx>)
  - [`frontend/src/components/workspace/changes/workspace-change-panel.tsx`](<frontend/src/components/workspace/changes/workspace-change-panel.tsx>)
  - [`frontend/src/components/workspace/channels/channel-provider-icon.tsx`](<frontend/src/components/workspace/channels/channel-provider-icon.tsx>)
  - [`frontend/src/components/workspace/channels/channel-runtime-config-dialog.tsx`](<frontend/src/components/workspace/channels/channel-runtime-config-dialog.tsx>)
  - [`frontend/src/components/workspace/channels/workspace-channels-list.tsx`](<frontend/src/components/workspace/channels/workspace-channels-list.tsx>)
  - [`frontend/src/components/workspace/chats/chat-box.tsx`](<frontend/src/components/workspace/chats/chat-box.tsx>)
  - [`frontend/src/components/workspace/chats/index.ts`](<frontend/src/components/workspace/chats/index.ts>)
  - [`frontend/src/components/workspace/chats/use-chat-mode.ts`](<frontend/src/components/workspace/chats/use-chat-mode.ts>)
  - [`frontend/src/components/workspace/chats/use-thread-chat.ts`](<frontend/src/components/workspace/chats/use-thread-chat.ts>)
  - [`frontend/src/components/workspace/citations/artifact-link.tsx`](<frontend/src/components/workspace/citations/artifact-link.tsx>)
  - [`frontend/src/components/workspace/citations/citation-link.tsx`](<frontend/src/components/workspace/citations/citation-link.tsx>)
  - [`frontend/src/components/workspace/citations/citation-sources-panel.tsx`](<frontend/src/components/workspace/citations/citation-sources-panel.tsx>)
  - [`frontend/src/components/workspace/code-editor.tsx`](<frontend/src/components/workspace/code-editor.tsx>)
  - [`frontend/src/components/workspace/command-palette.tsx`](<frontend/src/components/workspace/command-palette.tsx>)
  - [`frontend/src/components/workspace/copy-button.tsx`](<frontend/src/components/workspace/copy-button.tsx>)
  - [`frontend/src/components/workspace/export-trigger.tsx`](<frontend/src/components/workspace/export-trigger.tsx>)
  - [`frontend/src/components/workspace/flip-display.tsx`](<frontend/src/components/workspace/flip-display.tsx>)
  - [`frontend/src/components/workspace/gateway-offline-banner-helpers.ts`](<frontend/src/components/workspace/gateway-offline-banner-helpers.ts>)
  - [`frontend/src/components/workspace/gateway-offline-banner.tsx`](<frontend/src/components/workspace/gateway-offline-banner.tsx>)
  - [`frontend/src/components/workspace/gateway-offline-fallback.tsx`](<frontend/src/components/workspace/gateway-offline-fallback.tsx>)
  - [`frontend/src/components/workspace/github-icon.tsx`](<frontend/src/components/workspace/github-icon.tsx>)
  - [`frontend/src/components/workspace/goal-status-helpers.ts`](<frontend/src/components/workspace/goal-status-helpers.ts>)
  - [`frontend/src/components/workspace/goal-status.tsx`](<frontend/src/components/workspace/goal-status.tsx>)
  - [`frontend/src/components/workspace/input-box-helpers.ts`](<frontend/src/components/workspace/input-box-helpers.ts>)
  - [`frontend/src/components/workspace/input-box.tsx`](<frontend/src/components/workspace/input-box.tsx>)
  - [`frontend/src/components/workspace/messages/context.ts`](<frontend/src/components/workspace/messages/context.ts>)
  - [`frontend/src/components/workspace/messages/human-input-card.tsx`](<frontend/src/components/workspace/messages/human-input-card.tsx>)
  - [`frontend/src/components/workspace/messages/index.ts`](<frontend/src/components/workspace/messages/index.ts>)
  - [`frontend/src/components/workspace/messages/markdown-content.tsx`](<frontend/src/components/workspace/messages/markdown-content.tsx>)
  - [`frontend/src/components/workspace/messages/markdown-link.tsx`](<frontend/src/components/workspace/messages/markdown-link.tsx>)
  - [`frontend/src/components/workspace/messages/message-group.tsx`](<frontend/src/components/workspace/messages/message-group.tsx>)
  - [`frontend/src/components/workspace/messages/message-list-item.tsx`](<frontend/src/components/workspace/messages/message-list-item.tsx>)
  - [`frontend/src/components/workspace/messages/message-list.tsx`](<frontend/src/components/workspace/messages/message-list.tsx>)
  - [`frontend/src/components/workspace/messages/message-token-usage.tsx`](<frontend/src/components/workspace/messages/message-token-usage.tsx>)
  - [`frontend/src/components/workspace/messages/skeleton.tsx`](<frontend/src/components/workspace/messages/skeleton.tsx>)
  - [`frontend/src/components/workspace/messages/subtask-card.tsx`](<frontend/src/components/workspace/messages/subtask-card.tsx>)
  - [`frontend/src/components/workspace/mode-hover-guide.tsx`](<frontend/src/components/workspace/mode-hover-guide.tsx>)
  - [`frontend/src/components/workspace/overscroll.tsx`](<frontend/src/components/workspace/overscroll.tsx>)
  - [`frontend/src/components/workspace/recent-chat-list.tsx`](<frontend/src/components/workspace/recent-chat-list.tsx>)
  - [`frontend/src/components/workspace/scheduled-task-schedule-input.tsx`](<frontend/src/components/workspace/scheduled-task-schedule-input.tsx>)
  - [`frontend/src/components/workspace/settings/about-content.ts`](<frontend/src/components/workspace/settings/about-content.ts>)
  - [`frontend/src/components/workspace/settings/about-settings-page.tsx`](<frontend/src/components/workspace/settings/about-settings-page.tsx>)
  - [`frontend/src/components/workspace/settings/account-settings-page.tsx`](<frontend/src/components/workspace/settings/account-settings-page.tsx>)
  - [`frontend/src/components/workspace/settings/appearance-settings-page.tsx`](<frontend/src/components/workspace/settings/appearance-settings-page.tsx>)
  - [`frontend/src/components/workspace/settings/channels-settings-page.tsx`](<frontend/src/components/workspace/settings/channels-settings-page.tsx>)
  - [`frontend/src/components/workspace/settings/index.ts`](<frontend/src/components/workspace/settings/index.ts>)
  - [`frontend/src/components/workspace/settings/memory-settings-page.tsx`](<frontend/src/components/workspace/settings/memory-settings-page.tsx>)
  - [`frontend/src/components/workspace/settings/notification-settings-page.tsx`](<frontend/src/components/workspace/settings/notification-settings-page.tsx>)
  - [`frontend/src/components/workspace/settings/settings-dialog.tsx`](<frontend/src/components/workspace/settings/settings-dialog.tsx>)
  - [`frontend/src/components/workspace/settings/settings-section.tsx`](<frontend/src/components/workspace/settings/settings-section.tsx>)
  - [`frontend/src/components/workspace/settings/skill-settings-page.tsx`](<frontend/src/components/workspace/settings/skill-settings-page.tsx>)
  - [`frontend/src/components/workspace/settings/tool-settings-page.tsx`](<frontend/src/components/workspace/settings/tool-settings-page.tsx>)
  - [`frontend/src/components/workspace/sidecar/context.tsx`](<frontend/src/components/workspace/sidecar/context.tsx>)
  - [`frontend/src/components/workspace/sidecar/index.ts`](<frontend/src/components/workspace/sidecar/index.ts>)
  - [`frontend/src/components/workspace/sidecar/reference-attachments.tsx`](<frontend/src/components/workspace/sidecar/reference-attachments.tsx>)
  - [`frontend/src/components/workspace/sidecar/sidecar-panel.tsx`](<frontend/src/components/workspace/sidecar/sidecar-panel.tsx>)
  - [`frontend/src/components/workspace/sidecar/sidecar-trigger.tsx`](<frontend/src/components/workspace/sidecar/sidecar-trigger.tsx>)
  - [`frontend/src/components/workspace/slash-skill-chip.tsx`](<frontend/src/components/workspace/slash-skill-chip.tsx>)
  - [`frontend/src/components/workspace/streaming-indicator.tsx`](<frontend/src/components/workspace/streaming-indicator.tsx>)
  - [`frontend/src/components/workspace/thread-channel-source.tsx`](<frontend/src/components/workspace/thread-channel-source.tsx>)
  - [`frontend/src/components/workspace/thread-scheduled-tasks-link.tsx`](<frontend/src/components/workspace/thread-scheduled-tasks-link.tsx>)
  - [`frontend/src/components/workspace/thread-title.tsx`](<frontend/src/components/workspace/thread-title.tsx>)
  - [`frontend/src/components/workspace/todo-list.tsx`](<frontend/src/components/workspace/todo-list.tsx>)
  - [`frontend/src/components/workspace/token-usage-indicator.tsx`](<frontend/src/components/workspace/token-usage-indicator.tsx>)
  - [`frontend/src/components/workspace/tooltip.tsx`](<frontend/src/components/workspace/tooltip.tsx>)
  - [`frontend/src/components/workspace/use-active-goal.ts`](<frontend/src/components/workspace/use-active-goal.ts>)
  - [`frontend/src/components/workspace/welcome.tsx`](<frontend/src/components/workspace/welcome.tsx>)
  - [`frontend/src/components/workspace/workspace-container.tsx`](<frontend/src/components/workspace/workspace-container.tsx>)
  - [`frontend/src/components/workspace/workspace-header.tsx`](<frontend/src/components/workspace/workspace-header.tsx>)
  - [`frontend/src/components/workspace/workspace-nav-chat-list.tsx`](<frontend/src/components/workspace/workspace-nav-chat-list.tsx>)
  - [`frontend/src/components/workspace/workspace-nav-menu.tsx`](<frontend/src/components/workspace/workspace-nav-menu.tsx>)
  - [`frontend/src/components/workspace/workspace-sidebar.tsx`](<frontend/src/components/workspace/workspace-sidebar.tsx>)

### 13. `frontend/src/components/ai-elements`

- 作用：实现AI 交互元素场景的 React 展示组件与交互控件。
- 阅读重点：先识别组件接收的数据，再回溯到对应 core 领域模块。
- 文件：
  - [`frontend/src/components/ai-elements/artifact.tsx`](<frontend/src/components/ai-elements/artifact.tsx>)
  - [`frontend/src/components/ai-elements/canvas.tsx`](<frontend/src/components/ai-elements/canvas.tsx>)
  - [`frontend/src/components/ai-elements/chain-of-thought.tsx`](<frontend/src/components/ai-elements/chain-of-thought.tsx>)
  - [`frontend/src/components/ai-elements/checkpoint.tsx`](<frontend/src/components/ai-elements/checkpoint.tsx>)
  - [`frontend/src/components/ai-elements/code-block.tsx`](<frontend/src/components/ai-elements/code-block.tsx>)
  - [`frontend/src/components/ai-elements/connection.tsx`](<frontend/src/components/ai-elements/connection.tsx>)
  - [`frontend/src/components/ai-elements/context.tsx`](<frontend/src/components/ai-elements/context.tsx>)
  - [`frontend/src/components/ai-elements/controls.tsx`](<frontend/src/components/ai-elements/controls.tsx>)
  - [`frontend/src/components/ai-elements/conversation.tsx`](<frontend/src/components/ai-elements/conversation.tsx>)
  - [`frontend/src/components/ai-elements/edge.tsx`](<frontend/src/components/ai-elements/edge.tsx>)
  - [`frontend/src/components/ai-elements/image.tsx`](<frontend/src/components/ai-elements/image.tsx>)
  - [`frontend/src/components/ai-elements/loader.tsx`](<frontend/src/components/ai-elements/loader.tsx>)
  - [`frontend/src/components/ai-elements/message.tsx`](<frontend/src/components/ai-elements/message.tsx>)
  - [`frontend/src/components/ai-elements/model-selector.tsx`](<frontend/src/components/ai-elements/model-selector.tsx>)
  - [`frontend/src/components/ai-elements/node.tsx`](<frontend/src/components/ai-elements/node.tsx>)
  - [`frontend/src/components/ai-elements/open-in-chat.tsx`](<frontend/src/components/ai-elements/open-in-chat.tsx>)
  - [`frontend/src/components/ai-elements/panel.tsx`](<frontend/src/components/ai-elements/panel.tsx>)
  - [`frontend/src/components/ai-elements/plan.tsx`](<frontend/src/components/ai-elements/plan.tsx>)
  - [`frontend/src/components/ai-elements/prompt-input.tsx`](<frontend/src/components/ai-elements/prompt-input.tsx>)
  - [`frontend/src/components/ai-elements/queue.tsx`](<frontend/src/components/ai-elements/queue.tsx>)
  - [`frontend/src/components/ai-elements/reasoning.tsx`](<frontend/src/components/ai-elements/reasoning.tsx>)
  - [`frontend/src/components/ai-elements/shimmer.tsx`](<frontend/src/components/ai-elements/shimmer.tsx>)
  - [`frontend/src/components/ai-elements/sources.tsx`](<frontend/src/components/ai-elements/sources.tsx>)
  - [`frontend/src/components/ai-elements/streamdown.tsx`](<frontend/src/components/ai-elements/streamdown.tsx>)
  - [`frontend/src/components/ai-elements/suggestion.tsx`](<frontend/src/components/ai-elements/suggestion.tsx>)
  - [`frontend/src/components/ai-elements/task.tsx`](<frontend/src/components/ai-elements/task.tsx>)
  - [`frontend/src/components/ai-elements/toolbar.tsx`](<frontend/src/components/ai-elements/toolbar.tsx>)
  - [`frontend/src/components/ai-elements/web-preview.tsx`](<frontend/src/components/ai-elements/web-preview.tsx>)

### 14. `frontend/src/components/landing`

- 作用：实现首页场景的 React 展示组件与交互控件。
- 阅读重点：先识别组件接收的数据，再回溯到对应 core 领域模块。
- 文件：
  - [`frontend/src/components/landing/footer.tsx`](<frontend/src/components/landing/footer.tsx>)
  - [`frontend/src/components/landing/header.tsx`](<frontend/src/components/landing/header.tsx>)
  - [`frontend/src/components/landing/hero.tsx`](<frontend/src/components/landing/hero.tsx>)
  - [`frontend/src/components/landing/mobile-nav.tsx`](<frontend/src/components/landing/mobile-nav.tsx>)
  - [`frontend/src/components/landing/post-list.tsx`](<frontend/src/components/landing/post-list.tsx>)
  - [`frontend/src/components/landing/progressive-skills-animation.tsx`](<frontend/src/components/landing/progressive-skills-animation.tsx>)
  - [`frontend/src/components/landing/section.tsx`](<frontend/src/components/landing/section.tsx>)
  - [`frontend/src/components/landing/sections/case-study-section.tsx`](<frontend/src/components/landing/sections/case-study-section.tsx>)
  - [`frontend/src/components/landing/sections/community-section.tsx`](<frontend/src/components/landing/sections/community-section.tsx>)
  - [`frontend/src/components/landing/sections/sandbox-section.tsx`](<frontend/src/components/landing/sections/sandbox-section.tsx>)
  - [`frontend/src/components/landing/sections/skills-section.tsx`](<frontend/src/components/landing/sections/skills-section.tsx>)
  - [`frontend/src/components/landing/sections/whats-new-section.tsx`](<frontend/src/components/landing/sections/whats-new-section.tsx>)

### 15. `frontend/src/components/docs`

- 作用：实现文档场景的 React 展示组件与交互控件。
- 阅读重点：先识别组件接收的数据，再回溯到对应 core 领域模块。
- 文件：
  - [`frontend/src/components/docs/localized-cards.tsx`](<frontend/src/components/docs/localized-cards.tsx>)
  - [`frontend/src/components/docs/localized-links.ts`](<frontend/src/components/docs/localized-links.ts>)
  - [`frontend/src/components/docs/localized-mdx-components.tsx`](<frontend/src/components/docs/localized-mdx-components.tsx>)

### 16. `frontend/src/components/ui`

- 作用：实现通用 UI场景的 React 展示组件与交互控件。
- 阅读重点：先识别组件接收的数据，再回溯到对应 core 领域模块。
- 文件：
  - [`frontend/src/components/ui/alert.tsx`](<frontend/src/components/ui/alert.tsx>)
  - [`frontend/src/components/ui/aurora-text.tsx`](<frontend/src/components/ui/aurora-text.tsx>)
  - [`frontend/src/components/ui/avatar.tsx`](<frontend/src/components/ui/avatar.tsx>)
  - [`frontend/src/components/ui/badge.tsx`](<frontend/src/components/ui/badge.tsx>)
  - [`frontend/src/components/ui/breadcrumb.tsx`](<frontend/src/components/ui/breadcrumb.tsx>)
  - [`frontend/src/components/ui/button-group.tsx`](<frontend/src/components/ui/button-group.tsx>)
  - [`frontend/src/components/ui/button.tsx`](<frontend/src/components/ui/button.tsx>)
  - [`frontend/src/components/ui/card.tsx`](<frontend/src/components/ui/card.tsx>)
  - [`frontend/src/components/ui/carousel.tsx`](<frontend/src/components/ui/carousel.tsx>)
  - [`frontend/src/components/ui/collapsible.tsx`](<frontend/src/components/ui/collapsible.tsx>)
  - [`frontend/src/components/ui/command.tsx`](<frontend/src/components/ui/command.tsx>)
  - [`frontend/src/components/ui/confetti-button.tsx`](<frontend/src/components/ui/confetti-button.tsx>)
  - [`frontend/src/components/ui/dialog.tsx`](<frontend/src/components/ui/dialog.tsx>)
  - [`frontend/src/components/ui/dropdown-menu.tsx`](<frontend/src/components/ui/dropdown-menu.tsx>)
  - [`frontend/src/components/ui/empty.tsx`](<frontend/src/components/ui/empty.tsx>)
  - [`frontend/src/components/ui/flickering-grid.tsx`](<frontend/src/components/ui/flickering-grid.tsx>)
  - [`frontend/src/components/ui/galaxy.css`](<frontend/src/components/ui/galaxy.css>)
  - [`frontend/src/components/ui/galaxy.jsx`](<frontend/src/components/ui/galaxy.jsx>)
  - [`frontend/src/components/ui/hover-card.tsx`](<frontend/src/components/ui/hover-card.tsx>)
  - [`frontend/src/components/ui/input-group.tsx`](<frontend/src/components/ui/input-group.tsx>)
  - [`frontend/src/components/ui/input.tsx`](<frontend/src/components/ui/input.tsx>)
  - [`frontend/src/components/ui/item.tsx`](<frontend/src/components/ui/item.tsx>)
  - [`frontend/src/components/ui/magic-bento.css`](<frontend/src/components/ui/magic-bento.css>)
  - [`frontend/src/components/ui/magic-bento.tsx`](<frontend/src/components/ui/magic-bento.tsx>)
  - [`frontend/src/components/ui/number-ticker.tsx`](<frontend/src/components/ui/number-ticker.tsx>)
  - [`frontend/src/components/ui/progress.tsx`](<frontend/src/components/ui/progress.tsx>)
  - [`frontend/src/components/ui/resizable.tsx`](<frontend/src/components/ui/resizable.tsx>)
  - [`frontend/src/components/ui/scroll-area.tsx`](<frontend/src/components/ui/scroll-area.tsx>)
  - [`frontend/src/components/ui/select.tsx`](<frontend/src/components/ui/select.tsx>)
  - [`frontend/src/components/ui/separator.tsx`](<frontend/src/components/ui/separator.tsx>)
  - [`frontend/src/components/ui/sheet.tsx`](<frontend/src/components/ui/sheet.tsx>)
  - [`frontend/src/components/ui/shine-border.tsx`](<frontend/src/components/ui/shine-border.tsx>)
  - [`frontend/src/components/ui/sidebar.tsx`](<frontend/src/components/ui/sidebar.tsx>)
  - [`frontend/src/components/ui/skeleton.tsx`](<frontend/src/components/ui/skeleton.tsx>)
  - [`frontend/src/components/ui/sonner.tsx`](<frontend/src/components/ui/sonner.tsx>)
  - [`frontend/src/components/ui/spotlight-card.css`](<frontend/src/components/ui/spotlight-card.css>)
  - [`frontend/src/components/ui/spotlight-card.tsx`](<frontend/src/components/ui/spotlight-card.tsx>)
  - [`frontend/src/components/ui/switch.tsx`](<frontend/src/components/ui/switch.tsx>)
  - [`frontend/src/components/ui/tabs.tsx`](<frontend/src/components/ui/tabs.tsx>)
  - [`frontend/src/components/ui/terminal.tsx`](<frontend/src/components/ui/terminal.tsx>)
  - [`frontend/src/components/ui/textarea.tsx`](<frontend/src/components/ui/textarea.tsx>)
  - [`frontend/src/components/ui/toggle-group.tsx`](<frontend/src/components/ui/toggle-group.tsx>)
  - [`frontend/src/components/ui/toggle.tsx`](<frontend/src/components/ui/toggle.tsx>)
  - [`frontend/src/components/ui/tooltip.tsx`](<frontend/src/components/ui/tooltip.tsx>)

### 17. `frontend/src/core/threads`

- 作用：承载前端“会话与流式交互”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/threads/api.ts`](<frontend/src/core/threads/api.ts>)
  - [`frontend/src/core/threads/export.ts`](<frontend/src/core/threads/export.ts>)
  - [`frontend/src/core/threads/hooks.ts`](<frontend/src/core/threads/hooks.ts>)
  - [`frontend/src/core/threads/index.ts`](<frontend/src/core/threads/index.ts>)
  - [`frontend/src/core/threads/static-demo.ts`](<frontend/src/core/threads/static-demo.ts>)
  - [`frontend/src/core/threads/thread-search-query.ts`](<frontend/src/core/threads/thread-search-query.ts>)
  - [`frontend/src/core/threads/token-usage.ts`](<frontend/src/core/threads/token-usage.ts>)
  - [`frontend/src/core/threads/types.ts`](<frontend/src/core/threads/types.ts>)
  - [`frontend/src/core/threads/utils.ts`](<frontend/src/core/threads/utils.ts>)

### 18. `frontend/src/core/messages`

- 作用：承载前端“消息模型与渲染数据”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/messages/human-input.ts`](<frontend/src/core/messages/human-input.ts>)
  - [`frontend/src/core/messages/usage-model.ts`](<frontend/src/core/messages/usage-model.ts>)
  - [`frontend/src/core/messages/usage.ts`](<frontend/src/core/messages/usage.ts>)
  - [`frontend/src/core/messages/utils.ts`](<frontend/src/core/messages/utils.ts>)

### 19. `frontend/src/core/tasks`

- 作用：承载前端“子任务生命周期”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/tasks/api.ts`](<frontend/src/core/tasks/api.ts>)
  - [`frontend/src/core/tasks/context.tsx`](<frontend/src/core/tasks/context.tsx>)
  - [`frontend/src/core/tasks/index.ts`](<frontend/src/core/tasks/index.ts>)
  - [`frontend/src/core/tasks/lifecycle.ts`](<frontend/src/core/tasks/lifecycle.ts>)
  - [`frontend/src/core/tasks/presentation.ts`](<frontend/src/core/tasks/presentation.ts>)
  - [`frontend/src/core/tasks/steps.ts`](<frontend/src/core/tasks/steps.ts>)
  - [`frontend/src/core/tasks/subtask-result.ts`](<frontend/src/core/tasks/subtask-result.ts>)
  - [`frontend/src/core/tasks/subtask-update.ts`](<frontend/src/core/tasks/subtask-update.ts>)
  - [`frontend/src/core/tasks/types.ts`](<frontend/src/core/tasks/types.ts>)

### 20. `frontend/src/core/todos`

- 作用：承载前端“待办状态”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/todos/index.ts`](<frontend/src/core/todos/index.ts>)
  - [`frontend/src/core/todos/types.ts`](<frontend/src/core/todos/types.ts>)

### 21. `frontend/src/core/artifacts`

- 作用：承载前端“产物管理”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/artifacts/hooks.ts`](<frontend/src/core/artifacts/hooks.ts>)
  - [`frontend/src/core/artifacts/index.ts`](<frontend/src/core/artifacts/index.ts>)
  - [`frontend/src/core/artifacts/loader.ts`](<frontend/src/core/artifacts/loader.ts>)
  - [`frontend/src/core/artifacts/preview.ts`](<frontend/src/core/artifacts/preview.ts>)
  - [`frontend/src/core/artifacts/utils.ts`](<frontend/src/core/artifacts/utils.ts>)

### 22. `frontend/src/core/uploads`

- 作用：承载前端“文件上传”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/uploads/api.ts`](<frontend/src/core/uploads/api.ts>)
  - [`frontend/src/core/uploads/file-validation.ts`](<frontend/src/core/uploads/file-validation.ts>)
  - [`frontend/src/core/uploads/hooks.ts`](<frontend/src/core/uploads/hooks.ts>)
  - [`frontend/src/core/uploads/index.ts`](<frontend/src/core/uploads/index.ts>)
  - [`frontend/src/core/uploads/prompt-input-files.ts`](<frontend/src/core/uploads/prompt-input-files.ts>)

### 23. `frontend/src/core/workspace-changes`

- 作用：承载前端“工作区变更”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/workspace-changes/api.ts`](<frontend/src/core/workspace-changes/api.ts>)
  - [`frontend/src/core/workspace-changes/hooks.ts`](<frontend/src/core/workspace-changes/hooks.ts>)
  - [`frontend/src/core/workspace-changes/index.ts`](<frontend/src/core/workspace-changes/index.ts>)
  - [`frontend/src/core/workspace-changes/summary.ts`](<frontend/src/core/workspace-changes/summary.ts>)
  - [`frontend/src/core/workspace-changes/types.ts`](<frontend/src/core/workspace-changes/types.ts>)

### 24. `frontend/src/core/sidecar`

- 作用：承载前端“侧边会话”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/sidecar/api.ts`](<frontend/src/core/sidecar/api.ts>)
  - [`frontend/src/core/sidecar/context.ts`](<frontend/src/core/sidecar/context.ts>)
  - [`frontend/src/core/sidecar/index.ts`](<frontend/src/core/sidecar/index.ts>)
  - [`frontend/src/core/sidecar/reference-metadata.ts`](<frontend/src/core/sidecar/reference-metadata.ts>)
  - [`frontend/src/core/sidecar/reference-state.ts`](<frontend/src/core/sidecar/reference-state.ts>)
  - [`frontend/src/core/sidecar/thread.ts`](<frontend/src/core/sidecar/thread.ts>)

### 25. `frontend/src/core/agents`

- 作用：承载前端“自定义 Agent”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/agents/api.ts`](<frontend/src/core/agents/api.ts>)
  - [`frontend/src/core/agents/feature-cache.ts`](<frontend/src/core/agents/feature-cache.ts>)
  - [`frontend/src/core/agents/hooks.ts`](<frontend/src/core/agents/hooks.ts>)
  - [`frontend/src/core/agents/index.ts`](<frontend/src/core/agents/index.ts>)
  - [`frontend/src/core/agents/types.ts`](<frontend/src/core/agents/types.ts>)

### 26. `frontend/src/core/auth`

- 作用：承载前端“认证”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/auth/auth-disabled-user.ts`](<frontend/src/core/auth/auth-disabled-user.ts>)
  - [`frontend/src/core/auth/AuthProvider.tsx`](<frontend/src/core/auth/AuthProvider.tsx>)
  - [`frontend/src/core/auth/gateway-config.ts`](<frontend/src/core/auth/gateway-config.ts>)
  - [`frontend/src/core/auth/proxy-policy.ts`](<frontend/src/core/auth/proxy-policy.ts>)
  - [`frontend/src/core/auth/server.ts`](<frontend/src/core/auth/server.ts>)
  - [`frontend/src/core/auth/setup.ts`](<frontend/src/core/auth/setup.ts>)
  - [`frontend/src/core/auth/static-user.ts`](<frontend/src/core/auth/static-user.ts>)
  - [`frontend/src/core/auth/types.ts`](<frontend/src/core/auth/types.ts>)

### 27. `frontend/src/core/channels`

- 作用：承载前端“即时通信渠道”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/channels/api.ts`](<frontend/src/core/channels/api.ts>)
  - [`frontend/src/core/channels/connect-poll.ts`](<frontend/src/core/channels/connect-poll.ts>)
  - [`frontend/src/core/channels/hooks.ts`](<frontend/src/core/channels/hooks.ts>)
  - [`frontend/src/core/channels/open-connect-url.ts`](<frontend/src/core/channels/open-connect-url.ts>)
  - [`frontend/src/core/channels/provider-state.ts`](<frontend/src/core/channels/provider-state.ts>)
  - [`frontend/src/core/channels/types.ts`](<frontend/src/core/channels/types.ts>)

### 28. `frontend/src/core/scheduled-tasks`

- 作用：承载前端“定时任务”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/scheduled-tasks/api.ts`](<frontend/src/core/scheduled-tasks/api.ts>)
  - [`frontend/src/core/scheduled-tasks/cron.ts`](<frontend/src/core/scheduled-tasks/cron.ts>)
  - [`frontend/src/core/scheduled-tasks/hooks.ts`](<frontend/src/core/scheduled-tasks/hooks.ts>)
  - [`frontend/src/core/scheduled-tasks/recipes.ts`](<frontend/src/core/scheduled-tasks/recipes.ts>)
  - [`frontend/src/core/scheduled-tasks/types.ts`](<frontend/src/core/scheduled-tasks/types.ts>)

### 29. `frontend/src/core/settings`

- 作用：承载前端“用户设置”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/settings/hooks.ts`](<frontend/src/core/settings/hooks.ts>)
  - [`frontend/src/core/settings/index.ts`](<frontend/src/core/settings/index.ts>)
  - [`frontend/src/core/settings/local.ts`](<frontend/src/core/settings/local.ts>)
  - [`frontend/src/core/settings/store.ts`](<frontend/src/core/settings/store.ts>)

### 30. `frontend/src/core/memory`

- 作用：承载前端“记忆配置”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/memory/api.ts`](<frontend/src/core/memory/api.ts>)
  - [`frontend/src/core/memory/hooks.ts`](<frontend/src/core/memory/hooks.ts>)
  - [`frontend/src/core/memory/index.ts`](<frontend/src/core/memory/index.ts>)
  - [`frontend/src/core/memory/types.ts`](<frontend/src/core/memory/types.ts>)

### 31. `frontend/src/core/skills`

- 作用：承载前端“技能管理”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/skills/api.ts`](<frontend/src/core/skills/api.ts>)
  - [`frontend/src/core/skills/hooks.ts`](<frontend/src/core/skills/hooks.ts>)
  - [`frontend/src/core/skills/index.ts`](<frontend/src/core/skills/index.ts>)
  - [`frontend/src/core/skills/slash.ts`](<frontend/src/core/skills/slash.ts>)
  - [`frontend/src/core/skills/type.ts`](<frontend/src/core/skills/type.ts>)

### 32. `frontend/src/core/mcp`

- 作用：承载前端“MCP 工具接入”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/mcp/api.ts`](<frontend/src/core/mcp/api.ts>)
  - [`frontend/src/core/mcp/hooks.ts`](<frontend/src/core/mcp/hooks.ts>)
  - [`frontend/src/core/mcp/index.ts`](<frontend/src/core/mcp/index.ts>)
  - [`frontend/src/core/mcp/types.ts`](<frontend/src/core/mcp/types.ts>)

### 33. `frontend/src/core/models`

- 作用：承载前端“模型配置”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/models/api.ts`](<frontend/src/core/models/api.ts>)
  - [`frontend/src/core/models/hooks.ts`](<frontend/src/core/models/hooks.ts>)
  - [`frontend/src/core/models/index.ts`](<frontend/src/core/models/index.ts>)
  - [`frontend/src/core/models/types.ts`](<frontend/src/core/models/types.ts>)

### 34. `frontend/src/core/input-polish`

- 作用：承载前端“输入润色”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/input-polish/api.ts`](<frontend/src/core/input-polish/api.ts>)

### 35. `frontend/src/core/voice-input`

- 作用：承载前端“语音输入”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/voice-input/speech-recognition.ts`](<frontend/src/core/voice-input/speech-recognition.ts>)

### 36. `frontend/src/core/suggestions`

- 作用：承载前端“建议生成”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/suggestions/api.ts`](<frontend/src/core/suggestions/api.ts>)
  - [`frontend/src/core/suggestions/hooks.ts`](<frontend/src/core/suggestions/hooks.ts>)
  - [`frontend/src/core/suggestions/placeholders.ts`](<frontend/src/core/suggestions/placeholders.ts>)

### 37. `frontend/src/core/api`

- 作用：承载前端“后端 API 客户端”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/api/api-client.ts`](<frontend/src/core/api/api-client.ts>)
  - [`frontend/src/core/api/errors.ts`](<frontend/src/core/api/errors.ts>)
  - [`frontend/src/core/api/feedback.ts`](<frontend/src/core/api/feedback.ts>)
  - [`frontend/src/core/api/fetcher.ts`](<frontend/src/core/api/fetcher.ts>)
  - [`frontend/src/core/api/index.ts`](<frontend/src/core/api/index.ts>)
  - [`frontend/src/core/api/stream-mode.ts`](<frontend/src/core/api/stream-mode.ts>)

### 38. `frontend/src/core/config`

- 作用：承载前端“前端配置”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/config/index.ts`](<frontend/src/core/config/index.ts>)

### 39. `frontend/src/core/i18n`

- 作用：承载前端“国际化”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/i18n/context.tsx`](<frontend/src/core/i18n/context.tsx>)
  - [`frontend/src/core/i18n/cookies.ts`](<frontend/src/core/i18n/cookies.ts>)
  - [`frontend/src/core/i18n/hooks.ts`](<frontend/src/core/i18n/hooks.ts>)
  - [`frontend/src/core/i18n/index.ts`](<frontend/src/core/i18n/index.ts>)
  - [`frontend/src/core/i18n/locale.ts`](<frontend/src/core/i18n/locale.ts>)
  - [`frontend/src/core/i18n/locales/en-US.ts`](<frontend/src/core/i18n/locales/en-US.ts>)
  - [`frontend/src/core/i18n/locales/index.ts`](<frontend/src/core/i18n/locales/index.ts>)
  - [`frontend/src/core/i18n/locales/types.ts`](<frontend/src/core/i18n/locales/types.ts>)
  - [`frontend/src/core/i18n/locales/zh-CN.ts`](<frontend/src/core/i18n/locales/zh-CN.ts>)
  - [`frontend/src/core/i18n/server.ts`](<frontend/src/core/i18n/server.ts>)
  - [`frontend/src/core/i18n/translations.ts`](<frontend/src/core/i18n/translations.ts>)

### 40. `frontend/src/core/notification`

- 作用：承载前端“通知”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/notification/hooks.ts`](<frontend/src/core/notification/hooks.ts>)

### 41. `frontend/src/core/blog`

- 作用：承载前端“博客数据”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/blog/index.ts`](<frontend/src/core/blog/index.ts>)

### 42. `frontend/src/core/citations`

- 作用：承载前端“引用来源”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/citations/sources.ts`](<frontend/src/core/citations/sources.ts>)

### 43. `frontend/src/core/rehype`

- 作用：承载前端“Markdown 转换”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/rehype/index.ts`](<frontend/src/core/rehype/index.ts>)

### 44. `frontend/src/core/streamdown`

- 作用：承载前端“流式 Markdown 渲染”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/streamdown/components.tsx`](<frontend/src/core/streamdown/components.tsx>)
  - [`frontend/src/core/streamdown/index.ts`](<frontend/src/core/streamdown/index.ts>)
  - [`frontend/src/core/streamdown/mermaid.ts`](<frontend/src/core/streamdown/mermaid.ts>)
  - [`frontend/src/core/streamdown/plugins.ts`](<frontend/src/core/streamdown/plugins.ts>)
  - [`frontend/src/core/streamdown/preprocess.ts`](<frontend/src/core/streamdown/preprocess.ts>)
  - [`frontend/src/core/streamdown/safe-children.ts`](<frontend/src/core/streamdown/safe-children.ts>)

### 45. `frontend/src/core/tools`

- 作用：承载前端“工具展示”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/tools/utils.ts`](<frontend/src/core/tools/utils.ts>)

### 46. `frontend/src/core/utils`

- 作用：承载前端“通用工具”领域的 API、状态、类型和业务规则。
- 阅读重点：优先阅读 index、types、api 和 hooks，再看纯函数与适配逻辑。
- 文件：
  - [`frontend/src/core/utils/datetime.ts`](<frontend/src/core/utils/datetime.ts>)
  - [`frontend/src/core/utils/files.tsx`](<frontend/src/core/utils/files.tsx>)
  - [`frontend/src/core/utils/json.ts`](<frontend/src/core/utils/json.ts>)
  - [`frontend/src/core/utils/markdown.ts`](<frontend/src/core/utils/markdown.ts>)
  - [`frontend/src/core/utils/uuid.ts`](<frontend/src/core/utils/uuid.ts>)

### 47. `frontend/src/content`

- 作用：维护站点内容树的 TypeScript 元数据和导航结构。
- 阅读重点：了解内容文件如何映射到多语言页面。
- 文件：
  - [`frontend/src/content/en/_meta.ts`](<frontend/src/content/en/_meta.ts>)
  - [`frontend/src/content/en/application/_meta.ts`](<frontend/src/content/en/application/_meta.ts>)
  - [`frontend/src/content/en/harness/_meta.ts`](<frontend/src/content/en/harness/_meta.ts>)
  - [`frontend/src/content/en/introduction/_meta.ts`](<frontend/src/content/en/introduction/_meta.ts>)
  - [`frontend/src/content/en/posts/_meta.ts`](<frontend/src/content/en/posts/_meta.ts>)
  - [`frontend/src/content/en/reference/_meta.ts`](<frontend/src/content/en/reference/_meta.ts>)
  - [`frontend/src/content/en/reference/model-providers/_meta.ts`](<frontend/src/content/en/reference/model-providers/_meta.ts>)
  - [`frontend/src/content/en/tutorials/_meta.ts`](<frontend/src/content/en/tutorials/_meta.ts>)
  - [`frontend/src/content/zh/_meta.ts`](<frontend/src/content/zh/_meta.ts>)
  - [`frontend/src/content/zh/application/_meta.ts`](<frontend/src/content/zh/application/_meta.ts>)
  - [`frontend/src/content/zh/harness/_meta.ts`](<frontend/src/content/zh/harness/_meta.ts>)
  - [`frontend/src/content/zh/introduction/_meta.ts`](<frontend/src/content/zh/introduction/_meta.ts>)
  - [`frontend/src/content/zh/posts/_meta.ts`](<frontend/src/content/zh/posts/_meta.ts>)
  - [`frontend/src/content/zh/reference/_meta.ts`](<frontend/src/content/zh/reference/_meta.ts>)
  - [`frontend/src/content/zh/reference/model-providers/_meta.ts`](<frontend/src/content/zh/reference/model-providers/_meta.ts>)
  - [`frontend/src/content/zh/tutorials/_meta.ts`](<frontend/src/content/zh/tutorials/_meta.ts>)

### 48. `frontend/src/hooks`

- 作用：提供跨页面复用的 React Hooks。
- 阅读重点：关注全局快捷键和响应式设备判断。
- 文件：
  - [`frontend/src/hooks/use-global-shortcuts.ts`](<frontend/src/hooks/use-global-shortcuts.ts>)
  - [`frontend/src/hooks/use-mobile.ts`](<frontend/src/hooks/use-mobile.ts>)

### 49. `frontend/src/lib`

- 作用：提供前端低层通用辅助函数。
- 阅读重点：了解样式合并和输入法兼容等基础能力。
- 文件：
  - [`frontend/src/lib/ime.ts`](<frontend/src/lib/ime.ts>)
  - [`frontend/src/lib/utils.ts`](<frontend/src/lib/utils.ts>)

### 50. `frontend/src/styles` 与 `frontend/src/typings`

- 作用：定义全局样式、主题变量和 TypeScript 环境声明。
- 阅读重点：作为阅读前端实现时的样式与类型基础参考。
- 文件：
  - [`frontend/src/styles/globals.css`](<frontend/src/styles/globals.css>)
  - [`frontend/src/typings/md.d.ts`](<frontend/src/typings/md.d.ts>)

### 51. `frontend/src`

- 作用：包含前端环境校验、版本和 MDX 组件映射等源码根入口。
- 阅读重点：关注运行环境变量和全局组件映射。
- 文件：
  - [`frontend/src/env.js`](<frontend/src/env.js>)
  - [`frontend/src/mdx-components.ts`](<frontend/src/mdx-components.ts>)
  - [`frontend/src/version.ts`](<frontend/src/version.ts>)

### 52. `frontend/src/core/clipboard.ts`

- 作用：封装浏览器剪贴板写入与兼容处理，供消息和产物复制功能复用。
- 阅读重点：关注浏览器能力检测、降级路径和错误处理。
- 文件：
  - [`frontend/src/core/clipboard.ts`](<frontend/src/core/clipboard.ts>)

### 53. `frontend/src/core/static-mode.ts`

- 作用：判断前端是否运行在静态演示模式，并提供对应的行为开关。
- 阅读重点：关注静态模式如何改变 API 请求和演示数据来源。
- 文件：
  - [`frontend/src/core/static-mode.ts`](<frontend/src/core/static-mode.ts>)

## 第二阶段：Gateway、渠道与应用编排

### 54. `backend/app/gateway/app.py`

- 作用：创建 FastAPI Gateway 应用并注册中间件、路由和生命周期。
- 阅读重点：这是后端应用层最重要的装配入口。
- 文件：
  - [`backend/app/gateway/app.py`](<backend/app/gateway/app.py>)

### 55. `backend/app/gateway/routers`

- 作用：定义线程、运行、模型、技能、上传等 Gateway HTTP API。
- 阅读重点：从用户请求入口追踪到 harness 服务和持久化层。
- 文件：
  - [`backend/app/gateway/routers/__init__.py`](<backend/app/gateway/routers/__init__.py>)
  - [`backend/app/gateway/routers/agents.py`](<backend/app/gateway/routers/agents.py>)
  - [`backend/app/gateway/routers/artifacts.py`](<backend/app/gateway/routers/artifacts.py>)
  - [`backend/app/gateway/routers/assistants_compat.py`](<backend/app/gateway/routers/assistants_compat.py>)
  - [`backend/app/gateway/routers/auth.py`](<backend/app/gateway/routers/auth.py>)
  - [`backend/app/gateway/routers/channel_connections.py`](<backend/app/gateway/routers/channel_connections.py>)
  - [`backend/app/gateway/routers/channels.py`](<backend/app/gateway/routers/channels.py>)
  - [`backend/app/gateway/routers/console.py`](<backend/app/gateway/routers/console.py>)
  - [`backend/app/gateway/routers/features.py`](<backend/app/gateway/routers/features.py>)
  - [`backend/app/gateway/routers/feedback.py`](<backend/app/gateway/routers/feedback.py>)
  - [`backend/app/gateway/routers/github_webhooks.py`](<backend/app/gateway/routers/github_webhooks.py>)
  - [`backend/app/gateway/routers/input_polish.py`](<backend/app/gateway/routers/input_polish.py>)
  - [`backend/app/gateway/routers/mcp.py`](<backend/app/gateway/routers/mcp.py>)
  - [`backend/app/gateway/routers/memory.py`](<backend/app/gateway/routers/memory.py>)
  - [`backend/app/gateway/routers/models.py`](<backend/app/gateway/routers/models.py>)
  - [`backend/app/gateway/routers/runs.py`](<backend/app/gateway/routers/runs.py>)
  - [`backend/app/gateway/routers/scheduled_tasks.py`](<backend/app/gateway/routers/scheduled_tasks.py>)
  - [`backend/app/gateway/routers/skills.py`](<backend/app/gateway/routers/skills.py>)
  - [`backend/app/gateway/routers/suggestions.py`](<backend/app/gateway/routers/suggestions.py>)
  - [`backend/app/gateway/routers/thread_runs.py`](<backend/app/gateway/routers/thread_runs.py>)
  - [`backend/app/gateway/routers/threads.py`](<backend/app/gateway/routers/threads.py>)
  - [`backend/app/gateway/routers/uploads.py`](<backend/app/gateway/routers/uploads.py>)

### 56. `backend/app/gateway/auth`

- 作用：实现本地认证、OIDC、JWT、密码与用户仓储。
- 阅读重点：关注凭证验证、用户创建和认证状态持久化。
- 文件：
  - [`backend/app/gateway/auth/__init__.py`](<backend/app/gateway/auth/__init__.py>)
  - [`backend/app/gateway/auth/config.py`](<backend/app/gateway/auth/config.py>)
  - [`backend/app/gateway/auth/credential_file.py`](<backend/app/gateway/auth/credential_file.py>)
  - [`backend/app/gateway/auth/errors.py`](<backend/app/gateway/auth/errors.py>)
  - [`backend/app/gateway/auth/jwt.py`](<backend/app/gateway/auth/jwt.py>)
  - [`backend/app/gateway/auth/local_provider.py`](<backend/app/gateway/auth/local_provider.py>)
  - [`backend/app/gateway/auth/models.py`](<backend/app/gateway/auth/models.py>)
  - [`backend/app/gateway/auth/oidc_state.py`](<backend/app/gateway/auth/oidc_state.py>)
  - [`backend/app/gateway/auth/oidc.py`](<backend/app/gateway/auth/oidc.py>)
  - [`backend/app/gateway/auth/password.py`](<backend/app/gateway/auth/password.py>)
  - [`backend/app/gateway/auth/providers.py`](<backend/app/gateway/auth/providers.py>)
  - [`backend/app/gateway/auth/repositories/__init__.py`](<backend/app/gateway/auth/repositories/__init__.py>)
  - [`backend/app/gateway/auth/repositories/base.py`](<backend/app/gateway/auth/repositories/base.py>)
  - [`backend/app/gateway/auth/repositories/sqlite.py`](<backend/app/gateway/auth/repositories/sqlite.py>)
  - [`backend/app/gateway/auth/reset_admin.py`](<backend/app/gateway/auth/reset_admin.py>)
  - [`backend/app/gateway/auth/user_provisioning.py`](<backend/app/gateway/auth/user_provisioning.py>)

### 57. `backend/app/gateway/github`

- 作用：实现 GitHub App 身份、触发器和任务分发。
- 阅读重点：追踪 webhook 如何转换为受策略约束的 Agent 运行。
- 文件：
  - [`backend/app/gateway/github/__init__.py`](<backend/app/gateway/github/__init__.py>)
  - [`backend/app/gateway/github/app_auth.py`](<backend/app/gateway/github/app_auth.py>)
  - [`backend/app/gateway/github/dispatcher.py`](<backend/app/gateway/github/dispatcher.py>)
  - [`backend/app/gateway/github/identity.py`](<backend/app/gateway/github/identity.py>)
  - [`backend/app/gateway/github/prompts.py`](<backend/app/gateway/github/prompts.py>)
  - [`backend/app/gateway/github/registry.py`](<backend/app/gateway/github/registry.py>)
  - [`backend/app/gateway/github/run_policy.py`](<backend/app/gateway/github/run_policy.py>)
  - [`backend/app/gateway/github/triggers.py`](<backend/app/gateway/github/triggers.py>)

### 58. `backend/app/gateway`

- 作用：提供 Gateway 的鉴权、中间件、依赖注入、配置和通用服务。
- 阅读重点：理解请求进入路由前后的安全与上下文处理。
- 文件：
  - [`backend/app/gateway/__init__.py`](<backend/app/gateway/__init__.py>)
  - [`backend/app/gateway/auth_disabled.py`](<backend/app/gateway/auth_disabled.py>)
  - [`backend/app/gateway/auth_middleware.py`](<backend/app/gateway/auth_middleware.py>)
  - [`backend/app/gateway/authz.py`](<backend/app/gateway/authz.py>)
  - [`backend/app/gateway/config.py`](<backend/app/gateway/config.py>)
  - [`backend/app/gateway/csrf_middleware.py`](<backend/app/gateway/csrf_middleware.py>)
  - [`backend/app/gateway/deps.py`](<backend/app/gateway/deps.py>)
  - [`backend/app/gateway/internal_auth.py`](<backend/app/gateway/internal_auth.py>)
  - [`backend/app/gateway/langgraph_auth.py`](<backend/app/gateway/langgraph_auth.py>)
  - [`backend/app/gateway/pagination.py`](<backend/app/gateway/pagination.py>)
  - [`backend/app/gateway/path_utils.py`](<backend/app/gateway/path_utils.py>)
  - [`backend/app/gateway/services.py`](<backend/app/gateway/services.py>)
  - [`backend/app/gateway/trace_middleware.py`](<backend/app/gateway/trace_middleware.py>)
  - [`backend/app/gateway/utils.py`](<backend/app/gateway/utils.py>)

### 59. `backend/app/channels`

- 作用：适配飞书、Slack、Telegram、Discord、微信等即时通信渠道。
- 阅读重点：阅读统一渠道接口、消息总线、运行策略，再看各平台适配。
- 文件：
  - [`backend/app/channels/__init__.py`](<backend/app/channels/__init__.py>)
  - [`backend/app/channels/base.py`](<backend/app/channels/base.py>)
  - [`backend/app/channels/commands.py`](<backend/app/channels/commands.py>)
  - [`backend/app/channels/connection_identity.py`](<backend/app/channels/connection_identity.py>)
  - [`backend/app/channels/dingtalk.py`](<backend/app/channels/dingtalk.py>)
  - [`backend/app/channels/discord.py`](<backend/app/channels/discord.py>)
  - [`backend/app/channels/feishu_run_policy.py`](<backend/app/channels/feishu_run_policy.py>)
  - [`backend/app/channels/feishu.py`](<backend/app/channels/feishu.py>)
  - [`backend/app/channels/github.py`](<backend/app/channels/github.py>)
  - [`backend/app/channels/manager.py`](<backend/app/channels/manager.py>)
  - [`backend/app/channels/message_bus.py`](<backend/app/channels/message_bus.py>)
  - [`backend/app/channels/run_policy.py`](<backend/app/channels/run_policy.py>)
  - [`backend/app/channels/runtime_config_store.py`](<backend/app/channels/runtime_config_store.py>)
  - [`backend/app/channels/service.py`](<backend/app/channels/service.py>)
  - [`backend/app/channels/slack.py`](<backend/app/channels/slack.py>)
  - [`backend/app/channels/store.py`](<backend/app/channels/store.py>)
  - [`backend/app/channels/telegram.py`](<backend/app/channels/telegram.py>)
  - [`backend/app/channels/wechat.py`](<backend/app/channels/wechat.py>)
  - [`backend/app/channels/wecom.py`](<backend/app/channels/wecom.py>)

### 60. `backend/app/scheduler`

- 作用：运行后台定时任务扫描与非交互式 Agent 调度。
- 阅读重点：关注任务领取、触发和运行生命周期。
- 文件：
  - [`backend/app/scheduler/__init__.py`](<backend/app/scheduler/__init__.py>)
  - [`backend/app/scheduler/service.py`](<backend/app/scheduler/service.py>)

### 61. `backend/app`

- 作用：包含后端应用包入口和调试辅助入口。
- 阅读重点：用于补齐 Gateway 应用层的包结构。
- 文件：
  - [`backend/app/__init__.py`](<backend/app/__init__.py>)

## 第三阶段：Agent 核心、运行时与工具实现

### 62. `backend/packages/harness/deerflow/agents/lead_agent/agent.py`

- 作用：组装 DeerFlow 主 Agent 的模型、工具、中间件和运行状态。
- 阅读重点：从此文件建立 Agent 一次运行的整体心智模型。
- 文件：
  - [`backend/packages/harness/deerflow/agents/lead_agent/agent.py`](<backend/packages/harness/deerflow/agents/lead_agent/agent.py>)

### 63. `backend/packages/harness/deerflow/agents/lead_agent`

- 作用：定义主 Agent 的提示词和包入口。
- 阅读重点：结合 agent.py 理解系统提示词如何约束行为。
- 文件：
  - [`backend/packages/harness/deerflow/agents/lead_agent/__init__.py`](<backend/packages/harness/deerflow/agents/lead_agent/__init__.py>)
  - [`backend/packages/harness/deerflow/agents/lead_agent/prompt.py`](<backend/packages/harness/deerflow/agents/lead_agent/prompt.py>)

### 64. `backend/packages/harness/deerflow/agents/middlewares`

- 作用：实现 Agent 调用链上的技能、记忆、上传、预算、安全和结果处理中间件。
- 阅读重点：按 agent.py 中注册顺序阅读，理解每层对状态和工具调用的影响。
- 文件：
  - [`backend/packages/harness/deerflow/agents/middlewares/__init__.py`](<backend/packages/harness/deerflow/agents/middlewares/__init__.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/_bounded_dict.py`](<backend/packages/harness/deerflow/agents/middlewares/_bounded_dict.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/clarification_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/clarification_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/dangling_tool_call_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/dangling_tool_call_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/deferred_tool_filter_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/deferred_tool_filter_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/delegation_ledger.py`](<backend/packages/harness/deerflow/agents/middlewares/delegation_ledger.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/durable_context_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/durable_context_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/dynamic_context_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/dynamic_context_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/input_sanitization_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/input_sanitization_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/llm_error_handling_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/llm_error_handling_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/mcp_routing_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/mcp_routing_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/memory_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/memory_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/read_before_write_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/read_before_write_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/safety_finish_reason_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/safety_finish_reason_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/safety_termination_detectors.py`](<backend/packages/harness/deerflow/agents/middlewares/safety_termination_detectors.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/sandbox_audit_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/sandbox_audit_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/skill_activation_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/skill_activation_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/skill_context.py`](<backend/packages/harness/deerflow/agents/middlewares/skill_context.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/subagent_limit_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/subagent_limit_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/summarization_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/summarization_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/system_message_coalescing_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/system_message_coalescing_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/terminal_response_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/terminal_response_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/thread_data_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/thread_data_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/title_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/title_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/todo_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/todo_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/token_budget_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/token_budget_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/token_usage_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/token_usage_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/tool_call_metadata.py`](<backend/packages/harness/deerflow/agents/middlewares/tool_call_metadata.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/tool_output_budget_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/tool_output_budget_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/tool_progress_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/tool_progress_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/tool_result_meta.py`](<backend/packages/harness/deerflow/agents/middlewares/tool_result_meta.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/tool_result_sanitization_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/tool_result_sanitization_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py>)
  - [`backend/packages/harness/deerflow/agents/middlewares/view_image_middleware.py`](<backend/packages/harness/deerflow/agents/middlewares/view_image_middleware.py>)

### 65. `backend/packages/harness/deerflow/agents/memory`

- 作用：实现长期记忆管理、摘要钩子和记忆工具。
- 阅读重点：关注记忆后端接口、写入队列与上下文注入。
- 文件：
  - [`backend/packages/harness/deerflow/agents/memory/__init__.py`](<backend/packages/harness/deerflow/agents/memory/__init__.py>)
  - [`backend/packages/harness/deerflow/agents/memory/backends/__init__.py`](<backend/packages/harness/deerflow/agents/memory/backends/__init__.py>)
  - [`backend/packages/harness/deerflow/agents/memory/backends/deermem/__init__.py`](<backend/packages/harness/deerflow/agents/memory/backends/deermem/__init__.py>)
  - [`backend/packages/harness/deerflow/agents/memory/backends/deermem/deer_mem.py`](<backend/packages/harness/deerflow/agents/memory/backends/deermem/deer_mem.py>)
  - [`backend/packages/harness/deerflow/agents/memory/backends/deermem/deermem/__init__.py`](<backend/packages/harness/deerflow/agents/memory/backends/deermem/deermem/__init__.py>)
  - [`backend/packages/harness/deerflow/agents/memory/backends/deermem/deermem/config.py`](<backend/packages/harness/deerflow/agents/memory/backends/deermem/deermem/config.py>)
  - [`backend/packages/harness/deerflow/agents/memory/backends/deermem/deermem/core/__init__.py`](<backend/packages/harness/deerflow/agents/memory/backends/deermem/deermem/core/__init__.py>)
  - [`backend/packages/harness/deerflow/agents/memory/backends/deermem/deermem/core/llm.py`](<backend/packages/harness/deerflow/agents/memory/backends/deermem/deermem/core/llm.py>)
  - [`backend/packages/harness/deerflow/agents/memory/backends/deermem/deermem/core/message_processing.py`](<backend/packages/harness/deerflow/agents/memory/backends/deermem/deermem/core/message_processing.py>)
  - [`backend/packages/harness/deerflow/agents/memory/backends/deermem/deermem/core/paths.py`](<backend/packages/harness/deerflow/agents/memory/backends/deermem/deermem/core/paths.py>)
  - [`backend/packages/harness/deerflow/agents/memory/backends/deermem/deermem/core/prompt.py`](<backend/packages/harness/deerflow/agents/memory/backends/deermem/deermem/core/prompt.py>)
  - [`backend/packages/harness/deerflow/agents/memory/backends/deermem/deermem/core/queue.py`](<backend/packages/harness/deerflow/agents/memory/backends/deermem/deermem/core/queue.py>)
  - [`backend/packages/harness/deerflow/agents/memory/backends/deermem/deermem/core/storage.py`](<backend/packages/harness/deerflow/agents/memory/backends/deermem/deermem/core/storage.py>)
  - [`backend/packages/harness/deerflow/agents/memory/backends/deermem/deermem/core/updater.py`](<backend/packages/harness/deerflow/agents/memory/backends/deermem/deermem/core/updater.py>)
  - [`backend/packages/harness/deerflow/agents/memory/backends/noop/__init__.py`](<backend/packages/harness/deerflow/agents/memory/backends/noop/__init__.py>)
  - [`backend/packages/harness/deerflow/agents/memory/backends/noop/config.py`](<backend/packages/harness/deerflow/agents/memory/backends/noop/config.py>)
  - [`backend/packages/harness/deerflow/agents/memory/backends/noop/noop_manager.py`](<backend/packages/harness/deerflow/agents/memory/backends/noop/noop_manager.py>)
  - [`backend/packages/harness/deerflow/agents/memory/manager.py`](<backend/packages/harness/deerflow/agents/memory/manager.py>)
  - [`backend/packages/harness/deerflow/agents/memory/summarization_hook.py`](<backend/packages/harness/deerflow/agents/memory/summarization_hook.py>)
  - [`backend/packages/harness/deerflow/agents/memory/tools.py`](<backend/packages/harness/deerflow/agents/memory/tools.py>)

### 66. `backend/packages/harness/deerflow/agents`

- 作用：定义 Agent 工厂、线程状态、目标状态和人机交互协议。
- 阅读重点：理解 Agent 状态模型与功能开关。
- 文件：
  - [`backend/packages/harness/deerflow/agents/__init__.py`](<backend/packages/harness/deerflow/agents/__init__.py>)
  - [`backend/packages/harness/deerflow/agents/factory.py`](<backend/packages/harness/deerflow/agents/factory.py>)
  - [`backend/packages/harness/deerflow/agents/features.py`](<backend/packages/harness/deerflow/agents/features.py>)
  - [`backend/packages/harness/deerflow/agents/goal_state.py`](<backend/packages/harness/deerflow/agents/goal_state.py>)
  - [`backend/packages/harness/deerflow/agents/human_input.py`](<backend/packages/harness/deerflow/agents/human_input.py>)
  - [`backend/packages/harness/deerflow/agents/thread_state.py`](<backend/packages/harness/deerflow/agents/thread_state.py>)

### 67. `backend/packages/harness/deerflow/subagents`

- 作用：实现子 Agent 注册、执行、状态事件和令牌统计。
- 阅读重点：追踪主 Agent 委派任务后子任务如何运行并回传。
- 文件：
  - [`backend/packages/harness/deerflow/subagents/__init__.py`](<backend/packages/harness/deerflow/subagents/__init__.py>)
  - [`backend/packages/harness/deerflow/subagents/builtins/__init__.py`](<backend/packages/harness/deerflow/subagents/builtins/__init__.py>)
  - [`backend/packages/harness/deerflow/subagents/builtins/bash_agent.py`](<backend/packages/harness/deerflow/subagents/builtins/bash_agent.py>)
  - [`backend/packages/harness/deerflow/subagents/builtins/general_purpose.py`](<backend/packages/harness/deerflow/subagents/builtins/general_purpose.py>)
  - [`backend/packages/harness/deerflow/subagents/config.py`](<backend/packages/harness/deerflow/subagents/config.py>)
  - [`backend/packages/harness/deerflow/subagents/executor.py`](<backend/packages/harness/deerflow/subagents/executor.py>)
  - [`backend/packages/harness/deerflow/subagents/registry.py`](<backend/packages/harness/deerflow/subagents/registry.py>)
  - [`backend/packages/harness/deerflow/subagents/status_contract.py`](<backend/packages/harness/deerflow/subagents/status_contract.py>)
  - [`backend/packages/harness/deerflow/subagents/step_events.py`](<backend/packages/harness/deerflow/subagents/step_events.py>)
  - [`backend/packages/harness/deerflow/subagents/token_collector.py`](<backend/packages/harness/deerflow/subagents/token_collector.py>)

### 68. `backend/packages/harness/deerflow/tools/builtins`

- 作用：实现澄清、文件操作、任务调用等 Agent 内置工具。
- 阅读重点：从工具输入输出模型理解 Agent 与外部能力的边界。
- 文件：
  - [`backend/packages/harness/deerflow/tools/builtins/__init__.py`](<backend/packages/harness/deerflow/tools/builtins/__init__.py>)
  - [`backend/packages/harness/deerflow/tools/builtins/clarification_tool.py`](<backend/packages/harness/deerflow/tools/builtins/clarification_tool.py>)
  - [`backend/packages/harness/deerflow/tools/builtins/invoke_acp_agent_tool.py`](<backend/packages/harness/deerflow/tools/builtins/invoke_acp_agent_tool.py>)
  - [`backend/packages/harness/deerflow/tools/builtins/present_file_tool.py`](<backend/packages/harness/deerflow/tools/builtins/present_file_tool.py>)
  - [`backend/packages/harness/deerflow/tools/builtins/review_skill_package_tool.py`](<backend/packages/harness/deerflow/tools/builtins/review_skill_package_tool.py>)
  - [`backend/packages/harness/deerflow/tools/builtins/setup_agent_tool.py`](<backend/packages/harness/deerflow/tools/builtins/setup_agent_tool.py>)
  - [`backend/packages/harness/deerflow/tools/builtins/task_tool.py`](<backend/packages/harness/deerflow/tools/builtins/task_tool.py>)
  - [`backend/packages/harness/deerflow/tools/builtins/tool_search.py`](<backend/packages/harness/deerflow/tools/builtins/tool_search.py>)
  - [`backend/packages/harness/deerflow/tools/builtins/update_agent_tool.py`](<backend/packages/harness/deerflow/tools/builtins/update_agent_tool.py>)
  - [`backend/packages/harness/deerflow/tools/builtins/view_image_tool.py`](<backend/packages/harness/deerflow/tools/builtins/view_image_tool.py>)

### 69. `backend/packages/harness/deerflow/tools/__init__.py`

- 作用：定义工具注册、搜索、错误处理和通用工具协议。
- 阅读重点：从工具输入输出模型理解 Agent 与外部能力的边界。
- 文件：
  - [`backend/packages/harness/deerflow/tools/__init__.py`](<backend/packages/harness/deerflow/tools/__init__.py>)

### 70. `backend/packages/harness/deerflow/tools/mcp_metadata.py`

- 作用：定义工具注册、搜索、错误处理和通用工具协议。
- 阅读重点：从工具输入输出模型理解 Agent 与外部能力的边界。
- 文件：
  - [`backend/packages/harness/deerflow/tools/mcp_metadata.py`](<backend/packages/harness/deerflow/tools/mcp_metadata.py>)

### 71. `backend/packages/harness/deerflow/tools/skill_manage_tool.py`

- 作用：定义工具注册、搜索、错误处理和通用工具协议。
- 阅读重点：从工具输入输出模型理解 Agent 与外部能力的边界。
- 文件：
  - [`backend/packages/harness/deerflow/tools/skill_manage_tool.py`](<backend/packages/harness/deerflow/tools/skill_manage_tool.py>)

### 72. `backend/packages/harness/deerflow/tools/sync.py`

- 作用：定义工具注册、搜索、错误处理和通用工具协议。
- 阅读重点：从工具输入输出模型理解 Agent 与外部能力的边界。
- 文件：
  - [`backend/packages/harness/deerflow/tools/sync.py`](<backend/packages/harness/deerflow/tools/sync.py>)

### 73. `backend/packages/harness/deerflow/tools/tools.py`

- 作用：定义工具注册、搜索、错误处理和通用工具协议。
- 阅读重点：从工具输入输出模型理解 Agent 与外部能力的边界。
- 文件：
  - [`backend/packages/harness/deerflow/tools/tools.py`](<backend/packages/harness/deerflow/tools/tools.py>)

### 74. `backend/packages/harness/deerflow/tools/types.py`

- 作用：定义工具注册、搜索、错误处理和通用工具协议。
- 阅读重点：从工具输入输出模型理解 Agent 与外部能力的边界。
- 文件：
  - [`backend/packages/harness/deerflow/tools/types.py`](<backend/packages/harness/deerflow/tools/types.py>)

### 75. `backend/packages/harness/deerflow/runtime/__init__.py`

- 作用：实现 Agent 运行时的“__init__.py”基础能力。
- 阅读重点：关注并发运行、事件持久化、检查点和流式输出之间的协作。
- 文件：
  - [`backend/packages/harness/deerflow/runtime/__init__.py`](<backend/packages/harness/deerflow/runtime/__init__.py>)

### 76. `backend/packages/harness/deerflow/runtime/context_compaction.py`

- 作用：实现 Agent 运行时的“context_compaction.py”基础能力。
- 阅读重点：关注并发运行、事件持久化、检查点和流式输出之间的协作。
- 文件：
  - [`backend/packages/harness/deerflow/runtime/context_compaction.py`](<backend/packages/harness/deerflow/runtime/context_compaction.py>)

### 77. `backend/packages/harness/deerflow/runtime/context_keys.py`

- 作用：实现 Agent 运行时的“context_keys.py”基础能力。
- 阅读重点：关注并发运行、事件持久化、检查点和流式输出之间的协作。
- 文件：
  - [`backend/packages/harness/deerflow/runtime/context_keys.py`](<backend/packages/harness/deerflow/runtime/context_keys.py>)

### 78. `backend/packages/harness/deerflow/runtime/converters.py`

- 作用：实现 Agent 运行时的“converters.py”基础能力。
- 阅读重点：关注并发运行、事件持久化、检查点和流式输出之间的协作。
- 文件：
  - [`backend/packages/harness/deerflow/runtime/converters.py`](<backend/packages/harness/deerflow/runtime/converters.py>)

### 79. `backend/packages/harness/deerflow/runtime/goal.py`

- 作用：实现 Agent 运行时的“goal.py”基础能力。
- 阅读重点：关注并发运行、事件持久化、检查点和流式输出之间的协作。
- 文件：
  - [`backend/packages/harness/deerflow/runtime/goal.py`](<backend/packages/harness/deerflow/runtime/goal.py>)

### 80. `backend/packages/harness/deerflow/runtime/journal.py`

- 作用：实现 Agent 运行时的“journal.py”基础能力。
- 阅读重点：关注并发运行、事件持久化、检查点和流式输出之间的协作。
- 文件：
  - [`backend/packages/harness/deerflow/runtime/journal.py`](<backend/packages/harness/deerflow/runtime/journal.py>)

### 81. `backend/packages/harness/deerflow/runtime/secret_context.py`

- 作用：实现 Agent 运行时的“secret_context.py”基础能力。
- 阅读重点：关注并发运行、事件持久化、检查点和流式输出之间的协作。
- 文件：
  - [`backend/packages/harness/deerflow/runtime/secret_context.py`](<backend/packages/harness/deerflow/runtime/secret_context.py>)

### 82. `backend/packages/harness/deerflow/runtime/serialization.py`

- 作用：实现 Agent 运行时的“serialization.py”基础能力。
- 阅读重点：关注并发运行、事件持久化、检查点和流式输出之间的协作。
- 文件：
  - [`backend/packages/harness/deerflow/runtime/serialization.py`](<backend/packages/harness/deerflow/runtime/serialization.py>)

### 83. `backend/packages/harness/deerflow/runtime/user_context.py`

- 作用：实现 Agent 运行时的“user_context.py”基础能力。
- 阅读重点：关注并发运行、事件持久化、检查点和流式输出之间的协作。
- 文件：
  - [`backend/packages/harness/deerflow/runtime/user_context.py`](<backend/packages/harness/deerflow/runtime/user_context.py>)

### 84. `backend/packages/harness/deerflow/runtime/runs`

- 作用：实现 Agent 运行时的“runs”基础能力。
- 阅读重点：关注并发运行、事件持久化、检查点和流式输出之间的协作。
- 文件：
  - [`backend/packages/harness/deerflow/runtime/runs/__init__.py`](<backend/packages/harness/deerflow/runtime/runs/__init__.py>)
  - [`backend/packages/harness/deerflow/runtime/runs/manager.py`](<backend/packages/harness/deerflow/runtime/runs/manager.py>)
  - [`backend/packages/harness/deerflow/runtime/runs/naming.py`](<backend/packages/harness/deerflow/runtime/runs/naming.py>)
  - [`backend/packages/harness/deerflow/runtime/runs/schemas.py`](<backend/packages/harness/deerflow/runtime/runs/schemas.py>)
  - [`backend/packages/harness/deerflow/runtime/runs/store/__init__.py`](<backend/packages/harness/deerflow/runtime/runs/store/__init__.py>)
  - [`backend/packages/harness/deerflow/runtime/runs/store/base.py`](<backend/packages/harness/deerflow/runtime/runs/store/base.py>)
  - [`backend/packages/harness/deerflow/runtime/runs/store/memory.py`](<backend/packages/harness/deerflow/runtime/runs/store/memory.py>)
  - [`backend/packages/harness/deerflow/runtime/runs/worker.py`](<backend/packages/harness/deerflow/runtime/runs/worker.py>)

### 85. `backend/packages/harness/deerflow/runtime/events`

- 作用：实现 Agent 运行时的“events”基础能力。
- 阅读重点：关注并发运行、事件持久化、检查点和流式输出之间的协作。
- 文件：
  - [`backend/packages/harness/deerflow/runtime/events/__init__.py`](<backend/packages/harness/deerflow/runtime/events/__init__.py>)
  - [`backend/packages/harness/deerflow/runtime/events/store/__init__.py`](<backend/packages/harness/deerflow/runtime/events/store/__init__.py>)
  - [`backend/packages/harness/deerflow/runtime/events/store/base.py`](<backend/packages/harness/deerflow/runtime/events/store/base.py>)
  - [`backend/packages/harness/deerflow/runtime/events/store/db.py`](<backend/packages/harness/deerflow/runtime/events/store/db.py>)
  - [`backend/packages/harness/deerflow/runtime/events/store/jsonl.py`](<backend/packages/harness/deerflow/runtime/events/store/jsonl.py>)
  - [`backend/packages/harness/deerflow/runtime/events/store/memory.py`](<backend/packages/harness/deerflow/runtime/events/store/memory.py>)

### 86. `backend/packages/harness/deerflow/runtime/checkpointer`

- 作用：实现 Agent 运行时的“checkpointer”基础能力。
- 阅读重点：关注并发运行、事件持久化、检查点和流式输出之间的协作。
- 文件：
  - [`backend/packages/harness/deerflow/runtime/checkpointer/__init__.py`](<backend/packages/harness/deerflow/runtime/checkpointer/__init__.py>)
  - [`backend/packages/harness/deerflow/runtime/checkpointer/async_provider.py`](<backend/packages/harness/deerflow/runtime/checkpointer/async_provider.py>)
  - [`backend/packages/harness/deerflow/runtime/checkpointer/provider.py`](<backend/packages/harness/deerflow/runtime/checkpointer/provider.py>)

### 87. `backend/packages/harness/deerflow/runtime/store`

- 作用：实现 Agent 运行时的“store”基础能力。
- 阅读重点：关注并发运行、事件持久化、检查点和流式输出之间的协作。
- 文件：
  - [`backend/packages/harness/deerflow/runtime/store/__init__.py`](<backend/packages/harness/deerflow/runtime/store/__init__.py>)
  - [`backend/packages/harness/deerflow/runtime/store/_sqlite_utils.py`](<backend/packages/harness/deerflow/runtime/store/_sqlite_utils.py>)
  - [`backend/packages/harness/deerflow/runtime/store/async_provider.py`](<backend/packages/harness/deerflow/runtime/store/async_provider.py>)
  - [`backend/packages/harness/deerflow/runtime/store/provider.py`](<backend/packages/harness/deerflow/runtime/store/provider.py>)

### 88. `backend/packages/harness/deerflow/runtime/stream_bridge`

- 作用：实现 Agent 运行时的“stream_bridge”基础能力。
- 阅读重点：关注并发运行、事件持久化、检查点和流式输出之间的协作。
- 文件：
  - [`backend/packages/harness/deerflow/runtime/stream_bridge/__init__.py`](<backend/packages/harness/deerflow/runtime/stream_bridge/__init__.py>)
  - [`backend/packages/harness/deerflow/runtime/stream_bridge/async_provider.py`](<backend/packages/harness/deerflow/runtime/stream_bridge/async_provider.py>)
  - [`backend/packages/harness/deerflow/runtime/stream_bridge/base.py`](<backend/packages/harness/deerflow/runtime/stream_bridge/base.py>)
  - [`backend/packages/harness/deerflow/runtime/stream_bridge/memory.py`](<backend/packages/harness/deerflow/runtime/stream_bridge/memory.py>)
  - [`backend/packages/harness/deerflow/runtime/stream_bridge/redis.py`](<backend/packages/harness/deerflow/runtime/stream_bridge/redis.py>)

### 89. `backend/packages/harness/deerflow/sandbox/local`

- 作用：实现本地沙箱的文件系统与进程执行。
- 阅读重点：先读抽象接口和安全规则，再读具体 Provider。
- 文件：
  - [`backend/packages/harness/deerflow/sandbox/local/__init__.py`](<backend/packages/harness/deerflow/sandbox/local/__init__.py>)
  - [`backend/packages/harness/deerflow/sandbox/local/list_dir.py`](<backend/packages/harness/deerflow/sandbox/local/list_dir.py>)
  - [`backend/packages/harness/deerflow/sandbox/local/local_sandbox_provider.py`](<backend/packages/harness/deerflow/sandbox/local/local_sandbox_provider.py>)
  - [`backend/packages/harness/deerflow/sandbox/local/local_sandbox.py`](<backend/packages/harness/deerflow/sandbox/local/local_sandbox.py>)

### 90. `backend/packages/harness/deerflow/sandbox/__init__.py`

- 作用：定义沙箱接口、安全策略、路径规则和文件搜索工具。
- 阅读重点：先读抽象接口和安全规则，再读具体 Provider。
- 文件：
  - [`backend/packages/harness/deerflow/sandbox/__init__.py`](<backend/packages/harness/deerflow/sandbox/__init__.py>)

### 91. `backend/packages/harness/deerflow/sandbox/env_policy.py`

- 作用：定义沙箱接口、安全策略、路径规则和文件搜索工具。
- 阅读重点：先读抽象接口和安全规则，再读具体 Provider。
- 文件：
  - [`backend/packages/harness/deerflow/sandbox/env_policy.py`](<backend/packages/harness/deerflow/sandbox/env_policy.py>)

### 92. `backend/packages/harness/deerflow/sandbox/exceptions.py`

- 作用：定义沙箱接口、安全策略、路径规则和文件搜索工具。
- 阅读重点：先读抽象接口和安全规则，再读具体 Provider。
- 文件：
  - [`backend/packages/harness/deerflow/sandbox/exceptions.py`](<backend/packages/harness/deerflow/sandbox/exceptions.py>)

### 93. `backend/packages/harness/deerflow/sandbox/file_operation_lock.py`

- 作用：定义沙箱接口、安全策略、路径规则和文件搜索工具。
- 阅读重点：先读抽象接口和安全规则，再读具体 Provider。
- 文件：
  - [`backend/packages/harness/deerflow/sandbox/file_operation_lock.py`](<backend/packages/harness/deerflow/sandbox/file_operation_lock.py>)

### 94. `backend/packages/harness/deerflow/sandbox/middleware.py`

- 作用：定义沙箱接口、安全策略、路径规则和文件搜索工具。
- 阅读重点：先读抽象接口和安全规则，再读具体 Provider。
- 文件：
  - [`backend/packages/harness/deerflow/sandbox/middleware.py`](<backend/packages/harness/deerflow/sandbox/middleware.py>)

### 95. `backend/packages/harness/deerflow/sandbox/path_patterns.py`

- 作用：定义沙箱接口、安全策略、路径规则和文件搜索工具。
- 阅读重点：先读抽象接口和安全规则，再读具体 Provider。
- 文件：
  - [`backend/packages/harness/deerflow/sandbox/path_patterns.py`](<backend/packages/harness/deerflow/sandbox/path_patterns.py>)

### 96. `backend/packages/harness/deerflow/sandbox/sandbox_provider.py`

- 作用：定义沙箱接口、安全策略、路径规则和文件搜索工具。
- 阅读重点：先读抽象接口和安全规则，再读具体 Provider。
- 文件：
  - [`backend/packages/harness/deerflow/sandbox/sandbox_provider.py`](<backend/packages/harness/deerflow/sandbox/sandbox_provider.py>)

### 97. `backend/packages/harness/deerflow/sandbox/sandbox.py`

- 作用：定义沙箱接口、安全策略、路径规则和文件搜索工具。
- 阅读重点：先读抽象接口和安全规则，再读具体 Provider。
- 文件：
  - [`backend/packages/harness/deerflow/sandbox/sandbox.py`](<backend/packages/harness/deerflow/sandbox/sandbox.py>)

### 98. `backend/packages/harness/deerflow/sandbox/search.py`

- 作用：定义沙箱接口、安全策略、路径规则和文件搜索工具。
- 阅读重点：先读抽象接口和安全规则，再读具体 Provider。
- 文件：
  - [`backend/packages/harness/deerflow/sandbox/search.py`](<backend/packages/harness/deerflow/sandbox/search.py>)

### 99. `backend/packages/harness/deerflow/sandbox/security.py`

- 作用：定义沙箱接口、安全策略、路径规则和文件搜索工具。
- 阅读重点：先读抽象接口和安全规则，再读具体 Provider。
- 文件：
  - [`backend/packages/harness/deerflow/sandbox/security.py`](<backend/packages/harness/deerflow/sandbox/security.py>)

### 100. `backend/packages/harness/deerflow/sandbox/tools.py`

- 作用：定义沙箱接口、安全策略、路径规则和文件搜索工具。
- 阅读重点：先读抽象接口和安全规则，再读具体 Provider。
- 文件：
  - [`backend/packages/harness/deerflow/sandbox/tools.py`](<backend/packages/harness/deerflow/sandbox/tools.py>)

## 第四阶段：配置、存储、安全与外部适配

### 101. `backend/packages/harness/deerflow/config`

- 作用：集中定义模型、工具、沙箱、记忆、渠道和运行时配置模型。
- 阅读重点：把各配置类与 config.example.yaml 对照阅读。
- 文件：
  - [`backend/packages/harness/deerflow/config/__init__.py`](<backend/packages/harness/deerflow/config/__init__.py>)
  - [`backend/packages/harness/deerflow/config/acp_config.py`](<backend/packages/harness/deerflow/config/acp_config.py>)
  - [`backend/packages/harness/deerflow/config/agents_api_config.py`](<backend/packages/harness/deerflow/config/agents_api_config.py>)
  - [`backend/packages/harness/deerflow/config/agents_config.py`](<backend/packages/harness/deerflow/config/agents_config.py>)
  - [`backend/packages/harness/deerflow/config/app_config.py`](<backend/packages/harness/deerflow/config/app_config.py>)
  - [`backend/packages/harness/deerflow/config/auth_config.py`](<backend/packages/harness/deerflow/config/auth_config.py>)
  - [`backend/packages/harness/deerflow/config/authorization_config.py`](<backend/packages/harness/deerflow/config/authorization_config.py>)
  - [`backend/packages/harness/deerflow/config/channel_connections_config.py`](<backend/packages/harness/deerflow/config/channel_connections_config.py>)
  - [`backend/packages/harness/deerflow/config/checkpointer_config.py`](<backend/packages/harness/deerflow/config/checkpointer_config.py>)
  - [`backend/packages/harness/deerflow/config/database_config.py`](<backend/packages/harness/deerflow/config/database_config.py>)
  - [`backend/packages/harness/deerflow/config/extensions_config.py`](<backend/packages/harness/deerflow/config/extensions_config.py>)
  - [`backend/packages/harness/deerflow/config/guardrails_config.py`](<backend/packages/harness/deerflow/config/guardrails_config.py>)
  - [`backend/packages/harness/deerflow/config/input_polish_config.py`](<backend/packages/harness/deerflow/config/input_polish_config.py>)
  - [`backend/packages/harness/deerflow/config/loop_detection_config.py`](<backend/packages/harness/deerflow/config/loop_detection_config.py>)
  - [`backend/packages/harness/deerflow/config/memory_config.py`](<backend/packages/harness/deerflow/config/memory_config.py>)
  - [`backend/packages/harness/deerflow/config/model_config.py`](<backend/packages/harness/deerflow/config/model_config.py>)
  - [`backend/packages/harness/deerflow/config/paths.py`](<backend/packages/harness/deerflow/config/paths.py>)
  - [`backend/packages/harness/deerflow/config/read_before_write_config.py`](<backend/packages/harness/deerflow/config/read_before_write_config.py>)
  - [`backend/packages/harness/deerflow/config/reload_boundary.py`](<backend/packages/harness/deerflow/config/reload_boundary.py>)
  - [`backend/packages/harness/deerflow/config/run_events_config.py`](<backend/packages/harness/deerflow/config/run_events_config.py>)
  - [`backend/packages/harness/deerflow/config/run_ownership_config.py`](<backend/packages/harness/deerflow/config/run_ownership_config.py>)
  - [`backend/packages/harness/deerflow/config/runtime_paths.py`](<backend/packages/harness/deerflow/config/runtime_paths.py>)
  - [`backend/packages/harness/deerflow/config/safety_finish_reason_config.py`](<backend/packages/harness/deerflow/config/safety_finish_reason_config.py>)
  - [`backend/packages/harness/deerflow/config/sandbox_config.py`](<backend/packages/harness/deerflow/config/sandbox_config.py>)
  - [`backend/packages/harness/deerflow/config/scheduler_config.py`](<backend/packages/harness/deerflow/config/scheduler_config.py>)
  - [`backend/packages/harness/deerflow/config/skill_evolution_config.py`](<backend/packages/harness/deerflow/config/skill_evolution_config.py>)
  - [`backend/packages/harness/deerflow/config/skill_scan_config.py`](<backend/packages/harness/deerflow/config/skill_scan_config.py>)
  - [`backend/packages/harness/deerflow/config/skills_config.py`](<backend/packages/harness/deerflow/config/skills_config.py>)
  - [`backend/packages/harness/deerflow/config/stream_bridge_config.py`](<backend/packages/harness/deerflow/config/stream_bridge_config.py>)
  - [`backend/packages/harness/deerflow/config/subagents_config.py`](<backend/packages/harness/deerflow/config/subagents_config.py>)
  - [`backend/packages/harness/deerflow/config/suggestions_config.py`](<backend/packages/harness/deerflow/config/suggestions_config.py>)
  - [`backend/packages/harness/deerflow/config/summarization_config.py`](<backend/packages/harness/deerflow/config/summarization_config.py>)
  - [`backend/packages/harness/deerflow/config/title_config.py`](<backend/packages/harness/deerflow/config/title_config.py>)
  - [`backend/packages/harness/deerflow/config/token_budget_config.py`](<backend/packages/harness/deerflow/config/token_budget_config.py>)
  - [`backend/packages/harness/deerflow/config/token_usage_config.py`](<backend/packages/harness/deerflow/config/token_usage_config.py>)
  - [`backend/packages/harness/deerflow/config/tool_config.py`](<backend/packages/harness/deerflow/config/tool_config.py>)
  - [`backend/packages/harness/deerflow/config/tool_output_config.py`](<backend/packages/harness/deerflow/config/tool_output_config.py>)
  - [`backend/packages/harness/deerflow/config/tool_progress_config.py`](<backend/packages/harness/deerflow/config/tool_progress_config.py>)
  - [`backend/packages/harness/deerflow/config/tool_search_config.py`](<backend/packages/harness/deerflow/config/tool_search_config.py>)
  - [`backend/packages/harness/deerflow/config/tracing_config.py`](<backend/packages/harness/deerflow/config/tracing_config.py>)

### 102. `backend/packages/harness/deerflow/persistence/__init__.py`

- 作用：实现持久化层的 __init__.py 数据仓储。
- 阅读重点：先读模型和仓储接口，再读 SQL 实现与迁移。
- 文件：
  - [`backend/packages/harness/deerflow/persistence/__init__.py`](<backend/packages/harness/deerflow/persistence/__init__.py>)

### 103. `backend/packages/harness/deerflow/persistence/base.py`

- 作用：实现持久化层的 base.py 数据仓储。
- 阅读重点：先读模型和仓储接口，再读 SQL 实现与迁移。
- 文件：
  - [`backend/packages/harness/deerflow/persistence/base.py`](<backend/packages/harness/deerflow/persistence/base.py>)

### 104. `backend/packages/harness/deerflow/persistence/bootstrap.py`

- 作用：实现持久化层的 bootstrap.py 数据仓储。
- 阅读重点：先读模型和仓储接口，再读 SQL 实现与迁移。
- 文件：
  - [`backend/packages/harness/deerflow/persistence/bootstrap.py`](<backend/packages/harness/deerflow/persistence/bootstrap.py>)

### 105. `backend/packages/harness/deerflow/persistence/channel_connections`

- 作用：实现持久化层的 channel_connections 数据仓储。
- 阅读重点：先读模型和仓储接口，再读 SQL 实现与迁移。
- 文件：
  - [`backend/packages/harness/deerflow/persistence/channel_connections/__init__.py`](<backend/packages/harness/deerflow/persistence/channel_connections/__init__.py>)
  - [`backend/packages/harness/deerflow/persistence/channel_connections/model.py`](<backend/packages/harness/deerflow/persistence/channel_connections/model.py>)
  - [`backend/packages/harness/deerflow/persistence/channel_connections/sql.py`](<backend/packages/harness/deerflow/persistence/channel_connections/sql.py>)

### 106. `backend/packages/harness/deerflow/persistence/engine.py`

- 作用：实现持久化层的 engine.py 数据仓储。
- 阅读重点：先读模型和仓储接口，再读 SQL 实现与迁移。
- 文件：
  - [`backend/packages/harness/deerflow/persistence/engine.py`](<backend/packages/harness/deerflow/persistence/engine.py>)

### 107. `backend/packages/harness/deerflow/persistence/feedback`

- 作用：实现持久化层的 feedback 数据仓储。
- 阅读重点：先读模型和仓储接口，再读 SQL 实现与迁移。
- 文件：
  - [`backend/packages/harness/deerflow/persistence/feedback/__init__.py`](<backend/packages/harness/deerflow/persistence/feedback/__init__.py>)
  - [`backend/packages/harness/deerflow/persistence/feedback/model.py`](<backend/packages/harness/deerflow/persistence/feedback/model.py>)
  - [`backend/packages/harness/deerflow/persistence/feedback/sql.py`](<backend/packages/harness/deerflow/persistence/feedback/sql.py>)

### 108. `backend/packages/harness/deerflow/persistence/json_compat.py`

- 作用：实现持久化层的 json_compat.py 数据仓储。
- 阅读重点：先读模型和仓储接口，再读 SQL 实现与迁移。
- 文件：
  - [`backend/packages/harness/deerflow/persistence/json_compat.py`](<backend/packages/harness/deerflow/persistence/json_compat.py>)

### 109. `backend/packages/harness/deerflow/persistence/migrations`

- 作用：实现持久化层的 数据库迁移。
- 阅读重点：先读模型和仓储接口，再读 SQL 实现与迁移。
- 文件：
  - [`backend/packages/harness/deerflow/persistence/migrations/_env_filters.py`](<backend/packages/harness/deerflow/persistence/migrations/_env_filters.py>)
  - [`backend/packages/harness/deerflow/persistence/migrations/_helpers.py`](<backend/packages/harness/deerflow/persistence/migrations/_helpers.py>)
  - [`backend/packages/harness/deerflow/persistence/migrations/env.py`](<backend/packages/harness/deerflow/persistence/migrations/env.py>)
  - [`backend/packages/harness/deerflow/persistence/migrations/script.py.mako`](<backend/packages/harness/deerflow/persistence/migrations/script.py.mako>)
  - [`backend/packages/harness/deerflow/persistence/migrations/versions/0001_baseline.py`](<backend/packages/harness/deerflow/persistence/migrations/versions/0001_baseline.py>)
  - [`backend/packages/harness/deerflow/persistence/migrations/versions/0002_runs_token_usage.py`](<backend/packages/harness/deerflow/persistence/migrations/versions/0002_runs_token_usage.py>)
  - [`backend/packages/harness/deerflow/persistence/migrations/versions/0003_scheduled_tasks.py`](<backend/packages/harness/deerflow/persistence/migrations/versions/0003_scheduled_tasks.py>)
  - [`backend/packages/harness/deerflow/persistence/migrations/versions/0004_run_ownership.py`](<backend/packages/harness/deerflow/persistence/migrations/versions/0004_run_ownership.py>)
  - [`backend/packages/harness/deerflow/persistence/migrations/versions/0005_run_stop_reason.py`](<backend/packages/harness/deerflow/persistence/migrations/versions/0005_run_stop_reason.py>)

### 110. `backend/packages/harness/deerflow/persistence/models`

- 作用：实现持久化层的 models 数据仓储。
- 阅读重点：先读模型和仓储接口，再读 SQL 实现与迁移。
- 文件：
  - [`backend/packages/harness/deerflow/persistence/models/__init__.py`](<backend/packages/harness/deerflow/persistence/models/__init__.py>)
  - [`backend/packages/harness/deerflow/persistence/models/run_event.py`](<backend/packages/harness/deerflow/persistence/models/run_event.py>)

### 111. `backend/packages/harness/deerflow/persistence/run`

- 作用：实现持久化层的 run 数据仓储。
- 阅读重点：先读模型和仓储接口，再读 SQL 实现与迁移。
- 文件：
  - [`backend/packages/harness/deerflow/persistence/run/__init__.py`](<backend/packages/harness/deerflow/persistence/run/__init__.py>)
  - [`backend/packages/harness/deerflow/persistence/run/model.py`](<backend/packages/harness/deerflow/persistence/run/model.py>)
  - [`backend/packages/harness/deerflow/persistence/run/sql.py`](<backend/packages/harness/deerflow/persistence/run/sql.py>)

### 112. `backend/packages/harness/deerflow/persistence/scheduled_task_runs`

- 作用：实现持久化层的 scheduled_task_runs 数据仓储。
- 阅读重点：先读模型和仓储接口，再读 SQL 实现与迁移。
- 文件：
  - [`backend/packages/harness/deerflow/persistence/scheduled_task_runs/__init__.py`](<backend/packages/harness/deerflow/persistence/scheduled_task_runs/__init__.py>)
  - [`backend/packages/harness/deerflow/persistence/scheduled_task_runs/model.py`](<backend/packages/harness/deerflow/persistence/scheduled_task_runs/model.py>)
  - [`backend/packages/harness/deerflow/persistence/scheduled_task_runs/sql.py`](<backend/packages/harness/deerflow/persistence/scheduled_task_runs/sql.py>)

### 113. `backend/packages/harness/deerflow/persistence/scheduled_tasks`

- 作用：实现持久化层的 scheduled_tasks 数据仓储。
- 阅读重点：先读模型和仓储接口，再读 SQL 实现与迁移。
- 文件：
  - [`backend/packages/harness/deerflow/persistence/scheduled_tasks/__init__.py`](<backend/packages/harness/deerflow/persistence/scheduled_tasks/__init__.py>)
  - [`backend/packages/harness/deerflow/persistence/scheduled_tasks/model.py`](<backend/packages/harness/deerflow/persistence/scheduled_tasks/model.py>)
  - [`backend/packages/harness/deerflow/persistence/scheduled_tasks/sql.py`](<backend/packages/harness/deerflow/persistence/scheduled_tasks/sql.py>)

### 114. `backend/packages/harness/deerflow/persistence/thread_meta`

- 作用：实现持久化层的 thread_meta 数据仓储。
- 阅读重点：先读模型和仓储接口，再读 SQL 实现与迁移。
- 文件：
  - [`backend/packages/harness/deerflow/persistence/thread_meta/__init__.py`](<backend/packages/harness/deerflow/persistence/thread_meta/__init__.py>)
  - [`backend/packages/harness/deerflow/persistence/thread_meta/base.py`](<backend/packages/harness/deerflow/persistence/thread_meta/base.py>)
  - [`backend/packages/harness/deerflow/persistence/thread_meta/memory.py`](<backend/packages/harness/deerflow/persistence/thread_meta/memory.py>)
  - [`backend/packages/harness/deerflow/persistence/thread_meta/model.py`](<backend/packages/harness/deerflow/persistence/thread_meta/model.py>)
  - [`backend/packages/harness/deerflow/persistence/thread_meta/sql.py`](<backend/packages/harness/deerflow/persistence/thread_meta/sql.py>)

### 115. `backend/packages/harness/deerflow/persistence/user`

- 作用：实现持久化层的 user 数据仓储。
- 阅读重点：先读模型和仓储接口，再读 SQL 实现与迁移。
- 文件：
  - [`backend/packages/harness/deerflow/persistence/user/__init__.py`](<backend/packages/harness/deerflow/persistence/user/__init__.py>)
  - [`backend/packages/harness/deerflow/persistence/user/model.py`](<backend/packages/harness/deerflow/persistence/user/model.py>)

### 116. `backend/packages/harness/deerflow/models`

- 作用：适配 OpenAI、Claude、vLLM 等模型提供商并处理凭证与兼容差异。
- 阅读重点：从 factory 和 credential loader 进入，再看各 Provider 补丁。
- 文件：
  - [`backend/packages/harness/deerflow/models/__init__.py`](<backend/packages/harness/deerflow/models/__init__.py>)
  - [`backend/packages/harness/deerflow/models/assistant_payload_replay.py`](<backend/packages/harness/deerflow/models/assistant_payload_replay.py>)
  - [`backend/packages/harness/deerflow/models/claude_provider.py`](<backend/packages/harness/deerflow/models/claude_provider.py>)
  - [`backend/packages/harness/deerflow/models/credential_loader.py`](<backend/packages/harness/deerflow/models/credential_loader.py>)
  - [`backend/packages/harness/deerflow/models/factory.py`](<backend/packages/harness/deerflow/models/factory.py>)
  - [`backend/packages/harness/deerflow/models/mindie_provider.py`](<backend/packages/harness/deerflow/models/mindie_provider.py>)
  - [`backend/packages/harness/deerflow/models/openai_codex_provider.py`](<backend/packages/harness/deerflow/models/openai_codex_provider.py>)
  - [`backend/packages/harness/deerflow/models/patched_deepseek.py`](<backend/packages/harness/deerflow/models/patched_deepseek.py>)
  - [`backend/packages/harness/deerflow/models/patched_mimo.py`](<backend/packages/harness/deerflow/models/patched_mimo.py>)
  - [`backend/packages/harness/deerflow/models/patched_minimax.py`](<backend/packages/harness/deerflow/models/patched_minimax.py>)
  - [`backend/packages/harness/deerflow/models/patched_openai.py`](<backend/packages/harness/deerflow/models/patched_openai.py>)
  - [`backend/packages/harness/deerflow/models/patched_stepfun.py`](<backend/packages/harness/deerflow/models/patched_stepfun.py>)
  - [`backend/packages/harness/deerflow/models/vllm_provider.py`](<backend/packages/harness/deerflow/models/vllm_provider.py>)

### 117. `backend/packages/harness/deerflow/mcp`

- 作用：实现 MCP 客户端、OAuth、连接池和工具转换。
- 阅读重点：关注会话生命周期、缓存和 MCP 工具暴露策略。
- 文件：
  - [`backend/packages/harness/deerflow/mcp/__init__.py`](<backend/packages/harness/deerflow/mcp/__init__.py>)
  - [`backend/packages/harness/deerflow/mcp/cache.py`](<backend/packages/harness/deerflow/mcp/cache.py>)
  - [`backend/packages/harness/deerflow/mcp/client.py`](<backend/packages/harness/deerflow/mcp/client.py>)
  - [`backend/packages/harness/deerflow/mcp/oauth.py`](<backend/packages/harness/deerflow/mcp/oauth.py>)
  - [`backend/packages/harness/deerflow/mcp/session_pool.py`](<backend/packages/harness/deerflow/mcp/session_pool.py>)
  - [`backend/packages/harness/deerflow/mcp/tools.py`](<backend/packages/harness/deerflow/mcp/tools.py>)

### 118. `backend/packages/harness/deerflow/skills/__init__.py`

- 作用：实现技能系统的目录、解析、安装与权限能力。
- 阅读重点：理解技能从发现、校验、安装到运行时激活的完整路径。
- 文件：
  - [`backend/packages/harness/deerflow/skills/__init__.py`](<backend/packages/harness/deerflow/skills/__init__.py>)

### 119. `backend/packages/harness/deerflow/skills/catalog.py`

- 作用：实现技能系统的目录、解析、安装与权限能力。
- 阅读重点：理解技能从发现、校验、安装到运行时激活的完整路径。
- 文件：
  - [`backend/packages/harness/deerflow/skills/catalog.py`](<backend/packages/harness/deerflow/skills/catalog.py>)

### 120. `backend/packages/harness/deerflow/skills/describe.py`

- 作用：实现技能系统的目录、解析、安装与权限能力。
- 阅读重点：理解技能从发现、校验、安装到运行时激活的完整路径。
- 文件：
  - [`backend/packages/harness/deerflow/skills/describe.py`](<backend/packages/harness/deerflow/skills/describe.py>)

### 121. `backend/packages/harness/deerflow/skills/frontmatter.py`

- 作用：实现技能系统的目录、解析、安装与权限能力。
- 阅读重点：理解技能从发现、校验、安装到运行时激活的完整路径。
- 文件：
  - [`backend/packages/harness/deerflow/skills/frontmatter.py`](<backend/packages/harness/deerflow/skills/frontmatter.py>)

### 122. `backend/packages/harness/deerflow/skills/installer.py`

- 作用：实现技能系统的目录、解析、安装与权限能力。
- 阅读重点：理解技能从发现、校验、安装到运行时激活的完整路径。
- 文件：
  - [`backend/packages/harness/deerflow/skills/installer.py`](<backend/packages/harness/deerflow/skills/installer.py>)

### 123. `backend/packages/harness/deerflow/skills/package_paths.py`

- 作用：实现技能系统的目录、解析、安装与权限能力。
- 阅读重点：理解技能从发现、校验、安装到运行时激活的完整路径。
- 文件：
  - [`backend/packages/harness/deerflow/skills/package_paths.py`](<backend/packages/harness/deerflow/skills/package_paths.py>)

### 124. `backend/packages/harness/deerflow/skills/parser.py`

- 作用：实现技能系统的目录、解析、安装与权限能力。
- 阅读重点：理解技能从发现、校验、安装到运行时激活的完整路径。
- 文件：
  - [`backend/packages/harness/deerflow/skills/parser.py`](<backend/packages/harness/deerflow/skills/parser.py>)

### 125. `backend/packages/harness/deerflow/skills/permissions.py`

- 作用：实现技能系统的目录、解析、安装与权限能力。
- 阅读重点：理解技能从发现、校验、安装到运行时激活的完整路径。
- 文件：
  - [`backend/packages/harness/deerflow/skills/permissions.py`](<backend/packages/harness/deerflow/skills/permissions.py>)

### 126. `backend/packages/harness/deerflow/skills/review`

- 作用：实现技能系统的质量评审能力。
- 阅读重点：理解技能从发现、校验、安装到运行时激活的完整路径。
- 文件：
  - [`backend/packages/harness/deerflow/skills/review/__init__.py`](<backend/packages/harness/deerflow/skills/review/__init__.py>)
  - [`backend/packages/harness/deerflow/skills/review/analyzer.py`](<backend/packages/harness/deerflow/skills/review/analyzer.py>)
  - [`backend/packages/harness/deerflow/skills/review/cli.py`](<backend/packages/harness/deerflow/skills/review/cli.py>)
  - [`backend/packages/harness/deerflow/skills/review/digest.py`](<backend/packages/harness/deerflow/skills/review/digest.py>)
  - [`backend/packages/harness/deerflow/skills/review/eval_schema.py`](<backend/packages/harness/deerflow/skills/review/eval_schema.py>)
  - [`backend/packages/harness/deerflow/skills/review/models.py`](<backend/packages/harness/deerflow/skills/review/models.py>)
  - [`backend/packages/harness/deerflow/skills/review/readers.py`](<backend/packages/harness/deerflow/skills/review/readers.py>)
  - [`backend/packages/harness/deerflow/skills/review/renderer.py`](<backend/packages/harness/deerflow/skills/review/renderer.py>)
  - [`backend/packages/harness/deerflow/skills/review/resource_graph.py`](<backend/packages/harness/deerflow/skills/review/resource_graph.py>)

### 127. `backend/packages/harness/deerflow/skills/security_scanner.py`

- 作用：实现技能系统的目录、解析、安装与权限能力。
- 阅读重点：理解技能从发现、校验、安装到运行时激活的完整路径。
- 文件：
  - [`backend/packages/harness/deerflow/skills/security_scanner.py`](<backend/packages/harness/deerflow/skills/security_scanner.py>)

### 128. `backend/packages/harness/deerflow/skills/security_static_scanner.py`

- 作用：实现技能系统的目录、解析、安装与权限能力。
- 阅读重点：理解技能从发现、校验、安装到运行时激活的完整路径。
- 文件：
  - [`backend/packages/harness/deerflow/skills/security_static_scanner.py`](<backend/packages/harness/deerflow/skills/security_static_scanner.py>)

### 129. `backend/packages/harness/deerflow/skills/skillscan`

- 作用：实现技能系统的安全扫描能力。
- 阅读重点：理解技能从发现、校验、安装到运行时激活的完整路径。
- 文件：
  - [`backend/packages/harness/deerflow/skills/skillscan/__init__.py`](<backend/packages/harness/deerflow/skills/skillscan/__init__.py>)
  - [`backend/packages/harness/deerflow/skills/skillscan/models.py`](<backend/packages/harness/deerflow/skills/skillscan/models.py>)
  - [`backend/packages/harness/deerflow/skills/skillscan/orchestrator.py`](<backend/packages/harness/deerflow/skills/skillscan/orchestrator.py>)

### 130. `backend/packages/harness/deerflow/skills/slash.py`

- 作用：实现技能系统的目录、解析、安装与权限能力。
- 阅读重点：理解技能从发现、校验、安装到运行时激活的完整路径。
- 文件：
  - [`backend/packages/harness/deerflow/skills/slash.py`](<backend/packages/harness/deerflow/skills/slash.py>)

### 131. `backend/packages/harness/deerflow/skills/storage`

- 作用：实现技能系统的存储能力。
- 阅读重点：理解技能从发现、校验、安装到运行时激活的完整路径。
- 文件：
  - [`backend/packages/harness/deerflow/skills/storage/__init__.py`](<backend/packages/harness/deerflow/skills/storage/__init__.py>)
  - [`backend/packages/harness/deerflow/skills/storage/local_skill_storage.py`](<backend/packages/harness/deerflow/skills/storage/local_skill_storage.py>)
  - [`backend/packages/harness/deerflow/skills/storage/skill_storage.py`](<backend/packages/harness/deerflow/skills/storage/skill_storage.py>)
  - [`backend/packages/harness/deerflow/skills/storage/user_scoped_skill_storage.py`](<backend/packages/harness/deerflow/skills/storage/user_scoped_skill_storage.py>)

### 132. `backend/packages/harness/deerflow/skills/tool_policy.py`

- 作用：实现技能系统的目录、解析、安装与权限能力。
- 阅读重点：理解技能从发现、校验、安装到运行时激活的完整路径。
- 文件：
  - [`backend/packages/harness/deerflow/skills/tool_policy.py`](<backend/packages/harness/deerflow/skills/tool_policy.py>)

### 133. `backend/packages/harness/deerflow/skills/types.py`

- 作用：实现技能系统的目录、解析、安装与权限能力。
- 阅读重点：理解技能从发现、校验、安装到运行时激活的完整路径。
- 文件：
  - [`backend/packages/harness/deerflow/skills/types.py`](<backend/packages/harness/deerflow/skills/types.py>)

### 134. `backend/packages/harness/deerflow/skills/validation.py`

- 作用：实现技能系统的目录、解析、安装与权限能力。
- 阅读重点：理解技能从发现、校验、安装到运行时激活的完整路径。
- 文件：
  - [`backend/packages/harness/deerflow/skills/validation.py`](<backend/packages/harness/deerflow/skills/validation.py>)

### 135. `backend/packages/harness/deerflow/community/aio_sandbox`

- 作用：实现 aio_sandbox 社区扩展或第三方服务适配。
- 阅读重点：关注统一工具接口如何封装不同外部 API。
- 文件：
  - [`backend/packages/harness/deerflow/community/aio_sandbox/__init__.py`](<backend/packages/harness/deerflow/community/aio_sandbox/__init__.py>)
  - [`backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py`](<backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py>)
  - [`backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox.py`](<backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox.py>)
  - [`backend/packages/harness/deerflow/community/aio_sandbox/backend.py`](<backend/packages/harness/deerflow/community/aio_sandbox/backend.py>)
  - [`backend/packages/harness/deerflow/community/aio_sandbox/local_backend.py`](<backend/packages/harness/deerflow/community/aio_sandbox/local_backend.py>)
  - [`backend/packages/harness/deerflow/community/aio_sandbox/remote_backend.py`](<backend/packages/harness/deerflow/community/aio_sandbox/remote_backend.py>)
  - [`backend/packages/harness/deerflow/community/aio_sandbox/sandbox_info.py`](<backend/packages/harness/deerflow/community/aio_sandbox/sandbox_info.py>)

### 136. `backend/packages/harness/deerflow/community/boxlite`

- 作用：实现 boxlite 社区扩展或第三方服务适配。
- 阅读重点：关注统一工具接口如何封装不同外部 API。
- 文件：
  - [`backend/packages/harness/deerflow/community/boxlite/__init__.py`](<backend/packages/harness/deerflow/community/boxlite/__init__.py>)
  - [`backend/packages/harness/deerflow/community/boxlite/box.py`](<backend/packages/harness/deerflow/community/boxlite/box.py>)
  - [`backend/packages/harness/deerflow/community/boxlite/provider.py`](<backend/packages/harness/deerflow/community/boxlite/provider.py>)

### 137. `backend/packages/harness/deerflow/community/brave`

- 作用：实现 brave 社区扩展或第三方服务适配。
- 阅读重点：关注统一工具接口如何封装不同外部 API。
- 文件：
  - [`backend/packages/harness/deerflow/community/brave/__init__.py`](<backend/packages/harness/deerflow/community/brave/__init__.py>)
  - [`backend/packages/harness/deerflow/community/brave/tools.py`](<backend/packages/harness/deerflow/community/brave/tools.py>)

### 138. `backend/packages/harness/deerflow/community/browserless`

- 作用：实现 browserless 社区扩展或第三方服务适配。
- 阅读重点：关注统一工具接口如何封装不同外部 API。
- 文件：
  - [`backend/packages/harness/deerflow/community/browserless/__init__.py`](<backend/packages/harness/deerflow/community/browserless/__init__.py>)
  - [`backend/packages/harness/deerflow/community/browserless/browserless_client.py`](<backend/packages/harness/deerflow/community/browserless/browserless_client.py>)
  - [`backend/packages/harness/deerflow/community/browserless/tools.py`](<backend/packages/harness/deerflow/community/browserless/tools.py>)

### 139. `backend/packages/harness/deerflow/community/crawl4ai`

- 作用：实现 crawl4ai 社区扩展或第三方服务适配。
- 阅读重点：关注统一工具接口如何封装不同外部 API。
- 文件：
  - [`backend/packages/harness/deerflow/community/crawl4ai/__init__.py`](<backend/packages/harness/deerflow/community/crawl4ai/__init__.py>)
  - [`backend/packages/harness/deerflow/community/crawl4ai/crawl4ai_client.py`](<backend/packages/harness/deerflow/community/crawl4ai/crawl4ai_client.py>)
  - [`backend/packages/harness/deerflow/community/crawl4ai/tools.py`](<backend/packages/harness/deerflow/community/crawl4ai/tools.py>)

### 140. `backend/packages/harness/deerflow/community/ddg_search`

- 作用：实现 ddg_search 社区扩展或第三方服务适配。
- 阅读重点：关注统一工具接口如何封装不同外部 API。
- 文件：
  - [`backend/packages/harness/deerflow/community/ddg_search/__init__.py`](<backend/packages/harness/deerflow/community/ddg_search/__init__.py>)
  - [`backend/packages/harness/deerflow/community/ddg_search/tools.py`](<backend/packages/harness/deerflow/community/ddg_search/tools.py>)

### 141. `backend/packages/harness/deerflow/community/e2b_sandbox`

- 作用：实现 e2b_sandbox 社区扩展或第三方服务适配。
- 阅读重点：关注统一工具接口如何封装不同外部 API。
- 文件：
  - [`backend/packages/harness/deerflow/community/e2b_sandbox/__init__.py`](<backend/packages/harness/deerflow/community/e2b_sandbox/__init__.py>)
  - [`backend/packages/harness/deerflow/community/e2b_sandbox/e2b_sandbox_provider.py`](<backend/packages/harness/deerflow/community/e2b_sandbox/e2b_sandbox_provider.py>)
  - [`backend/packages/harness/deerflow/community/e2b_sandbox/e2b_sandbox.py`](<backend/packages/harness/deerflow/community/e2b_sandbox/e2b_sandbox.py>)

### 142. `backend/packages/harness/deerflow/community/exa`

- 作用：实现 exa 社区扩展或第三方服务适配。
- 阅读重点：关注统一工具接口如何封装不同外部 API。
- 文件：
  - [`backend/packages/harness/deerflow/community/exa/tools.py`](<backend/packages/harness/deerflow/community/exa/tools.py>)

### 143. `backend/packages/harness/deerflow/community/fastcrw`

- 作用：实现 fastcrw 社区扩展或第三方服务适配。
- 阅读重点：关注统一工具接口如何封装不同外部 API。
- 文件：
  - [`backend/packages/harness/deerflow/community/fastcrw/tools.py`](<backend/packages/harness/deerflow/community/fastcrw/tools.py>)

### 144. `backend/packages/harness/deerflow/community/firecrawl`

- 作用：实现 firecrawl 社区扩展或第三方服务适配。
- 阅读重点：关注统一工具接口如何封装不同外部 API。
- 文件：
  - [`backend/packages/harness/deerflow/community/firecrawl/tools.py`](<backend/packages/harness/deerflow/community/firecrawl/tools.py>)

### 145. `backend/packages/harness/deerflow/community/groundroute`

- 作用：实现 groundroute 社区扩展或第三方服务适配。
- 阅读重点：关注统一工具接口如何封装不同外部 API。
- 文件：
  - [`backend/packages/harness/deerflow/community/groundroute/__init__.py`](<backend/packages/harness/deerflow/community/groundroute/__init__.py>)
  - [`backend/packages/harness/deerflow/community/groundroute/tools.py`](<backend/packages/harness/deerflow/community/groundroute/tools.py>)

### 146. `backend/packages/harness/deerflow/community/image_search`

- 作用：实现 image_search 社区扩展或第三方服务适配。
- 阅读重点：关注统一工具接口如何封装不同外部 API。
- 文件：
  - [`backend/packages/harness/deerflow/community/image_search/__init__.py`](<backend/packages/harness/deerflow/community/image_search/__init__.py>)
  - [`backend/packages/harness/deerflow/community/image_search/tools.py`](<backend/packages/harness/deerflow/community/image_search/tools.py>)

### 147. `backend/packages/harness/deerflow/community/infoquest`

- 作用：实现 infoquest 社区扩展或第三方服务适配。
- 阅读重点：关注统一工具接口如何封装不同外部 API。
- 文件：
  - [`backend/packages/harness/deerflow/community/infoquest/infoquest_client.py`](<backend/packages/harness/deerflow/community/infoquest/infoquest_client.py>)
  - [`backend/packages/harness/deerflow/community/infoquest/tools.py`](<backend/packages/harness/deerflow/community/infoquest/tools.py>)

### 148. `backend/packages/harness/deerflow/community/jina_ai`

- 作用：实现 jina_ai 社区扩展或第三方服务适配。
- 阅读重点：关注统一工具接口如何封装不同外部 API。
- 文件：
  - [`backend/packages/harness/deerflow/community/jina_ai/jina_client.py`](<backend/packages/harness/deerflow/community/jina_ai/jina_client.py>)
  - [`backend/packages/harness/deerflow/community/jina_ai/tools.py`](<backend/packages/harness/deerflow/community/jina_ai/tools.py>)

### 149. `backend/packages/harness/deerflow/community/searxng`

- 作用：实现 searxng 社区扩展或第三方服务适配。
- 阅读重点：关注统一工具接口如何封装不同外部 API。
- 文件：
  - [`backend/packages/harness/deerflow/community/searxng/__init__.py`](<backend/packages/harness/deerflow/community/searxng/__init__.py>)
  - [`backend/packages/harness/deerflow/community/searxng/searxng_client.py`](<backend/packages/harness/deerflow/community/searxng/searxng_client.py>)
  - [`backend/packages/harness/deerflow/community/searxng/tools.py`](<backend/packages/harness/deerflow/community/searxng/tools.py>)

### 150. `backend/packages/harness/deerflow/community/serper`

- 作用：实现 serper 社区扩展或第三方服务适配。
- 阅读重点：关注统一工具接口如何封装不同外部 API。
- 文件：
  - [`backend/packages/harness/deerflow/community/serper/__init__.py`](<backend/packages/harness/deerflow/community/serper/__init__.py>)
  - [`backend/packages/harness/deerflow/community/serper/tools.py`](<backend/packages/harness/deerflow/community/serper/tools.py>)

### 151. `backend/packages/harness/deerflow/community/tavily`

- 作用：实现 tavily 社区扩展或第三方服务适配。
- 阅读重点：关注统一工具接口如何封装不同外部 API。
- 文件：
  - [`backend/packages/harness/deerflow/community/tavily/tools.py`](<backend/packages/harness/deerflow/community/tavily/tools.py>)

### 152. `backend/packages/harness/deerflow/community/url_safety.py`

- 作用：实现 url_safety.py 社区扩展或第三方服务适配。
- 阅读重点：关注统一工具接口如何封装不同外部 API。
- 文件：
  - [`backend/packages/harness/deerflow/community/url_safety.py`](<backend/packages/harness/deerflow/community/url_safety.py>)

### 153. `backend/packages/harness/deerflow/community/warm_pool_lifecycle.py`

- 作用：实现 warm_pool_lifecycle.py 社区扩展或第三方服务适配。
- 阅读重点：关注统一工具接口如何封装不同外部 API。
- 文件：
  - [`backend/packages/harness/deerflow/community/warm_pool_lifecycle.py`](<backend/packages/harness/deerflow/community/warm_pool_lifecycle.py>)

### 154. `backend/packages/harness/deerflow/guardrails`

- 作用：实现输入输出安全护栏及其 Provider 接口。
- 阅读重点：关注内置规则和中间件接入点。
- 文件：
  - [`backend/packages/harness/deerflow/guardrails/__init__.py`](<backend/packages/harness/deerflow/guardrails/__init__.py>)
  - [`backend/packages/harness/deerflow/guardrails/builtin.py`](<backend/packages/harness/deerflow/guardrails/builtin.py>)
  - [`backend/packages/harness/deerflow/guardrails/middleware.py`](<backend/packages/harness/deerflow/guardrails/middleware.py>)
  - [`backend/packages/harness/deerflow/guardrails/provider.py`](<backend/packages/harness/deerflow/guardrails/provider.py>)

### 155. `backend/packages/harness/deerflow/authz`

- 作用：定义授权 Provider 和权限适配协议。
- 阅读重点：理解应用层如何把用户权限传入 harness。
- 文件：
  - [`backend/packages/harness/deerflow/authz/__init__.py`](<backend/packages/harness/deerflow/authz/__init__.py>)
  - [`backend/packages/harness/deerflow/authz/adapter.py`](<backend/packages/harness/deerflow/authz/adapter.py>)
  - [`backend/packages/harness/deerflow/authz/provider.py`](<backend/packages/harness/deerflow/authz/provider.py>)

### 156. `backend/packages/harness/deerflow/reflection`

- 作用：提供运行时反射和依赖解析辅助能力。
- 阅读重点：查看延迟解析如何降低模块耦合。
- 文件：
  - [`backend/packages/harness/deerflow/reflection/__init__.py`](<backend/packages/harness/deerflow/reflection/__init__.py>)
  - [`backend/packages/harness/deerflow/reflection/resolvers.py`](<backend/packages/harness/deerflow/reflection/resolvers.py>)

### 157. `backend/packages/harness/deerflow/scheduler`

- 作用：定义定时表达式和调度领域规则。
- 阅读重点：与应用层 scheduler 服务对照阅读。
- 文件：
  - [`backend/packages/harness/deerflow/scheduler/__init__.py`](<backend/packages/harness/deerflow/scheduler/__init__.py>)
  - [`backend/packages/harness/deerflow/scheduler/schedules.py`](<backend/packages/harness/deerflow/scheduler/schedules.py>)

### 158. `backend/packages/harness/deerflow`

- 作用：包含 harness 包入口、客户端、常量、日志和跨领域基础模块。
- 阅读重点：作为上层模块共同依赖的底层参考。
- 文件：
  - [`backend/packages/harness/deerflow/__init__.py`](<backend/packages/harness/deerflow/__init__.py>)
  - [`backend/packages/harness/deerflow/client.py`](<backend/packages/harness/deerflow/client.py>)
  - [`backend/packages/harness/deerflow/constants.py`](<backend/packages/harness/deerflow/constants.py>)
  - [`backend/packages/harness/deerflow/logging_config.py`](<backend/packages/harness/deerflow/logging_config.py>)
  - [`backend/packages/harness/deerflow/trace_context.py`](<backend/packages/harness/deerflow/trace_context.py>)
  - [`backend/packages/harness/deerflow/tracing/__init__.py`](<backend/packages/harness/deerflow/tracing/__init__.py>)
  - [`backend/packages/harness/deerflow/tracing/factory.py`](<backend/packages/harness/deerflow/tracing/factory.py>)
  - [`backend/packages/harness/deerflow/tracing/metadata.py`](<backend/packages/harness/deerflow/tracing/metadata.py>)
  - [`backend/packages/harness/deerflow/tracing/monocle.py`](<backend/packages/harness/deerflow/tracing/monocle.py>)
  - [`backend/packages/harness/deerflow/tui/__init__.py`](<backend/packages/harness/deerflow/tui/__init__.py>)
  - [`backend/packages/harness/deerflow/tui/__main__.py`](<backend/packages/harness/deerflow/tui/__main__.py>)
  - [`backend/packages/harness/deerflow/tui/app.py`](<backend/packages/harness/deerflow/tui/app.py>)
  - [`backend/packages/harness/deerflow/tui/cli.py`](<backend/packages/harness/deerflow/tui/cli.py>)
  - [`backend/packages/harness/deerflow/tui/command_registry.py`](<backend/packages/harness/deerflow/tui/command_registry.py>)
  - [`backend/packages/harness/deerflow/tui/input_history.py`](<backend/packages/harness/deerflow/tui/input_history.py>)
  - [`backend/packages/harness/deerflow/tui/message_format.py`](<backend/packages/harness/deerflow/tui/message_format.py>)
  - [`backend/packages/harness/deerflow/tui/persistence.py`](<backend/packages/harness/deerflow/tui/persistence.py>)
  - [`backend/packages/harness/deerflow/tui/render.py`](<backend/packages/harness/deerflow/tui/render.py>)
  - [`backend/packages/harness/deerflow/tui/runtime.py`](<backend/packages/harness/deerflow/tui/runtime.py>)
  - [`backend/packages/harness/deerflow/tui/session.py`](<backend/packages/harness/deerflow/tui/session.py>)
  - [`backend/packages/harness/deerflow/tui/theme.py`](<backend/packages/harness/deerflow/tui/theme.py>)
  - [`backend/packages/harness/deerflow/tui/view_state.py`](<backend/packages/harness/deerflow/tui/view_state.py>)
  - [`backend/packages/harness/deerflow/tui/widgets/__init__.py`](<backend/packages/harness/deerflow/tui/widgets/__init__.py>)
  - [`backend/packages/harness/deerflow/tui/widgets/composer.py`](<backend/packages/harness/deerflow/tui/widgets/composer.py>)
  - [`backend/packages/harness/deerflow/uploads/__init__.py`](<backend/packages/harness/deerflow/uploads/__init__.py>)
  - [`backend/packages/harness/deerflow/uploads/manager.py`](<backend/packages/harness/deerflow/uploads/manager.py>)
  - [`backend/packages/harness/deerflow/utils/file_conversion.py`](<backend/packages/harness/deerflow/utils/file_conversion.py>)
  - [`backend/packages/harness/deerflow/utils/file_io.py`](<backend/packages/harness/deerflow/utils/file_io.py>)
  - [`backend/packages/harness/deerflow/utils/llm_text.py`](<backend/packages/harness/deerflow/utils/llm_text.py>)
  - [`backend/packages/harness/deerflow/utils/messages.py`](<backend/packages/harness/deerflow/utils/messages.py>)
  - [`backend/packages/harness/deerflow/utils/network.py`](<backend/packages/harness/deerflow/utils/network.py>)
  - [`backend/packages/harness/deerflow/utils/oneshot_llm.py`](<backend/packages/harness/deerflow/utils/oneshot_llm.py>)
  - [`backend/packages/harness/deerflow/utils/readability.py`](<backend/packages/harness/deerflow/utils/readability.py>)
  - [`backend/packages/harness/deerflow/utils/time.py`](<backend/packages/harness/deerflow/utils/time.py>)
  - [`backend/packages/harness/deerflow/workspace_changes/__init__.py`](<backend/packages/harness/deerflow/workspace_changes/__init__.py>)
  - [`backend/packages/harness/deerflow/workspace_changes/api.py`](<backend/packages/harness/deerflow/workspace_changes/api.py>)
  - [`backend/packages/harness/deerflow/workspace_changes/diff.py`](<backend/packages/harness/deerflow/workspace_changes/diff.py>)
  - [`backend/packages/harness/deerflow/workspace_changes/recorder.py`](<backend/packages/harness/deerflow/workspace_changes/recorder.py>)
  - [`backend/packages/harness/deerflow/workspace_changes/scanner.py`](<backend/packages/harness/deerflow/workspace_changes/scanner.py>)
  - [`backend/packages/harness/deerflow/workspace_changes/types.py`](<backend/packages/harness/deerflow/workspace_changes/types.py>)

## 第五阶段：测试与质量保障

### 159. `frontend/tests/e2e`

- 作用：验证前端 e2e 场景的行为、交互与接口契约。
- 阅读重点：结合对应 src 模块阅读测试用例描述的外部行为。
- 文件：
  - [`frontend/tests/e2e/agent-chat.spec.ts`](<frontend/tests/e2e/agent-chat.spec.ts>)
  - [`frontend/tests/e2e/agents-feature-disabled.spec.ts`](<frontend/tests/e2e/agents-feature-disabled.spec.ts>)
  - [`frontend/tests/e2e/artifact-preview.spec.ts`](<frontend/tests/e2e/artifact-preview.spec.ts>)
  - [`frontend/tests/e2e/artifact-stream-state.spec.ts`](<frontend/tests/e2e/artifact-stream-state.spec.ts>)
  - [`frontend/tests/e2e/branch-thread.spec.ts`](<frontend/tests/e2e/branch-thread.spec.ts>)
  - [`frontend/tests/e2e/channels.spec.ts`](<frontend/tests/e2e/channels.spec.ts>)
  - [`frontend/tests/e2e/chat-thread-init-ordering.spec.ts`](<frontend/tests/e2e/chat-thread-init-ordering.spec.ts>)
  - [`frontend/tests/e2e/chat.spec.ts`](<frontend/tests/e2e/chat.spec.ts>)
  - [`frontend/tests/e2e/docs-localized-links.spec.ts`](<frontend/tests/e2e/docs-localized-links.spec.ts>)
  - [`frontend/tests/e2e/landing.spec.ts`](<frontend/tests/e2e/landing.spec.ts>)
  - [`frontend/tests/e2e/scheduled-tasks.spec.ts`](<frontend/tests/e2e/scheduled-tasks.spec.ts>)
  - [`frontend/tests/e2e/settings-notification.spec.ts`](<frontend/tests/e2e/settings-notification.spec.ts>)
  - [`frontend/tests/e2e/sidebar.spec.ts`](<frontend/tests/e2e/sidebar.spec.ts>)
  - [`frontend/tests/e2e/sidecar-chat.spec.ts`](<frontend/tests/e2e/sidecar-chat.spec.ts>)
  - [`frontend/tests/e2e/subtask-card.spec.ts`](<frontend/tests/e2e/subtask-card.spec.ts>)
  - [`frontend/tests/e2e/thread-history-mermaid.spec.ts`](<frontend/tests/e2e/thread-history-mermaid.spec.ts>)
  - [`frontend/tests/e2e/thread-history.spec.ts`](<frontend/tests/e2e/thread-history.spec.ts>)
  - [`frontend/tests/e2e/thread-list-infinite-scroll.spec.ts`](<frontend/tests/e2e/thread-list-infinite-scroll.spec.ts>)
  - [`frontend/tests/e2e/ui-polish-mobile.spec.ts`](<frontend/tests/e2e/ui-polish-mobile.spec.ts>)
  - [`frontend/tests/e2e/user-message-plain-text.spec.ts`](<frontend/tests/e2e/user-message-plain-text.spec.ts>)
  - [`frontend/tests/e2e/utils/mock-api.ts`](<frontend/tests/e2e/utils/mock-api.ts>)
  - [`frontend/tests/e2e/workspace-changes.spec.ts`](<frontend/tests/e2e/workspace-changes.spec.ts>)

### 160. `frontend/tests/e2e-real-backend`

- 作用：验证前端 e2e-real-backend 场景的行为、交互与接口契约。
- 阅读重点：结合对应 src 模块阅读测试用例描述的外部行为。
- 文件：
  - [`frontend/tests/e2e-real-backend/auth-disabled-contract.spec.ts`](<frontend/tests/e2e-real-backend/auth-disabled-contract.spec.ts>)
  - [`frontend/tests/e2e-real-backend/multi-run-order.spec.ts`](<frontend/tests/e2e-real-backend/multi-run-order.spec.ts>)
  - [`frontend/tests/e2e-real-backend/real-backend-render.spec.ts`](<frontend/tests/e2e-real-backend/real-backend-render.spec.ts>)

### 161. `frontend/tests/e2e-record`

- 作用：验证前端 e2e-record 场景的行为、交互与接口契约。
- 阅读重点：结合对应 src 模块阅读测试用例描述的外部行为。
- 文件：
  - [`frontend/tests/e2e-record/record-write-read-file.spec.ts`](<frontend/tests/e2e-record/record-write-read-file.spec.ts>)

### 162. `frontend/tests/unit`

- 作用：验证前端 unit 场景的行为、交互与接口契约。
- 阅读重点：结合对应 src 模块阅读测试用例描述的外部行为。
- 文件：
  - [`frontend/tests/unit/components/docs/localized-links.test.ts`](<frontend/tests/unit/components/docs/localized-links.test.ts>)
  - [`frontend/tests/unit/components/workspace/citations/citation-sources-panel.test.ts`](<frontend/tests/unit/components/workspace/citations/citation-sources-panel.test.ts>)
  - [`frontend/tests/unit/components/workspace/gateway-offline-banner-helpers.test.ts`](<frontend/tests/unit/components/workspace/gateway-offline-banner-helpers.test.ts>)
  - [`frontend/tests/unit/components/workspace/goal-status-helpers.test.ts`](<frontend/tests/unit/components/workspace/goal-status-helpers.test.ts>)
  - [`frontend/tests/unit/components/workspace/input-box-helpers.test.ts`](<frontend/tests/unit/components/workspace/input-box-helpers.test.ts>)
  - [`frontend/tests/unit/components/workspace/messages/human-input-card.test.ts`](<frontend/tests/unit/components/workspace/messages/human-input-card.test.ts>)
  - [`frontend/tests/unit/components/workspace/messages/markdown-content.test.ts`](<frontend/tests/unit/components/workspace/messages/markdown-content.test.ts>)
  - [`frontend/tests/unit/components/workspace/messages/message-group.test.ts`](<frontend/tests/unit/components/workspace/messages/message-group.test.ts>)
  - [`frontend/tests/unit/components/workspace/settings/about-content.test.ts`](<frontend/tests/unit/components/workspace/settings/about-content.test.ts>)
  - [`frontend/tests/unit/components/workspace/use-active-goal.test.ts`](<frontend/tests/unit/components/workspace/use-active-goal.test.ts>)
  - [`frontend/tests/unit/core/agents/api.test.ts`](<frontend/tests/unit/core/agents/api.test.ts>)
  - [`frontend/tests/unit/core/agents/feature-cache.test.ts`](<frontend/tests/unit/core/agents/feature-cache.test.ts>)
  - [`frontend/tests/unit/core/agents/features.test.ts`](<frontend/tests/unit/core/agents/features.test.ts>)
  - [`frontend/tests/unit/core/api/api-client.test.ts`](<frontend/tests/unit/core/api/api-client.test.ts>)
  - [`frontend/tests/unit/core/api/stream-mode.test.ts`](<frontend/tests/unit/core/api/stream-mode.test.ts>)
  - [`frontend/tests/unit/core/artifacts/preview.test.ts`](<frontend/tests/unit/core/artifacts/preview.test.ts>)
  - [`frontend/tests/unit/core/artifacts/utils.test.ts`](<frontend/tests/unit/core/artifacts/utils.test.ts>)
  - [`frontend/tests/unit/core/auth/gateway-config.test.ts`](<frontend/tests/unit/core/auth/gateway-config.test.ts>)
  - [`frontend/tests/unit/core/auth/server.test.ts`](<frontend/tests/unit/core/auth/server.test.ts>)
  - [`frontend/tests/unit/core/auth/setup.test.ts`](<frontend/tests/unit/core/auth/setup.test.ts>)
  - [`frontend/tests/unit/core/channels/api.test.ts`](<frontend/tests/unit/core/channels/api.test.ts>)
  - [`frontend/tests/unit/core/channels/connect-poll.test.ts`](<frontend/tests/unit/core/channels/connect-poll.test.ts>)
  - [`frontend/tests/unit/core/channels/open-connect-url.test.ts`](<frontend/tests/unit/core/channels/open-connect-url.test.ts>)
  - [`frontend/tests/unit/core/channels/provider-state.test.ts`](<frontend/tests/unit/core/channels/provider-state.test.ts>)
  - [`frontend/tests/unit/core/citations/sources.test.ts`](<frontend/tests/unit/core/citations/sources.test.ts>)
  - [`frontend/tests/unit/core/clipboard.test.ts`](<frontend/tests/unit/core/clipboard.test.ts>)
  - [`frontend/tests/unit/core/mcp/api.test.ts`](<frontend/tests/unit/core/mcp/api.test.ts>)
  - [`frontend/tests/unit/core/mcp/hooks.test.ts`](<frontend/tests/unit/core/mcp/hooks.test.ts>)
  - [`frontend/tests/unit/core/messages/human-input.test.ts`](<frontend/tests/unit/core/messages/human-input.test.ts>)
  - [`frontend/tests/unit/core/messages/usage-model.test.ts`](<frontend/tests/unit/core/messages/usage-model.test.ts>)
  - [`frontend/tests/unit/core/messages/usage.test.ts`](<frontend/tests/unit/core/messages/usage.test.ts>)
  - [`frontend/tests/unit/core/messages/utils.test.ts`](<frontend/tests/unit/core/messages/utils.test.ts>)
  - [`frontend/tests/unit/core/notification/hooks.test.ts`](<frontend/tests/unit/core/notification/hooks.test.ts>)
  - [`frontend/tests/unit/core/reasoning-trigger.test.ts`](<frontend/tests/unit/core/reasoning-trigger.test.ts>)
  - [`frontend/tests/unit/core/scheduled-tasks/cron.test.ts`](<frontend/tests/unit/core/scheduled-tasks/cron.test.ts>)
  - [`frontend/tests/unit/core/scheduled-tasks/hooks.test.ts`](<frontend/tests/unit/core/scheduled-tasks/hooks.test.ts>)
  - [`frontend/tests/unit/core/settings/local.test.ts`](<frontend/tests/unit/core/settings/local.test.ts>)
  - [`frontend/tests/unit/core/sidecar/api.test.ts`](<frontend/tests/unit/core/sidecar/api.test.ts>)
  - [`frontend/tests/unit/core/sidecar/context.test.ts`](<frontend/tests/unit/core/sidecar/context.test.ts>)
  - [`frontend/tests/unit/core/sidecar/reference-metadata.test.ts`](<frontend/tests/unit/core/sidecar/reference-metadata.test.ts>)
  - [`frontend/tests/unit/core/sidecar/reference-state.test.ts`](<frontend/tests/unit/core/sidecar/reference-state.test.ts>)
  - [`frontend/tests/unit/core/sidecar/thread.test.ts`](<frontend/tests/unit/core/sidecar/thread.test.ts>)
  - [`frontend/tests/unit/core/skills/slash-contract.test.ts`](<frontend/tests/unit/core/skills/slash-contract.test.ts>)
  - [`frontend/tests/unit/core/skills/slash.test.ts`](<frontend/tests/unit/core/skills/slash.test.ts>)
  - [`frontend/tests/unit/core/streamdown-plugins.test.ts`](<frontend/tests/unit/core/streamdown-plugins.test.ts>)
  - [`frontend/tests/unit/core/streamdown/mermaid.test.ts`](<frontend/tests/unit/core/streamdown/mermaid.test.ts>)
  - [`frontend/tests/unit/core/streamdown/plugins.test.ts`](<frontend/tests/unit/core/streamdown/plugins.test.ts>)
  - [`frontend/tests/unit/core/streamdown/preprocess.test.ts`](<frontend/tests/unit/core/streamdown/preprocess.test.ts>)
  - [`frontend/tests/unit/core/suggestions/placeholders.test.ts`](<frontend/tests/unit/core/suggestions/placeholders.test.ts>)
  - [`frontend/tests/unit/core/tasks/api.test.ts`](<frontend/tests/unit/core/tasks/api.test.ts>)
  - [`frontend/tests/unit/core/tasks/lifecycle.test.ts`](<frontend/tests/unit/core/tasks/lifecycle.test.ts>)
  - [`frontend/tests/unit/core/tasks/presentation.test.ts`](<frontend/tests/unit/core/tasks/presentation.test.ts>)
  - [`frontend/tests/unit/core/tasks/steps.test.ts`](<frontend/tests/unit/core/tasks/steps.test.ts>)
  - [`frontend/tests/unit/core/tasks/subtask-result.test.ts`](<frontend/tests/unit/core/tasks/subtask-result.test.ts>)
  - [`frontend/tests/unit/core/tasks/subtask-update.test.ts`](<frontend/tests/unit/core/tasks/subtask-update.test.ts>)
  - [`frontend/tests/unit/core/threads/api.test.ts`](<frontend/tests/unit/core/threads/api.test.ts>)
  - [`frontend/tests/unit/core/threads/delete-thread.test.ts`](<frontend/tests/unit/core/threads/delete-thread.test.ts>)
  - [`frontend/tests/unit/core/threads/export.test.ts`](<frontend/tests/unit/core/threads/export.test.ts>)
  - [`frontend/tests/unit/core/threads/infinite.test.ts`](<frontend/tests/unit/core/threads/infinite.test.ts>)
  - [`frontend/tests/unit/core/threads/message-merge.test.ts`](<frontend/tests/unit/core/threads/message-merge.test.ts>)
  - [`frontend/tests/unit/core/threads/send-message.test.ts`](<frontend/tests/unit/core/threads/send-message.test.ts>)
  - [`frontend/tests/unit/core/threads/thread-search-query.test.ts`](<frontend/tests/unit/core/threads/thread-search-query.test.ts>)
  - [`frontend/tests/unit/core/threads/token-usage.test.ts`](<frontend/tests/unit/core/threads/token-usage.test.ts>)
  - [`frontend/tests/unit/core/threads/utils.test.ts`](<frontend/tests/unit/core/threads/utils.test.ts>)
  - [`frontend/tests/unit/core/uploads/file-validation.test.ts`](<frontend/tests/unit/core/uploads/file-validation.test.ts>)
  - [`frontend/tests/unit/core/uploads/prompt-input-files.test.ts`](<frontend/tests/unit/core/uploads/prompt-input-files.test.ts>)
  - [`frontend/tests/unit/core/voice-input/speech-recognition.test.ts`](<frontend/tests/unit/core/voice-input/speech-recognition.test.ts>)
  - [`frontend/tests/unit/core/workspace-changes/api.test.ts`](<frontend/tests/unit/core/workspace-changes/api.test.ts>)
  - [`frontend/tests/unit/core/workspace-changes/summary.test.ts`](<frontend/tests/unit/core/workspace-changes/summary.test.ts>)
  - [`frontend/tests/unit/hooks/use-global-shortcuts.test.ts`](<frontend/tests/unit/hooks/use-global-shortcuts.test.ts>)
  - [`frontend/tests/unit/version.test.ts`](<frontend/tests/unit/version.test.ts>)

### 163. `backend/tests`

- 作用：覆盖 Gateway、Agent、运行时、工具、存储、安全和渠道的后端测试。
- 阅读重点：按被测模块名称检索测试，利用断言确认真实行为边界。
- 文件：
  - [`backend/tests/_agent_e2e_helpers.py`](<backend/tests/_agent_e2e_helpers.py>)
  - [`backend/tests/_replay_fixture.py`](<backend/tests/_replay_fixture.py>)
  - [`backend/tests/_router_auth_helpers.py`](<backend/tests/_router_auth_helpers.py>)
  - [`backend/tests/_run_message_pagination_helpers.py`](<backend/tests/_run_message_pagination_helpers.py>)
  - [`backend/tests/blocking_io/__init__.py`](<backend/tests/blocking_io/__init__.py>)
  - [`backend/tests/blocking_io/conftest.py`](<backend/tests/blocking_io/conftest.py>)
  - [`backend/tests/blocking_io/test_agents_router.py`](<backend/tests/blocking_io/test_agents_router.py>)
  - [`backend/tests/blocking_io/test_artifacts_router.py`](<backend/tests/blocking_io/test_artifacts_router.py>)
  - [`backend/tests/blocking_io/test_channel_runtime_config_store.py`](<backend/tests/blocking_io/test_channel_runtime_config_store.py>)
  - [`backend/tests/blocking_io/test_channels_ingest.py`](<backend/tests/blocking_io/test_channels_ingest.py>)
  - [`backend/tests/blocking_io/test_discord_channel_state.py`](<backend/tests/blocking_io/test_discord_channel_state.py>)
  - [`backend/tests/blocking_io/test_dynamic_context_middleware.py`](<backend/tests/blocking_io/test_dynamic_context_middleware.py>)
  - [`backend/tests/blocking_io/test_gate_smoke.py`](<backend/tests/blocking_io/test_gate_smoke.py>)
  - [`backend/tests/blocking_io/test_jsonl_run_event_store.py`](<backend/tests/blocking_io/test_jsonl_run_event_store.py>)
  - [`backend/tests/blocking_io/test_mcp_router.py`](<backend/tests/blocking_io/test_mcp_router.py>)
  - [`backend/tests/blocking_io/test_persistence_bootstrap.py`](<backend/tests/blocking_io/test_persistence_bootstrap.py>)
  - [`backend/tests/blocking_io/test_persistence_engine_sqlite.py`](<backend/tests/blocking_io/test_persistence_engine_sqlite.py>)
  - [`backend/tests/blocking_io/test_skills_install.py`](<backend/tests/blocking_io/test_skills_install.py>)
  - [`backend/tests/blocking_io/test_skills_load.py`](<backend/tests/blocking_io/test_skills_load.py>)
  - [`backend/tests/blocking_io/test_sqlite_lifespan.py`](<backend/tests/blocking_io/test_sqlite_lifespan.py>)
  - [`backend/tests/blocking_io/test_uploads_middleware.py`](<backend/tests/blocking_io/test_uploads_middleware.py>)
  - [`backend/tests/blocking_io/test_uploads_router.py`](<backend/tests/blocking_io/test_uploads_router.py>)
  - [`backend/tests/blocking_io/test_wechat_channel_state.py`](<backend/tests/blocking_io/test_wechat_channel_state.py>)
  - [`backend/tests/conftest.py`](<backend/tests/conftest.py>)
  - [`backend/tests/replay_provider.py`](<backend/tests/replay_provider.py>)
  - [`backend/tests/seed_runs_router.py`](<backend/tests/seed_runs_router.py>)
  - [`backend/tests/support/__init__.py`](<backend/tests/support/__init__.py>)
  - [`backend/tests/support/detectors/__init__.py`](<backend/tests/support/detectors/__init__.py>)
  - [`backend/tests/support/detectors/blocking_io_changed.py`](<backend/tests/support/detectors/blocking_io_changed.py>)
  - [`backend/tests/support/detectors/blocking_io_runtime.py`](<backend/tests/support/detectors/blocking_io_runtime.py>)
  - [`backend/tests/support/detectors/blocking_io_static.py`](<backend/tests/support/detectors/blocking_io_static.py>)
  - [`backend/tests/support/detectors/repo_root.py`](<backend/tests/support/detectors/repo_root.py>)
  - [`backend/tests/support/detectors/thread_boundaries.py`](<backend/tests/support/detectors/thread_boundaries.py>)
  - [`backend/tests/test_acp_config.py`](<backend/tests/test_acp_config.py>)
  - [`backend/tests/test_additional_channel_connections.py`](<backend/tests/test_additional_channel_connections.py>)
  - [`backend/tests/test_aio_sandbox_local_backend.py`](<backend/tests/test_aio_sandbox_local_backend.py>)
  - [`backend/tests/test_aio_sandbox_provider.py`](<backend/tests/test_aio_sandbox_provider.py>)
  - [`backend/tests/test_aio_sandbox_readiness.py`](<backend/tests/test_aio_sandbox_readiness.py>)
  - [`backend/tests/test_aio_sandbox.py`](<backend/tests/test_aio_sandbox.py>)
  - [`backend/tests/test_app_config_name_indexes.py`](<backend/tests/test_app_config_name_indexes.py>)
  - [`backend/tests/test_app_config_reload.py`](<backend/tests/test_app_config_reload.py>)
  - [`backend/tests/test_artifacts_router.py`](<backend/tests/test_artifacts_router.py>)
  - [`backend/tests/test_assistant_payload_replay.py`](<backend/tests/test_assistant_payload_replay.py>)
  - [`backend/tests/test_auth_config.py`](<backend/tests/test_auth_config.py>)
  - [`backend/tests/test_auth_errors.py`](<backend/tests/test_auth_errors.py>)
  - [`backend/tests/test_auth_middleware.py`](<backend/tests/test_auth_middleware.py>)
  - [`backend/tests/test_auth_type_system.py`](<backend/tests/test_auth_type_system.py>)
  - [`backend/tests/test_auth.py`](<backend/tests/test_auth.py>)
  - [`backend/tests/test_authorization_provider.py`](<backend/tests/test_authorization_provider.py>)
  - [`backend/tests/test_base_to_dict.py`](<backend/tests/test_base_to_dict.py>)
  - [`backend/tests/test_bench_sandbox_provider.py`](<backend/tests/test_bench_sandbox_provider.py>)
  - [`backend/tests/test_boxlite_provider.py`](<backend/tests/test_boxlite_provider.py>)
  - [`backend/tests/test_brave_tools.py`](<backend/tests/test_brave_tools.py>)
  - [`backend/tests/test_browserless_client.py`](<backend/tests/test_browserless_client.py>)
  - [`backend/tests/test_cancel_run_idempotent.py`](<backend/tests/test_cancel_run_idempotent.py>)
  - [`backend/tests/test_channel_connections_config.py`](<backend/tests/test_channel_connections_config.py>)
  - [`backend/tests/test_channel_connections_repository.py`](<backend/tests/test_channel_connections_repository.py>)
  - [`backend/tests/test_channel_connections_router.py`](<backend/tests/test_channel_connections_router.py>)
  - [`backend/tests/test_channel_file_attachments.py`](<backend/tests/test_channel_file_attachments.py>)
  - [`backend/tests/test_channel_user_id_env.py`](<backend/tests/test_channel_user_id_env.py>)
  - [`backend/tests/test_channels_router.py`](<backend/tests/test_channels_router.py>)
  - [`backend/tests/test_channels.py`](<backend/tests/test_channels.py>)
  - [`backend/tests/test_check_script.py`](<backend/tests/test_check_script.py>)
  - [`backend/tests/test_checkpointer_none_fix.py`](<backend/tests/test_checkpointer_none_fix.py>)
  - [`backend/tests/test_checkpointer.py`](<backend/tests/test_checkpointer.py>)
  - [`backend/tests/test_clarification_middleware.py`](<backend/tests/test_clarification_middleware.py>)
  - [`backend/tests/test_claude_provider_oauth_billing.py`](<backend/tests/test_claude_provider_oauth_billing.py>)
  - [`backend/tests/test_claude_provider_prompt_caching.py`](<backend/tests/test_claude_provider_prompt_caching.py>)
  - [`backend/tests/test_cli_auth_providers.py`](<backend/tests/test_cli_auth_providers.py>)
  - [`backend/tests/test_client_e2e.py`](<backend/tests/test_client_e2e.py>)
  - [`backend/tests/test_client_langfuse_metadata.py`](<backend/tests/test_client_langfuse_metadata.py>)
  - [`backend/tests/test_client_live.py`](<backend/tests/test_client_live.py>)
  - [`backend/tests/test_client_message_serialization.py`](<backend/tests/test_client_message_serialization.py>)
  - [`backend/tests/test_client.py`](<backend/tests/test_client.py>)
  - [`backend/tests/test_codex_provider.py`](<backend/tests/test_codex_provider.py>)
  - [`backend/tests/test_compose_default_workers.py`](<backend/tests/test_compose_default_workers.py>)
  - [`backend/tests/test_config_version.py`](<backend/tests/test_config_version.py>)
  - [`backend/tests/test_console_router.py`](<backend/tests/test_console_router.py>)
  - [`backend/tests/test_context_compaction.py`](<backend/tests/test_context_compaction.py>)
  - [`backend/tests/test_converters.py`](<backend/tests/test_converters.py>)
  - [`backend/tests/test_crawl4ai_tools.py`](<backend/tests/test_crawl4ai_tools.py>)
  - [`backend/tests/test_create_deerflow_agent_live.py`](<backend/tests/test_create_deerflow_agent_live.py>)
  - [`backend/tests/test_create_deerflow_agent.py`](<backend/tests/test_create_deerflow_agent.py>)
  - [`backend/tests/test_credential_loader.py`](<backend/tests/test_credential_loader.py>)
  - [`backend/tests/test_csrf_middleware.py`](<backend/tests/test_csrf_middleware.py>)
  - [`backend/tests/test_custom_agent.py`](<backend/tests/test_custom_agent.py>)
  - [`backend/tests/test_dangling_tool_call_middleware.py`](<backend/tests/test_dangling_tool_call_middleware.py>)
  - [`backend/tests/test_ddg_search_tools.py`](<backend/tests/test_ddg_search_tools.py>)
  - [`backend/tests/test_deermem_self_contained.py`](<backend/tests/test_deermem_self_contained.py>)
  - [`backend/tests/test_deferred_catalog.py`](<backend/tests/test_deferred_catalog.py>)
  - [`backend/tests/test_deferred_filter_middleware.py`](<backend/tests/test_deferred_filter_middleware.py>)
  - [`backend/tests/test_deferred_promotion_integration.py`](<backend/tests/test_deferred_promotion_integration.py>)
  - [`backend/tests/test_deferred_setup.py`](<backend/tests/test_deferred_setup.py>)
  - [`backend/tests/test_deferred_tool_crosscontext.py`](<backend/tests/test_deferred_tool_crosscontext.py>)
  - [`backend/tests/test_deferred_tool_promotion_real_llm.py`](<backend/tests/test_deferred_tool_promotion_real_llm.py>)
  - [`backend/tests/test_delegation_ledger_live.py`](<backend/tests/test_delegation_ledger_live.py>)
  - [`backend/tests/test_delegation_ledger.py`](<backend/tests/test_delegation_ledger.py>)
  - [`backend/tests/test_deploy_uv_extras.py`](<backend/tests/test_deploy_uv_extras.py>)
  - [`backend/tests/test_detect_blocking_io_static.py`](<backend/tests/test_detect_blocking_io_static.py>)
  - [`backend/tests/test_detect_thread_boundaries.py`](<backend/tests/test_detect_thread_boundaries.py>)
  - [`backend/tests/test_detect_uv_extras.py`](<backend/tests/test_detect_uv_extras.py>)
  - [`backend/tests/test_detector_repo_root.py`](<backend/tests/test_detector_repo_root.py>)
  - [`backend/tests/test_dev_entrypoint.py`](<backend/tests/test_dev_entrypoint.py>)
  - [`backend/tests/test_dingtalk_channel.py`](<backend/tests/test_dingtalk_channel.py>)
  - [`backend/tests/test_discord_channel_connections.py`](<backend/tests/test_discord_channel_connections.py>)
  - [`backend/tests/test_discord_channel.py`](<backend/tests/test_discord_channel.py>)
  - [`backend/tests/test_docker_sandbox_mode_detection.py`](<backend/tests/test_docker_sandbox_mode_detection.py>)
  - [`backend/tests/test_doctor.py`](<backend/tests/test_doctor.py>)
  - [`backend/tests/test_durable_context_middleware.py`](<backend/tests/test_durable_context_middleware.py>)
  - [`backend/tests/test_dynamic_context_middleware.py`](<backend/tests/test_dynamic_context_middleware.py>)
  - [`backend/tests/test_e2b_sandbox_provider.py`](<backend/tests/test_e2b_sandbox_provider.py>)
  - [`backend/tests/test_ensure_admin.py`](<backend/tests/test_ensure_admin.py>)
  - [`backend/tests/test_exa_tools.py`](<backend/tests/test_exa_tools.py>)
  - [`backend/tests/test_fastcrw_tools.py`](<backend/tests/test_fastcrw_tools.py>)
  - [`backend/tests/test_features_router.py`](<backend/tests/test_features_router.py>)
  - [`backend/tests/test_feedback.py`](<backend/tests/test_feedback.py>)
  - [`backend/tests/test_feishu_parser.py`](<backend/tests/test_feishu_parser.py>)
  - [`backend/tests/test_file_conversion.py`](<backend/tests/test_file_conversion.py>)
  - [`backend/tests/test_file_io.py`](<backend/tests/test_file_io.py>)
  - [`backend/tests/test_firecrawl_tools.py`](<backend/tests/test_firecrawl_tools.py>)
  - [`backend/tests/test_gateway_config_freshness.py`](<backend/tests/test_gateway_config_freshness.py>)
  - [`backend/tests/test_gateway_docs_toggle.py`](<backend/tests/test_gateway_docs_toggle.py>)
  - [`backend/tests/test_gateway_imports.py`](<backend/tests/test_gateway_imports.py>)
  - [`backend/tests/test_gateway_lifespan_shutdown.py`](<backend/tests/test_gateway_lifespan_shutdown.py>)
  - [`backend/tests/test_gateway_run_drain_shutdown.py`](<backend/tests/test_gateway_run_drain_shutdown.py>)
  - [`backend/tests/test_gateway_run_recovery.py`](<backend/tests/test_gateway_run_recovery.py>)
  - [`backend/tests/test_gateway_runtime_cleanup.py`](<backend/tests/test_gateway_runtime_cleanup.py>)
  - [`backend/tests/test_gateway_services.py`](<backend/tests/test_gateway_services.py>)
  - [`backend/tests/test_github_agents_config.py`](<backend/tests/test_github_agents_config.py>)
  - [`backend/tests/test_github_app_auth.py`](<backend/tests/test_github_app_auth.py>)
  - [`backend/tests/test_github_channel.py`](<backend/tests/test_github_channel.py>)
  - [`backend/tests/test_github_dispatcher.py`](<backend/tests/test_github_dispatcher.py>)
  - [`backend/tests/test_github_identity.py`](<backend/tests/test_github_identity.py>)
  - [`backend/tests/test_github_prompts.py`](<backend/tests/test_github_prompts.py>)
  - [`backend/tests/test_github_registry.py`](<backend/tests/test_github_registry.py>)
  - [`backend/tests/test_github_token_plumbing.py`](<backend/tests/test_github_token_plumbing.py>)
  - [`backend/tests/test_github_triggers.py`](<backend/tests/test_github_triggers.py>)
  - [`backend/tests/test_github_webhooks.py`](<backend/tests/test_github_webhooks.py>)
  - [`backend/tests/test_goal_runtime.py`](<backend/tests/test_goal_runtime.py>)
  - [`backend/tests/test_goal_worker.py`](<backend/tests/test_goal_worker.py>)
  - [`backend/tests/test_groundroute_tools.py`](<backend/tests/test_groundroute_tools.py>)
  - [`backend/tests/test_guardrail_middleware.py`](<backend/tests/test_guardrail_middleware.py>)
  - [`backend/tests/test_harness_boundary.py`](<backend/tests/test_harness_boundary.py>)
  - [`backend/tests/test_harness_packaging.py`](<backend/tests/test_harness_packaging.py>)
  - [`backend/tests/test_history_batch_queries.py`](<backend/tests/test_history_batch_queries.py>)
  - [`backend/tests/test_human_input.py`](<backend/tests/test_human_input.py>)
  - [`backend/tests/test_image_search.py`](<backend/tests/test_image_search.py>)
  - [`backend/tests/test_infoquest_client.py`](<backend/tests/test_infoquest_client.py>)
  - [`backend/tests/test_initialize_admin.py`](<backend/tests/test_initialize_admin.py>)
  - [`backend/tests/test_input_polish_router.py`](<backend/tests/test_input_polish_router.py>)
  - [`backend/tests/test_input_sanitization_middleware.py`](<backend/tests/test_input_sanitization_middleware.py>)
  - [`backend/tests/test_internal_auth.py`](<backend/tests/test_internal_auth.py>)
  - [`backend/tests/test_interrupt_serialization.py`](<backend/tests/test_interrupt_serialization.py>)
  - [`backend/tests/test_invoke_acp_agent_tool.py`](<backend/tests/test_invoke_acp_agent_tool.py>)
  - [`backend/tests/test_jina_client.py`](<backend/tests/test_jina_client.py>)
  - [`backend/tests/test_jsonl_event_store_async_io.py`](<backend/tests/test_jsonl_event_store_async_io.py>)
  - [`backend/tests/test_langgraph_auth.py`](<backend/tests/test_langgraph_auth.py>)
  - [`backend/tests/test_lead_agent_model_resolution.py`](<backend/tests/test_lead_agent_model_resolution.py>)
  - [`backend/tests/test_lead_agent_prompt.py`](<backend/tests/test_lead_agent_prompt.py>)
  - [`backend/tests/test_lead_agent_skills.py`](<backend/tests/test_lead_agent_skills.py>)
  - [`backend/tests/test_llm_error_handling_middleware.py`](<backend/tests/test_llm_error_handling_middleware.py>)
  - [`backend/tests/test_local_bash_tool_loading.py`](<backend/tests/test_local_bash_tool_loading.py>)
  - [`backend/tests/test_local_sandbox_command_timeout.py`](<backend/tests/test_local_sandbox_command_timeout.py>)
  - [`backend/tests/test_local_sandbox_encoding.py`](<backend/tests/test_local_sandbox_encoding.py>)
  - [`backend/tests/test_local_sandbox_path_regex_cache.py`](<backend/tests/test_local_sandbox_path_regex_cache.py>)
  - [`backend/tests/test_local_sandbox_provider_mounts.py`](<backend/tests/test_local_sandbox_provider_mounts.py>)
  - [`backend/tests/test_local_sandbox_virtual_path_contract.py`](<backend/tests/test_local_sandbox_virtual_path_contract.py>)
  - [`backend/tests/test_local_skill_storage_write.py`](<backend/tests/test_local_skill_storage_write.py>)
  - [`backend/tests/test_logging_config.py`](<backend/tests/test_logging_config.py>)
  - [`backend/tests/test_logging_level_from_config.py`](<backend/tests/test_logging_level_from_config.py>)
  - [`backend/tests/test_loop_detection_config.py`](<backend/tests/test_loop_detection_config.py>)
  - [`backend/tests/test_loop_detection_middleware.py`](<backend/tests/test_loop_detection_middleware.py>)
  - [`backend/tests/test_loop_detection_stop_reason.py`](<backend/tests/test_loop_detection_stop_reason.py>)
  - [`backend/tests/test_mcp_cache.py`](<backend/tests/test_mcp_cache.py>)
  - [`backend/tests/test_mcp_client_config.py`](<backend/tests/test_mcp_client_config.py>)
  - [`backend/tests/test_mcp_config_secrets.py`](<backend/tests/test_mcp_config_secrets.py>)
  - [`backend/tests/test_mcp_custom_interceptors.py`](<backend/tests/test_mcp_custom_interceptors.py>)
  - [`backend/tests/test_mcp_file_migration.py`](<backend/tests/test_mcp_file_migration.py>)
  - [`backend/tests/test_mcp_oauth.py`](<backend/tests/test_mcp_oauth.py>)
  - [`backend/tests/test_mcp_routing_auto_promote.py`](<backend/tests/test_mcp_routing_auto_promote.py>)
  - [`backend/tests/test_mcp_routing_config.py`](<backend/tests/test_mcp_routing_config.py>)
  - [`backend/tests/test_mcp_routing_metadata.py`](<backend/tests/test_mcp_routing_metadata.py>)
  - [`backend/tests/test_mcp_routing_prompt.py`](<backend/tests/test_mcp_routing_prompt.py>)
  - [`backend/tests/test_mcp_session_pool.py`](<backend/tests/test_mcp_session_pool.py>)
  - [`backend/tests/test_mcp_sync_wrapper.py`](<backend/tests/test_mcp_sync_wrapper.py>)
  - [`backend/tests/test_mcp_tool_name_validation.py`](<backend/tests/test_mcp_tool_name_validation.py>)
  - [`backend/tests/test_memory_consolidation.py`](<backend/tests/test_memory_consolidation.py>)
  - [`backend/tests/test_memory_manager_pluggable.py`](<backend/tests/test_memory_manager_pluggable.py>)
  - [`backend/tests/test_memory_prompt_injection.py`](<backend/tests/test_memory_prompt_injection.py>)
  - [`backend/tests/test_memory_queue_user_isolation.py`](<backend/tests/test_memory_queue_user_isolation.py>)
  - [`backend/tests/test_memory_queue.py`](<backend/tests/test_memory_queue.py>)
  - [`backend/tests/test_memory_router.py`](<backend/tests/test_memory_router.py>)
  - [`backend/tests/test_memory_search.py`](<backend/tests/test_memory_search.py>)
  - [`backend/tests/test_memory_staleness_review.py`](<backend/tests/test_memory_staleness_review.py>)
  - [`backend/tests/test_memory_storage_user_isolation.py`](<backend/tests/test_memory_storage_user_isolation.py>)
  - [`backend/tests/test_memory_storage.py`](<backend/tests/test_memory_storage.py>)
  - [`backend/tests/test_memory_thread_meta_isolation.py`](<backend/tests/test_memory_thread_meta_isolation.py>)
  - [`backend/tests/test_memory_tools.py`](<backend/tests/test_memory_tools.py>)
  - [`backend/tests/test_memory_updater_user_isolation.py`](<backend/tests/test_memory_updater_user_isolation.py>)
  - [`backend/tests/test_memory_updater.py`](<backend/tests/test_memory_updater.py>)
  - [`backend/tests/test_memory_upload_filtering.py`](<backend/tests/test_memory_upload_filtering.py>)
  - [`backend/tests/test_migration_0004_run_ownership_dedupe.py`](<backend/tests/test_migration_0004_run_ownership_dedupe.py>)
  - [`backend/tests/test_migration_user_isolation.py`](<backend/tests/test_migration_user_isolation.py>)
  - [`backend/tests/test_mindie_provider.py`](<backend/tests/test_mindie_provider.py>)
  - [`backend/tests/test_model_config.py`](<backend/tests/test_model_config.py>)
  - [`backend/tests/test_model_factory.py`](<backend/tests/test_model_factory.py>)
  - [`backend/tests/test_monocle_tracing.py`](<backend/tests/test_monocle_tracing.py>)
  - [`backend/tests/test_multi_worker_postgres_gate.py`](<backend/tests/test_multi_worker_postgres_gate.py>)
  - [`backend/tests/test_multi_worker_run_ownership.py`](<backend/tests/test_multi_worker_run_ownership.py>)
  - [`backend/tests/test_multiturn_message_stream_graph_integration.py`](<backend/tests/test_multiturn_message_stream_graph_integration.py>)
  - [`backend/tests/test_oidc_auth.py`](<backend/tests/test_oidc_auth.py>)
  - [`backend/tests/test_openapi_operation_ids.py`](<backend/tests/test_openapi_operation_ids.py>)
  - [`backend/tests/test_owner_isolation.py`](<backend/tests/test_owner_isolation.py>)
  - [`backend/tests/test_patched_deepseek.py`](<backend/tests/test_patched_deepseek.py>)
  - [`backend/tests/test_patched_mimo.py`](<backend/tests/test_patched_mimo.py>)
  - [`backend/tests/test_patched_minimax.py`](<backend/tests/test_patched_minimax.py>)
  - [`backend/tests/test_patched_openai.py`](<backend/tests/test_patched_openai.py>)
  - [`backend/tests/test_patched_stepfun.py`](<backend/tests/test_patched_stepfun.py>)
  - [`backend/tests/test_paths_user_isolation.py`](<backend/tests/test_paths_user_isolation.py>)
  - [`backend/tests/test_persistence_autogen_script.py`](<backend/tests/test_persistence_autogen_script.py>)
  - [`backend/tests/test_persistence_bootstrap_concurrency.py`](<backend/tests/test_persistence_bootstrap_concurrency.py>)
  - [`backend/tests/test_persistence_bootstrap_pg_lock.py`](<backend/tests/test_persistence_bootstrap_pg_lock.py>)
  - [`backend/tests/test_persistence_bootstrap_regression.py`](<backend/tests/test_persistence_bootstrap_regression.py>)
  - [`backend/tests/test_persistence_bootstrap_sqlite_lock.py`](<backend/tests/test_persistence_bootstrap_sqlite_lock.py>)
  - [`backend/tests/test_persistence_bootstrap_url.py`](<backend/tests/test_persistence_bootstrap_url.py>)
  - [`backend/tests/test_persistence_bootstrap.py`](<backend/tests/test_persistence_bootstrap.py>)
  - [`backend/tests/test_persistence_migrations_env.py`](<backend/tests/test_persistence_migrations_env.py>)
  - [`backend/tests/test_persistence_scaffold.py`](<backend/tests/test_persistence_scaffold.py>)
  - [`backend/tests/test_persistence_timezone.py`](<backend/tests/test_persistence_timezone.py>)
  - [`backend/tests/test_present_file_tool_core_logic.py`](<backend/tests/test_present_file_tool_core_logic.py>)
  - [`backend/tests/test_provisioner_kubeconfig.py`](<backend/tests/test_provisioner_kubeconfig.py>)
  - [`backend/tests/test_provisioner_pvc_volumes.py`](<backend/tests/test_provisioner_pvc_volumes.py>)
  - [`backend/tests/test_provisioner_request_threading.py`](<backend/tests/test_provisioner_request_threading.py>)
  - [`backend/tests/test_read_before_write_middleware.py`](<backend/tests/test_read_before_write_middleware.py>)
  - [`backend/tests/test_read_file_line_range.py`](<backend/tests/test_read_file_line_range.py>)
  - [`backend/tests/test_read_file_tool_binary.py`](<backend/tests/test_read_file_tool_binary.py>)
  - [`backend/tests/test_readability.py`](<backend/tests/test_readability.py>)
  - [`backend/tests/test_reflection_resolvers.py`](<backend/tests/test_reflection_resolvers.py>)
  - [`backend/tests/test_reload_boundary.py`](<backend/tests/test_reload_boundary.py>)
  - [`backend/tests/test_remote_sandbox_backend.py`](<backend/tests/test_remote_sandbox_backend.py>)
  - [`backend/tests/test_replay_golden.py`](<backend/tests/test_replay_golden.py>)
  - [`backend/tests/test_replay_provider.py`](<backend/tests/test_replay_provider.py>)
  - [`backend/tests/test_review_changed_public_skills.py`](<backend/tests/test_review_changed_public_skills.py>)
  - [`backend/tests/test_review_skill_package_tool.py`](<backend/tests/test_review_skill_package_tool.py>)
  - [`backend/tests/test_run_duration_checkpoint.py`](<backend/tests/test_run_duration_checkpoint.py>)
  - [`backend/tests/test_run_event_store_by_run_index.py`](<backend/tests/test_run_event_store_by_run_index.py>)
  - [`backend/tests/test_run_event_store_filter.py`](<backend/tests/test_run_event_store_filter.py>)
  - [`backend/tests/test_run_event_store_pagination.py`](<backend/tests/test_run_event_store_pagination.py>)
  - [`backend/tests/test_run_event_store.py`](<backend/tests/test_run_event_store.py>)
  - [`backend/tests/test_run_events_endpoint.py`](<backend/tests/test_run_events_endpoint.py>)
  - [`backend/tests/test_run_journal.py`](<backend/tests/test_run_journal.py>)
  - [`backend/tests/test_run_manager.py`](<backend/tests/test_run_manager.py>)
  - [`backend/tests/test_run_naming.py`](<backend/tests/test_run_naming.py>)
  - [`backend/tests/test_run_repository.py`](<backend/tests/test_run_repository.py>)
  - [`backend/tests/test_run_worker_rollback.py`](<backend/tests/test_run_worker_rollback.py>)
  - [`backend/tests/test_runs_api_endpoints.py`](<backend/tests/test_runs_api_endpoints.py>)
  - [`backend/tests/test_runtime_channel_config_merge.py`](<backend/tests/test_runtime_channel_config_merge.py>)
  - [`backend/tests/test_runtime_lifecycle_e2e.py`](<backend/tests/test_runtime_lifecycle_e2e.py>)
  - [`backend/tests/test_runtime_paths.py`](<backend/tests/test_runtime_paths.py>)
  - [`backend/tests/test_safety_finish_reason_graph_integration.py`](<backend/tests/test_safety_finish_reason_graph_integration.py>)
  - [`backend/tests/test_safety_finish_reason_middleware.py`](<backend/tests/test_safety_finish_reason_middleware.py>)
  - [`backend/tests/test_safety_termination_detectors.py`](<backend/tests/test_safety_termination_detectors.py>)
  - [`backend/tests/test_sandbox_audit_middleware.py`](<backend/tests/test_sandbox_audit_middleware.py>)
  - [`backend/tests/test_sandbox_memory_profile_script.py`](<backend/tests/test_sandbox_memory_profile_script.py>)
  - [`backend/tests/test_sandbox_middleware.py`](<backend/tests/test_sandbox_middleware.py>)
  - [`backend/tests/test_sandbox_orphan_reconciliation_e2e.py`](<backend/tests/test_sandbox_orphan_reconciliation_e2e.py>)
  - [`backend/tests/test_sandbox_orphan_reconciliation.py`](<backend/tests/test_sandbox_orphan_reconciliation.py>)
  - [`backend/tests/test_sandbox_path_patterns.py`](<backend/tests/test_sandbox_path_patterns.py>)
  - [`backend/tests/test_sandbox_provider_lifecycle.py`](<backend/tests/test_sandbox_provider_lifecycle.py>)
  - [`backend/tests/test_sandbox_search_tools.py`](<backend/tests/test_sandbox_search_tools.py>)
  - [`backend/tests/test_sandbox_tools_security.py`](<backend/tests/test_sandbox_tools_security.py>)
  - [`backend/tests/test_sandbox_windows_path_normalization.py`](<backend/tests/test_sandbox_windows_path_normalization.py>)
  - [`backend/tests/test_scan_changed_blocking_io.py`](<backend/tests/test_scan_changed_blocking_io.py>)
  - [`backend/tests/test_scheduled_task_claims.py`](<backend/tests/test_scheduled_task_claims.py>)
  - [`backend/tests/test_scheduled_task_lifecycle.py`](<backend/tests/test_scheduled_task_lifecycle.py>)
  - [`backend/tests/test_scheduled_task_models.py`](<backend/tests/test_scheduled_task_models.py>)
  - [`backend/tests/test_scheduled_task_repository.py`](<backend/tests/test_scheduled_task_repository.py>)
  - [`backend/tests/test_scheduled_task_router_behavior.py`](<backend/tests/test_scheduled_task_router_behavior.py>)
  - [`backend/tests/test_scheduled_task_router.py`](<backend/tests/test_scheduled_task_router.py>)
  - [`backend/tests/test_scheduled_task_schedules.py`](<backend/tests/test_scheduled_task_schedules.py>)
  - [`backend/tests/test_scheduled_task_service.py`](<backend/tests/test_scheduled_task_service.py>)
  - [`backend/tests/test_searxng_client.py`](<backend/tests/test_searxng_client.py>)
  - [`backend/tests/test_security_scanner.py`](<backend/tests/test_security_scanner.py>)
  - [`backend/tests/test_serialization.py`](<backend/tests/test_serialization.py>)
  - [`backend/tests/test_serialize_message_content.py`](<backend/tests/test_serialize_message_content.py>)
  - [`backend/tests/test_serper_tools.py`](<backend/tests/test_serper_tools.py>)
  - [`backend/tests/test_serve_nginx_stop.py`](<backend/tests/test_serve_nginx_stop.py>)
  - [`backend/tests/test_session_pool_singleton_lifecycle.py`](<backend/tests/test_session_pool_singleton_lifecycle.py>)
  - [`backend/tests/test_setup_agent_e2e_user_isolation.py`](<backend/tests/test_setup_agent_e2e_user_isolation.py>)
  - [`backend/tests/test_setup_agent_http_e2e_real_server.py`](<backend/tests/test_setup_agent_http_e2e_real_server.py>)
  - [`backend/tests/test_setup_agent_tool.py`](<backend/tests/test_setup_agent_tool.py>)
  - [`backend/tests/test_setup_wizard.py`](<backend/tests/test_setup_wizard.py>)
  - [`backend/tests/test_should_ignore_name.py`](<backend/tests/test_should_ignore_name.py>)
  - [`backend/tests/test_skill_catalog.py`](<backend/tests/test_skill_catalog.py>)
  - [`backend/tests/test_skill_container_path_defaults.py`](<backend/tests/test_skill_container_path_defaults.py>)
  - [`backend/tests/test_skill_context.py`](<backend/tests/test_skill_context.py>)
  - [`backend/tests/test_skill_describe.py`](<backend/tests/test_skill_describe.py>)
  - [`backend/tests/test_skill_manage_tool.py`](<backend/tests/test_skill_manage_tool.py>)
  - [`backend/tests/test_skill_metadata_prompt_injection.py`](<backend/tests/test_skill_metadata_prompt_injection.py>)
  - [`backend/tests/test_skill_permissions.py`](<backend/tests/test_skill_permissions.py>)
  - [`backend/tests/test_skill_request_scoped_secrets.py`](<backend/tests/test_skill_request_scoped_secrets.py>)
  - [`backend/tests/test_skill_review_core.py`](<backend/tests/test_skill_review_core.py>)
  - [`backend/tests/test_skill_reviewer_public_skill.py`](<backend/tests/test_skill_reviewer_public_skill.py>)
  - [`backend/tests/test_skill_storage_lifecycle.py`](<backend/tests/test_skill_storage_lifecycle.py>)
  - [`backend/tests/test_skills_archive_root.py`](<backend/tests/test_skills_archive_root.py>)
  - [`backend/tests/test_skills_bundled.py`](<backend/tests/test_skills_bundled.py>)
  - [`backend/tests/test_skills_custom_router.py`](<backend/tests/test_skills_custom_router.py>)
  - [`backend/tests/test_skills_installer.py`](<backend/tests/test_skills_installer.py>)
  - [`backend/tests/test_skills_loader.py`](<backend/tests/test_skills_loader.py>)
  - [`backend/tests/test_skills_parser.py`](<backend/tests/test_skills_parser.py>)
  - [`backend/tests/test_skills_router_authz.py`](<backend/tests/test_skills_router_authz.py>)
  - [`backend/tests/test_skills_validation.py`](<backend/tests/test_skills_validation.py>)
  - [`backend/tests/test_skillscan_native.py`](<backend/tests/test_skillscan_native.py>)
  - [`backend/tests/test_slack_channel_connections.py`](<backend/tests/test_slack_channel_connections.py>)
  - [`backend/tests/test_slash_skill_contract.py`](<backend/tests/test_slash_skill_contract.py>)
  - [`backend/tests/test_slash_skills.py`](<backend/tests/test_slash_skills.py>)
  - [`backend/tests/test_soul_prompt_injection.py`](<backend/tests/test_soul_prompt_injection.py>)
  - [`backend/tests/test_sse_format.py`](<backend/tests/test_sse_format.py>)
  - [`backend/tests/test_stateless_runs_owner_isolation.py`](<backend/tests/test_stateless_runs_owner_isolation.py>)
  - [`backend/tests/test_str_replace_empty_file.py`](<backend/tests/test_str_replace_empty_file.py>)
  - [`backend/tests/test_stream_bridge.py`](<backend/tests/test_stream_bridge.py>)
  - [`backend/tests/test_subagent_checkpointer_isolation.py`](<backend/tests/test_subagent_checkpointer_isolation.py>)
  - [`backend/tests/test_subagent_deferred_promotion_integration.py`](<backend/tests/test_subagent_deferred_promotion_integration.py>)
  - [`backend/tests/test_subagent_description_injection.py`](<backend/tests/test_subagent_description_injection.py>)
  - [`backend/tests/test_subagent_executor.py`](<backend/tests/test_subagent_executor.py>)
  - [`backend/tests/test_subagent_limit_middleware.py`](<backend/tests/test_subagent_limit_middleware.py>)
  - [`backend/tests/test_subagent_prompt_security.py`](<backend/tests/test_subagent_prompt_security.py>)
  - [`backend/tests/test_subagent_skills_config.py`](<backend/tests/test_subagent_skills_config.py>)
  - [`backend/tests/test_subagent_status_contract.py`](<backend/tests/test_subagent_status_contract.py>)
  - [`backend/tests/test_subagent_step_events.py`](<backend/tests/test_subagent_step_events.py>)
  - [`backend/tests/test_subagent_timeout_config.py`](<backend/tests/test_subagent_timeout_config.py>)
  - [`backend/tests/test_subagent_token_collector.py`](<backend/tests/test_subagent_token_collector.py>)
  - [`backend/tests/test_suggestions_router.py`](<backend/tests/test_suggestions_router.py>)
  - [`backend/tests/test_summarization_middleware.py`](<backend/tests/test_summarization_middleware.py>)
  - [`backend/tests/test_summarization_summary_text.py`](<backend/tests/test_summarization_summary_text.py>)
  - [`backend/tests/test_support_bundle.py`](<backend/tests/test_support_bundle.py>)
  - [`backend/tests/test_system_message_coalescing_middleware.py`](<backend/tests/test_system_message_coalescing_middleware.py>)
  - [`backend/tests/test_task_tool_core_logic.py`](<backend/tests/test_task_tool_core_logic.py>)
  - [`backend/tests/test_task_tool_usage_recorder.py`](<backend/tests/test_task_tool_usage_recorder.py>)
  - [`backend/tests/test_telegram_channel_connections.py`](<backend/tests/test_telegram_channel_connections.py>)
  - [`backend/tests/test_terminal_response_middleware.py`](<backend/tests/test_terminal_response_middleware.py>)
  - [`backend/tests/test_thread_data_middleware.py`](<backend/tests/test_thread_data_middleware.py>)
  - [`backend/tests/test_thread_messages_feedback.py`](<backend/tests/test_thread_messages_feedback.py>)
  - [`backend/tests/test_thread_messages_page.py`](<backend/tests/test_thread_messages_page.py>)
  - [`backend/tests/test_thread_meta_repo.py`](<backend/tests/test_thread_meta_repo.py>)
  - [`backend/tests/test_thread_regenerate_prepare.py`](<backend/tests/test_thread_regenerate_prepare.py>)
  - [`backend/tests/test_thread_run_messages_pagination.py`](<backend/tests/test_thread_run_messages_pagination.py>)
  - [`backend/tests/test_thread_state_promoted.py`](<backend/tests/test_thread_state_promoted.py>)
  - [`backend/tests/test_thread_state_reducers.py`](<backend/tests/test_thread_state_reducers.py>)
  - [`backend/tests/test_thread_token_usage.py`](<backend/tests/test_thread_token_usage.py>)
  - [`backend/tests/test_threads_router.py`](<backend/tests/test_threads_router.py>)
  - [`backend/tests/test_three_way_skills_mount_e2e.py`](<backend/tests/test_three_way_skills_mount_e2e.py>)
  - [`backend/tests/test_tiktoken_cache_and_count_tokens.py`](<backend/tests/test_tiktoken_cache_and_count_tokens.py>)
  - [`backend/tests/test_title_generation.py`](<backend/tests/test_title_generation.py>)
  - [`backend/tests/test_title_middleware_core_logic.py`](<backend/tests/test_title_middleware_core_logic.py>)
  - [`backend/tests/test_todo_middleware.py`](<backend/tests/test_todo_middleware.py>)
  - [`backend/tests/test_token_budget_middleware.py`](<backend/tests/test_token_budget_middleware.py>)
  - [`backend/tests/test_token_usage_by_model.py`](<backend/tests/test_token_usage_by_model.py>)
  - [`backend/tests/test_token_usage_config.py`](<backend/tests/test_token_usage_config.py>)
  - [`backend/tests/test_token_usage_middleware.py`](<backend/tests/test_token_usage_middleware.py>)
  - [`backend/tests/test_token_usage.py`](<backend/tests/test_token_usage.py>)
  - [`backend/tests/test_tool_args_schema_no_pydantic_warning.py`](<backend/tests/test_tool_args_schema_no_pydantic_warning.py>)
  - [`backend/tests/test_tool_deduplication.py`](<backend/tests/test_tool_deduplication.py>)
  - [`backend/tests/test_tool_error_handling_middleware.py`](<backend/tests/test_tool_error_handling_middleware.py>)
  - [`backend/tests/test_tool_error_handling_subagent_stamp.py`](<backend/tests/test_tool_error_handling_subagent_stamp.py>)
  - [`backend/tests/test_tool_output_budget_middleware.py`](<backend/tests/test_tool_output_budget_middleware.py>)
  - [`backend/tests/test_tool_output_truncation.py`](<backend/tests/test_tool_output_truncation.py>)
  - [`backend/tests/test_tool_progress_middleware.py`](<backend/tests/test_tool_progress_middleware.py>)
  - [`backend/tests/test_tool_result_meta.py`](<backend/tests/test_tool_result_meta.py>)
  - [`backend/tests/test_tool_result_sanitization_middleware.py`](<backend/tests/test_tool_result_sanitization_middleware.py>)
  - [`backend/tests/test_tool_search.py`](<backend/tests/test_tool_search.py>)
  - [`backend/tests/test_trace_context.py`](<backend/tests/test_trace_context.py>)
  - [`backend/tests/test_trace_middleware.py`](<backend/tests/test_trace_middleware.py>)
  - [`backend/tests/test_tracing_config.py`](<backend/tests/test_tracing_config.py>)
  - [`backend/tests/test_tracing_factory.py`](<backend/tests/test_tracing_factory.py>)
  - [`backend/tests/test_tracing_metadata.py`](<backend/tests/test_tracing_metadata.py>)
  - [`backend/tests/test_tui_app.py`](<backend/tests/test_tui_app.py>)
  - [`backend/tests/test_tui_cli_main.py`](<backend/tests/test_tui_cli_main.py>)
  - [`backend/tests/test_tui_cli.py`](<backend/tests/test_tui_cli.py>)
  - [`backend/tests/test_tui_command_registry.py`](<backend/tests/test_tui_command_registry.py>)
  - [`backend/tests/test_tui_composer.py`](<backend/tests/test_tui_composer.py>)
  - [`backend/tests/test_tui_input_history.py`](<backend/tests/test_tui_input_history.py>)
  - [`backend/tests/test_tui_message_format.py`](<backend/tests/test_tui_message_format.py>)
  - [`backend/tests/test_tui_overlays.py`](<backend/tests/test_tui_overlays.py>)
  - [`backend/tests/test_tui_palette_render.py`](<backend/tests/test_tui_palette_render.py>)
  - [`backend/tests/test_tui_palette.py`](<backend/tests/test_tui_palette.py>)
  - [`backend/tests/test_tui_persistence.py`](<backend/tests/test_tui_persistence.py>)
  - [`backend/tests/test_tui_render.py`](<backend/tests/test_tui_render.py>)
  - [`backend/tests/test_tui_runtime.py`](<backend/tests/test_tui_runtime.py>)
  - [`backend/tests/test_tui_session.py`](<backend/tests/test_tui_session.py>)
  - [`backend/tests/test_tui_view_state.py`](<backend/tests/test_tui_view_state.py>)
  - [`backend/tests/test_update_agent_e2e_user_isolation.py`](<backend/tests/test_update_agent_e2e_user_isolation.py>)
  - [`backend/tests/test_update_agent_tool.py`](<backend/tests/test_update_agent_tool.py>)
  - [`backend/tests/test_uploads_manager.py`](<backend/tests/test_uploads_manager.py>)
  - [`backend/tests/test_uploads_middleware_core_logic.py`](<backend/tests/test_uploads_middleware_core_logic.py>)
  - [`backend/tests/test_uploads_router.py`](<backend/tests/test_uploads_router.py>)
  - [`backend/tests/test_user_context.py`](<backend/tests/test_user_context.py>)
  - [`backend/tests/test_user_scoped_skill_storage.py`](<backend/tests/test_user_scoped_skill_storage.py>)
  - [`backend/tests/test_utils_llm_text.py`](<backend/tests/test_utils_llm_text.py>)
  - [`backend/tests/test_utils_messages.py`](<backend/tests/test_utils_messages.py>)
  - [`backend/tests/test_utils_time.py`](<backend/tests/test_utils_time.py>)
  - [`backend/tests/test_uvicorn_reload_exclude.py`](<backend/tests/test_uvicorn_reload_exclude.py>)
  - [`backend/tests/test_view_image_middleware.py`](<backend/tests/test_view_image_middleware.py>)
  - [`backend/tests/test_view_image_tool.py`](<backend/tests/test_view_image_tool.py>)
  - [`backend/tests/test_vllm_provider.py`](<backend/tests/test_vllm_provider.py>)
  - [`backend/tests/test_wait_disconnect_handling.py`](<backend/tests/test_wait_disconnect_handling.py>)
  - [`backend/tests/test_warm_pool_lifecycle.py`](<backend/tests/test_warm_pool_lifecycle.py>)
  - [`backend/tests/test_wechat_channel.py`](<backend/tests/test_wechat_channel.py>)
  - [`backend/tests/test_wecom_ws_text.py`](<backend/tests/test_wecom_ws_text.py>)
  - [`backend/tests/test_worker_langfuse_metadata.py`](<backend/tests/test_worker_langfuse_metadata.py>)
  - [`backend/tests/test_worker_subagent_persistence.py`](<backend/tests/test_worker_subagent_persistence.py>)
  - [`backend/tests/test_workspace_changes.py`](<backend/tests/test_workspace_changes.py>)
  - [`backend/tests/test_write_file_tool_size_guard.py`](<backend/tests/test_write_file_tool_size_guard.py>)

### 164. `tests`

- 作用：验证仓库公共技能加载与多媒体技能契约。
- 阅读重点：关注跨模块公共能力的回归保障。
- 文件：
  - [`tests/skills/skill_loader.py`](<tests/skills/skill_loader.py>)
  - [`tests/skills/test_image_generation.py`](<tests/skills/test_image_generation.py>)
  - [`tests/skills/test_music_generation.py`](<tests/skills/test_music_generation.py>)
  - [`tests/skills/test_podcast_generation.py`](<tests/skills/test_podcast_generation.py>)
  - [`tests/skills/test_video_generation.py`](<tests/skills/test_video_generation.py>)

## 第六阶段：公共技能实现

### 165. `skills/public/chart-visualization`

- 作用：提供“chart-visualization”公共技能的提示资源、执行脚本和评测资产。
- 阅读重点：先读 SKILL 定义的契约，再看脚本如何落地；本索引仅列代码文件。
- 文件：
  - [`skills/public/chart-visualization/scripts/generate.js`](<skills/public/chart-visualization/scripts/generate.js>)

### 166. `skills/public/claude-to-deerflow`

- 作用：提供“claude-to-deerflow”公共技能的提示资源、执行脚本和评测资产。
- 阅读重点：先读 SKILL 定义的契约，再看脚本如何落地；本索引仅列代码文件。
- 文件：
  - [`skills/public/claude-to-deerflow/scripts/chat.sh`](<skills/public/claude-to-deerflow/scripts/chat.sh>)
  - [`skills/public/claude-to-deerflow/scripts/status.sh`](<skills/public/claude-to-deerflow/scripts/status.sh>)

### 167. `skills/public/data-analysis`

- 作用：提供“data-analysis”公共技能的提示资源、执行脚本和评测资产。
- 阅读重点：先读 SKILL 定义的契约，再看脚本如何落地；本索引仅列代码文件。
- 文件：
  - [`skills/public/data-analysis/scripts/analyze.py`](<skills/public/data-analysis/scripts/analyze.py>)

### 168. `skills/public/find-skills`

- 作用：提供“find-skills”公共技能的提示资源、执行脚本和评测资产。
- 阅读重点：先读 SKILL 定义的契约，再看脚本如何落地；本索引仅列代码文件。
- 文件：
  - [`skills/public/find-skills/scripts/install-skill.sh`](<skills/public/find-skills/scripts/install-skill.sh>)

### 169. `skills/public/github-deep-research`

- 作用：提供“github-deep-research”公共技能的提示资源、执行脚本和评测资产。
- 阅读重点：先读 SKILL 定义的契约，再看脚本如何落地；本索引仅列代码文件。
- 文件：
  - [`skills/public/github-deep-research/scripts/github_api.py`](<skills/public/github-deep-research/scripts/github_api.py>)

### 170. `skills/public/image-generation`

- 作用：提供“image-generation”公共技能的提示资源、执行脚本和评测资产。
- 阅读重点：先读 SKILL 定义的契约，再看脚本如何落地；本索引仅列代码文件。
- 文件：
  - [`skills/public/image-generation/scripts/generate.py`](<skills/public/image-generation/scripts/generate.py>)

### 171. `skills/public/music-generation`

- 作用：提供“music-generation”公共技能的提示资源、执行脚本和评测资产。
- 阅读重点：先读 SKILL 定义的契约，再看脚本如何落地；本索引仅列代码文件。
- 文件：
  - [`skills/public/music-generation/scripts/generate.py`](<skills/public/music-generation/scripts/generate.py>)

### 172. `skills/public/podcast-generation`

- 作用：提供“podcast-generation”公共技能的提示资源、执行脚本和评测资产。
- 阅读重点：先读 SKILL 定义的契约，再看脚本如何落地；本索引仅列代码文件。
- 文件：
  - [`skills/public/podcast-generation/scripts/generate.py`](<skills/public/podcast-generation/scripts/generate.py>)

### 173. `skills/public/ppt-generation`

- 作用：提供“ppt-generation”公共技能的提示资源、执行脚本和评测资产。
- 阅读重点：先读 SKILL 定义的契约，再看脚本如何落地；本索引仅列代码文件。
- 文件：
  - [`skills/public/ppt-generation/scripts/generate.py`](<skills/public/ppt-generation/scripts/generate.py>)

### 174. `skills/public/skill-creator`

- 作用：提供“skill-creator”公共技能的提示资源、执行脚本和评测资产。
- 阅读重点：先读 SKILL 定义的契约，再看脚本如何落地；本索引仅列代码文件。
- 文件：
  - [`skills/public/skill-creator/assets/eval_review.html`](<skills/public/skill-creator/assets/eval_review.html>)
  - [`skills/public/skill-creator/eval-viewer/generate_review.py`](<skills/public/skill-creator/eval-viewer/generate_review.py>)
  - [`skills/public/skill-creator/eval-viewer/viewer.html`](<skills/public/skill-creator/eval-viewer/viewer.html>)
  - [`skills/public/skill-creator/scripts/aggregate_benchmark.py`](<skills/public/skill-creator/scripts/aggregate_benchmark.py>)
  - [`skills/public/skill-creator/scripts/generate_report.py`](<skills/public/skill-creator/scripts/generate_report.py>)
  - [`skills/public/skill-creator/scripts/improve_description.py`](<skills/public/skill-creator/scripts/improve_description.py>)
  - [`skills/public/skill-creator/scripts/init_skill.py`](<skills/public/skill-creator/scripts/init_skill.py>)
  - [`skills/public/skill-creator/scripts/package_skill.py`](<skills/public/skill-creator/scripts/package_skill.py>)
  - [`skills/public/skill-creator/scripts/quick_validate.py`](<skills/public/skill-creator/scripts/quick_validate.py>)
  - [`skills/public/skill-creator/scripts/run_eval.py`](<skills/public/skill-creator/scripts/run_eval.py>)
  - [`skills/public/skill-creator/scripts/run_loop.py`](<skills/public/skill-creator/scripts/run_loop.py>)
  - [`skills/public/skill-creator/scripts/utils.py`](<skills/public/skill-creator/scripts/utils.py>)

### 175. `skills/public/systematic-literature-review`

- 作用：提供“systematic-literature-review”公共技能的提示资源、执行脚本和评测资产。
- 阅读重点：先读 SKILL 定义的契约，再看脚本如何落地；本索引仅列代码文件。
- 文件：
  - [`skills/public/systematic-literature-review/scripts/arxiv_search.py`](<skills/public/systematic-literature-review/scripts/arxiv_search.py>)

### 176. `skills/public/vercel-deploy-claimable`

- 作用：提供“vercel-deploy-claimable”公共技能的提示资源、执行脚本和评测资产。
- 阅读重点：先读 SKILL 定义的契约，再看脚本如何落地；本索引仅列代码文件。
- 文件：
  - [`skills/public/vercel-deploy-claimable/scripts/deploy.sh`](<skills/public/vercel-deploy-claimable/scripts/deploy.sh>)

### 177. `skills/public/video-generation`

- 作用：提供“video-generation”公共技能的提示资源、执行脚本和评测资产。
- 阅读重点：先读 SKILL 定义的契约，再看脚本如何落地；本索引仅列代码文件。
- 文件：
  - [`skills/public/video-generation/scripts/generate.py`](<skills/public/video-generation/scripts/generate.py>)

## 第七阶段：部署、构建与工程自动化

### 178. `scripts/wizard`

- 作用：实现交互式安装向导的界面、步骤和配置写入。
- 阅读重点：从 setup_wizard.py 追踪各步骤如何生成本地配置。
- 文件：
  - [`scripts/wizard/__init__.py`](<scripts/wizard/__init__.py>)
  - [`scripts/wizard/providers.py`](<scripts/wizard/providers.py>)
  - [`scripts/wizard/steps/__init__.py`](<scripts/wizard/steps/__init__.py>)
  - [`scripts/wizard/steps/channels.py`](<scripts/wizard/steps/channels.py>)
  - [`scripts/wizard/steps/execution.py`](<scripts/wizard/steps/execution.py>)
  - [`scripts/wizard/steps/llm.py`](<scripts/wizard/steps/llm.py>)
  - [`scripts/wizard/steps/search.py`](<scripts/wizard/steps/search.py>)
  - [`scripts/wizard/ui.py`](<scripts/wizard/ui.py>)
  - [`scripts/wizard/writer.py`](<scripts/wizard/writer.py>)

### 179. `scripts`

- 作用：提供启动、检查、诊断、部署、版本和维护自动化脚本。
- 阅读重点：按 Makefile 调用关系阅读常用脚本，再看专项诊断工具。
- 文件：
  - [`scripts/_detector_cli.py`](<scripts/_detector_cli.py>)
  - [`scripts/bump_version.sh`](<scripts/bump_version.sh>)
  - [`scripts/check_config_version.sh`](<scripts/check_config_version.sh>)
  - [`scripts/check.py`](<scripts/check.py>)
  - [`scripts/check.sh`](<scripts/check.sh>)
  - [`scripts/cleanup-containers.sh`](<scripts/cleanup-containers.sh>)
  - [`scripts/config-upgrade.sh`](<scripts/config-upgrade.sh>)
  - [`scripts/configure.py`](<scripts/configure.py>)
  - [`scripts/deploy.sh`](<scripts/deploy.sh>)
  - [`scripts/detect_blocking_io_static.py`](<scripts/detect_blocking_io_static.py>)
  - [`scripts/detect_thread_boundaries.py`](<scripts/detect_thread_boundaries.py>)
  - [`scripts/detect_uv_extras.py`](<scripts/detect_uv_extras.py>)
  - [`scripts/docker.sh`](<scripts/docker.sh>)
  - [`scripts/doctor.py`](<scripts/doctor.py>)
  - [`scripts/export_claude_code_oauth.py`](<scripts/export_claude_code_oauth.py>)
  - [`scripts/load_memory_sample.py`](<scripts/load_memory_sample.py>)
  - [`scripts/nginx.sh`](<scripts/nginx.sh>)
  - [`scripts/review_changed_public_skills.py`](<scripts/review_changed_public_skills.py>)
  - [`scripts/run-with-git-bash.cmd`](<scripts/run-with-git-bash.cmd>)
  - [`scripts/sandbox_memory_profile.py`](<scripts/sandbox_memory_profile.py>)
  - [`scripts/scan_changed_blocking_io.py`](<scripts/scan_changed_blocking_io.py>)
  - [`scripts/serve.sh`](<scripts/serve.sh>)
  - [`scripts/setup_wizard.py`](<scripts/setup_wizard.py>)
  - [`scripts/setup-sandbox.sh`](<scripts/setup-sandbox.sh>)
  - [`scripts/start-daemon.sh`](<scripts/start-daemon.sh>)
  - [`scripts/support_bundle.py`](<scripts/support_bundle.py>)
  - [`scripts/sync_labels.py`](<scripts/sync_labels.py>)
  - [`scripts/tool-error-degradation-detection.sh`](<scripts/tool-error-degradation-detection.sh>)
  - [`scripts/verify_versions.sh`](<scripts/verify_versions.sh>)
  - [`scripts/wait-for-port.sh`](<scripts/wait-for-port.sh>)

### 180. `backend/scripts`

- 作用：提供后端迁移生成和沙箱性能基准脚本。
- 阅读重点：关注数据库迁移与性能验证流程。
- 文件：
  - [`backend/scripts/_autogen_revision.py`](<backend/scripts/_autogen_revision.py>)
  - [`backend/scripts/benchmark/bench_sandbox_provider.py`](<backend/scripts/benchmark/bench_sandbox_provider.py>)
  - [`backend/scripts/benchmark/summarize_bench.py`](<backend/scripts/benchmark/summarize_bench.py>)
  - [`backend/scripts/build_fixture_from_jsonl.py`](<backend/scripts/build_fixture_from_jsonl.py>)
  - [`backend/scripts/e2e_safety_termination_demo.py`](<backend/scripts/e2e_safety_termination_demo.py>)
  - [`backend/scripts/migrate_user_isolation.py`](<backend/scripts/migrate_user_isolation.py>)
  - [`backend/scripts/record_gateway.py`](<backend/scripts/record_gateway.py>)
  - [`backend/scripts/run_replay_gateway.py`](<backend/scripts/run_replay_gateway.py>)

### 181. `frontend/scripts`

- 作用：提供前端演示数据保存等辅助脚本。
- 阅读重点：理解开发演示资产的生成方式。
- 文件：
  - [`frontend/scripts/save-demo.js`](<frontend/scripts/save-demo.js>)

### 182. `frontend/public`

- 作用：保存可直接运行的前端演示页面代码和样式。
- 阅读重点：这些文件是演示产物，但仍属于可执行页面代码。
- 文件：
  - [`frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/css/style.css`](<frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/css/style.css>)
  - [`frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/favicon.html`](<frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/favicon.html>)
  - [`frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/index.html`](<frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/index.html>)
  - [`frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/js/data.js`](<frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/js/data.js>)
  - [`frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/js/main.js`](<frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/js/main.js>)
  - [`frontend/public/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/user-data/outputs/index.html`](<frontend/public/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/user-data/outputs/index.html>)
  - [`frontend/public/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/user-data/outputs/script.js`](<frontend/public/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/user-data/outputs/script.js>)
  - [`frontend/public/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/user-data/outputs/style.css`](<frontend/public/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/user-data/outputs/style.css>)
  - [`frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/user-data/outputs/index.html`](<frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/user-data/outputs/index.html>)
  - [`frontend/public/demo/threads/c02bb4d5-4202-490e-ae8f-ff4864fc0d2e/user-data/outputs/index.html`](<frontend/public/demo/threads/c02bb4d5-4202-490e-ae8f-ff4864fc0d2e/user-data/outputs/index.html>)
  - [`frontend/public/demo/threads/c02bb4d5-4202-490e-ae8f-ff4864fc0d2e/user-data/outputs/script.js`](<frontend/public/demo/threads/c02bb4d5-4202-490e-ae8f-ff4864fc0d2e/user-data/outputs/script.js>)
  - [`frontend/public/demo/threads/c02bb4d5-4202-490e-ae8f-ff4864fc0d2e/user-data/outputs/styles.css`](<frontend/public/demo/threads/c02bb4d5-4202-490e-ae8f-ff4864fc0d2e/user-data/outputs/styles.css>)
  - [`frontend/public/demo/threads/f4125791-0128-402a-8ca9-50e0947557e4/user-data/outputs/index.html`](<frontend/public/demo/threads/f4125791-0128-402a-8ca9-50e0947557e4/user-data/outputs/index.html>)
  - [`frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/user-data/outputs/index.html`](<frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/user-data/outputs/index.html>)

### 183. `frontend`

- 作用：定义前端构建、测试、格式化、容器和框架配置。
- 阅读重点：结合 package scripts 理解开发与生产构建链。
- 文件：
  - [`frontend/Dockerfile`](<frontend/Dockerfile>)
  - [`frontend/eslint.config.js`](<frontend/eslint.config.js>)
  - [`frontend/Makefile`](<frontend/Makefile>)
  - [`frontend/next.config.js`](<frontend/next.config.js>)
  - [`frontend/playwright.config.ts`](<frontend/playwright.config.ts>)
  - [`frontend/playwright.real-backend.config.ts`](<frontend/playwright.real-backend.config.ts>)
  - [`frontend/playwright.record.config.ts`](<frontend/playwright.record.config.ts>)
  - [`frontend/pnpm-lock.yaml`](<frontend/pnpm-lock.yaml>)
  - [`frontend/pnpm-workspace.yaml`](<frontend/pnpm-workspace.yaml>)
  - [`frontend/postcss.config.js`](<frontend/postcss.config.js>)
  - [`frontend/prettier.config.js`](<frontend/prettier.config.js>)
  - [`frontend/rstest.config.ts`](<frontend/rstest.config.ts>)

### 184. `backend`

- 作用：定义后端包、容器、LangGraph 和开发命令配置。
- 阅读重点：了解 Gateway 与 harness 如何被安装和启动。
- 文件：
  - [`backend/debug.py`](<backend/debug.py>)
  - [`backend/Dockerfile`](<backend/Dockerfile>)
  - [`backend/Makefile`](<backend/Makefile>)
  - [`backend/samples/other_agent_demo/deermem_manager.yaml`](<backend/samples/other_agent_demo/deermem_manager.yaml>)
  - [`backend/sitecustomize.py`](<backend/sitecustomize.py>)

### 185. `docker/provisioner`

- 作用：实现远程或 Kubernetes 沙箱的 Provisioner 服务。
- 阅读重点：关注沙箱创建、资源限制和生命周期接口。
- 文件：
  - [`docker/provisioner/app.py`](<docker/provisioner/app.py>)
  - [`docker/provisioner/Dockerfile`](<docker/provisioner/Dockerfile>)

### 186. `docker`

- 作用：定义本地、开发和生产容器编排及 Nginx 入口。
- 阅读重点：沿服务拓扑理解端口、卷和反向代理关系。
- 文件：
  - [`docker/dev-entrypoint.sh`](<docker/dev-entrypoint.sh>)
  - [`docker/docker-compose-dev.yaml`](<docker/docker-compose-dev.yaml>)
  - [`docker/docker-compose.cli-auth.yaml`](<docker/docker-compose.cli-auth.yaml>)
  - [`docker/docker-compose.dood.yaml`](<docker/docker-compose.dood.yaml>)
  - [`docker/docker-compose.yaml`](<docker/docker-compose.yaml>)

### 187. `deploy`

- 作用：提供 Helm 等生产部署模板与权限资源。
- 阅读重点：关注服务、配置和 RBAC 如何映射到集群。
- 文件：
  - [`deploy/helm/deer-flow/Chart.yaml`](<deploy/helm/deer-flow/Chart.yaml>)
  - [`deploy/helm/deer-flow/templates/configmap-config.yaml`](<deploy/helm/deer-flow/templates/configmap-config.yaml>)
  - [`deploy/helm/deer-flow/templates/configmap-extensions.yaml`](<deploy/helm/deer-flow/templates/configmap-extensions.yaml>)
  - [`deploy/helm/deer-flow/templates/configmap-nginx.yaml`](<deploy/helm/deer-flow/templates/configmap-nginx.yaml>)
  - [`deploy/helm/deer-flow/templates/frontend-deployment.yaml`](<deploy/helm/deer-flow/templates/frontend-deployment.yaml>)
  - [`deploy/helm/deer-flow/templates/frontend-service.yaml`](<deploy/helm/deer-flow/templates/frontend-service.yaml>)
  - [`deploy/helm/deer-flow/templates/gateway-deployment.yaml`](<deploy/helm/deer-flow/templates/gateway-deployment.yaml>)
  - [`deploy/helm/deer-flow/templates/gateway-service.yaml`](<deploy/helm/deer-flow/templates/gateway-service.yaml>)
  - [`deploy/helm/deer-flow/templates/ingress.yaml`](<deploy/helm/deer-flow/templates/ingress.yaml>)
  - [`deploy/helm/deer-flow/templates/nginx-deployment.yaml`](<deploy/helm/deer-flow/templates/nginx-deployment.yaml>)
  - [`deploy/helm/deer-flow/templates/nginx-service.yaml`](<deploy/helm/deer-flow/templates/nginx-service.yaml>)
  - [`deploy/helm/deer-flow/templates/postgres-secret.yaml`](<deploy/helm/deer-flow/templates/postgres-secret.yaml>)
  - [`deploy/helm/deer-flow/templates/postgres-service.yaml`](<deploy/helm/deer-flow/templates/postgres-service.yaml>)
  - [`deploy/helm/deer-flow/templates/postgres-statefulset.yaml`](<deploy/helm/deer-flow/templates/postgres-statefulset.yaml>)
  - [`deploy/helm/deer-flow/templates/provisioner-deployment.yaml`](<deploy/helm/deer-flow/templates/provisioner-deployment.yaml>)
  - [`deploy/helm/deer-flow/templates/provisioner-rbac.yaml`](<deploy/helm/deer-flow/templates/provisioner-rbac.yaml>)
  - [`deploy/helm/deer-flow/templates/provisioner-service.yaml`](<deploy/helm/deer-flow/templates/provisioner-service.yaml>)
  - [`deploy/helm/deer-flow/templates/pvc-home.yaml`](<deploy/helm/deer-flow/templates/pvc-home.yaml>)
  - [`deploy/helm/deer-flow/templates/redis-secret.yaml`](<deploy/helm/deer-flow/templates/redis-secret.yaml>)
  - [`deploy/helm/deer-flow/templates/redis-service.yaml`](<deploy/helm/deer-flow/templates/redis-service.yaml>)
  - [`deploy/helm/deer-flow/templates/redis-statefulset.yaml`](<deploy/helm/deer-flow/templates/redis-statefulset.yaml>)
  - [`deploy/helm/deer-flow/templates/secret-app.yaml`](<deploy/helm/deer-flow/templates/secret-app.yaml>)
  - [`deploy/helm/deer-flow/templates/secret-provider.yaml`](<deploy/helm/deer-flow/templates/secret-provider.yaml>)
  - [`deploy/helm/deer-flow/values.yaml`](<deploy/helm/deer-flow/values.yaml>)

### 188. `.`

- 作用：包含仓库根级构建配置、示例配置和质量工具设置。
- 阅读重点：作为本地开发和 CI 的公共配置入口。
- 文件：
  - [`.pre-commit-config.yaml`](<.pre-commit-config.yaml>)
  - [`config.example.yaml`](<config.example.yaml>)
