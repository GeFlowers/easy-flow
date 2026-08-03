# DeerFlow Code Reading Order Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在根目录重建覆盖全部代码文件、从上层功能到底层实现排序且逐组说明作用的 `CODE_READING_ORDER.md`。

**Architecture:** 从 Git 跟踪文件生成纳入范围清单，再按认知层级和职责路径映射到编号组。每组包含中文作用说明、阅读重点和所有具体文件链接，最后以集合比较验证完整性与唯一性。

**Tech Stack:** Markdown、Git、PowerShell、ripgrep。

## Global Constraints

- 所有工作在当前 Git 分支完成，不使用新分支或 worktree。
- 只有用户明确要求时才提交和推送；本任务已明确要求提交 GitHub。
- 覆盖全部代码、测试、部署脚本与构建配置。
- 每个编号必须说明文件夹或单文件的作用。
- 文件夹分组内部仍须列出每个具体代码文件的超链接。

---

### Task 1: 建立全量文件清单与分组映射

**Files:**
- Read: `AGENTS.md`
- Read: `backend/AGENTS.md`
- Read: `frontend/AGENTS.md`
- Create: `CODE_READING_ORDER.md`

**Interfaces:**
- Consumes: Git 跟踪文件清单和设计说明中的覆盖规则。
- Produces: 每个代码文件到唯一职责组的映射。

- [x] **Step 1: 获取纳入范围文件总数**

运行 PowerShell：读取 `git ls-files`，按设计说明中的扩展名和特殊文件名筛选。

预期：得到去重后的代码文件集合，并记录总数。

- [x] **Step 2: 按上层到底层定义编号组**

顺序固定为产品入口、前端功能、Gateway/API、Agent 编排、运行时与工具、配置与持久化、测试、技能脚本、部署与工程自动化。

预期：每个文件恰好分配到一个组。

### Task 2: 生成带说明和具体链接的阅读文档

**Files:**
- Create: `CODE_READING_ORDER.md`

**Interfaces:**
- Consumes: Task 1 的唯一分组映射。
- Produces: 根目录 Markdown 阅读索引。

- [x] **Step 1: 写入文档说明和阅读原则**

写明覆盖范围、排序依据以及文件夹编号不替代具体文件链接的约束。

- [x] **Step 2: 写入全部编号组**

每组统一包含“作用”“阅读重点”“文件”三部分；关键入口单文件独立成组，其余按职责文件夹成组。

- [x] **Step 3: 保证链接兼容特殊路径**

所有相对路径放入 Markdown 尖括号目标中，使包含括号和方括号的 Next.js 路径可正常解析。

### Task 3: 验证、提交和推送

**Files:**
- Verify: `CODE_READING_ORDER.md`
- Verify: `docs/superpowers/specs/2026-08-03-code-reading-order-design.md`
- Verify: `docs/superpowers/plans/2026-08-03-code-reading-order.md`

**Interfaces:**
- Consumes: 最终文档和 Git 跟踪文件集合。
- Produces: 完整性证据与 GitHub 提交。

- [x] **Step 1: 比较文件集合与链接集合**

预期：缺失链接为 0、额外链接为 0、重复链接为 0。

- [x] **Step 2: 校验编号说明**

预期：每个编号标题后都存在非空“作用”段落。

- [x] **Step 3: 运行 Markdown 和 Git 检查**

运行：`git diff --check`

预期：退出码为 0。

- [x] **Step 4: 提交并推送**

运行：

```bash
git add CODE_READING_ORDER.md docs/superpowers/plans/2026-08-03-code-reading-order.md
git commit -m "docs: restructure complete code reading order"
git push geflowers main
```

预期：当前分支提交成功并与 `geflowers/main` 同步。
