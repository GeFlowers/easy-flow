---
name: code-documentation
description: 用户要求为代码、接口、库、仓库或软件项目生成、创建或改进文档时使用。支持项目说明、接口参考、行内注释、架构文档、更新日志和开发者指南。“为这段代码写文档”、“创建项目说明”、“生成接口文档”、“写开发者指南”，或为文档分析代码库时触发。
---

# 代码文档技能

## 概述

为软件项目、代码库、库和 API（Application Programming Interface，应用程序编程接口）生成专业、全面的文档。遵循 React、Django、Stripe 和 Kubernetes 等项目的行业实践，确保准确、结构清晰，对新贡献者与资深开发者都有帮助。

输出从单文件 README（Read Me，项目自述文件）到多文档开发者指南不等，始终匹配项目复杂度和用户需求。

## 核心能力

- 生成完整 README.md，包括徽章、安装、用法和接口参考。
- 根据源代码分析创建接口参考。
- 生成带图的架构与设计文档。
- 编写开发者入门与贡献指南。
- 根据提交历史或发布说明生成更新日志。
- 按语言约定生成行内文档。
- 支持 JSDoc、文档字符串、GoDoc、Javadoc 和 Rustdoc。
- 适配项目语言与生态的文档风格。

## 使用时机

以下情况**始终加载**：

- 用户要求为任何代码“写文档”、“创建文档”。
- 用户要求项目自述、接口参考或开发者指南。
- 用户提供代码库或仓库，希望生成文档。
- 用户要求改进或更新现有文档。
- 用户需要包含图示的架构文档。
- 用户要求更新日志或迁移指南。

## 文档流程

### 第 1 阶段：分析代码库

编写任何文档前，充分理解代码库。

#### 第 1.1 步：了解项目

| 信息 | 判断方式 |
| --- | --- |
| **语言** | 文件扩展名、`package.json`、`pyproject.toml`、`go.mod`、`Cargo.toml` 等 |
| **框架** | 检查 React、Django、Express、Spring 等依赖 |
| **构建系统** | 检查 `Makefile`、`CMakeLists.txt`、`webpack.config.js`、`build.gradle` 等 |
| **包管理器** | npm／yarn／pnpm、pip／uv／poetry、cargo、Go 模块等 |
| **项目结构** | 梳理目录树，理解架构 |
| **入口** | 主文件、命令行入口、导出模块 |
| **现有文档** | 自述文件、docs/、知识库或行内文档 |

#### 第 1.2 步：分析代码结构

使用沙箱工具探索：

```bash
# 获取目录结构
ls /mnt/user-data/uploads/project-dir/

# 阅读关键文件
read_file /mnt/user-data/uploads/project-dir/package.json
read_file /mnt/user-data/uploads/project-dir/pyproject.toml

# 搜索公开接口
grep -r "export " /mnt/user-data/uploads/project-dir/src/
grep -r "def " /mnt/user-data/uploads/project-dir/src/ --include="*.py"
grep -r "func " /mnt/user-data/uploads/project-dir/ --include="*.go"
```

#### 第 1.3 步：识别文档范围

| 项目规模 | 推荐文档 |
| --- | --- |
| **单文件／脚本** | 行内注释和用法抬头 |
| **小型库** | 自述文件和接口参考 |
| **中型项目** | 自述文件、接口文档、示例 |
| **大型项目** | 自述、架构、接口、贡献指南、更新日志 |

### 第 2 阶段：生成文档

#### 第 2.1 步：生成项目自述

每个项目都需要 README，遵循：

```markdown
# 项目名称

[一句话说明用途及价值]

[![徽章](link)](#) [![徽章](link)](#)

## 功能

- [关键功能一：简述]
- [关键功能二：简述]
- [关键功能三：简述]

## 快速开始

### 前置条件

- [条件一与版本要求]
- [条件二与版本要求]

### 安装

[可直接复制粘贴的安装命令代码块]

### 基本用法

[展示核心功能的最小可用示例]

## 文档

- [独立接口参考链接（如有）]
- [独立架构文档链接（如有）]
- [示例目录链接（如适用）]

## 接口参考

[小项目直接写参考，或链接生成文档]

## 配置

[环境变量、配置文件或运行选项]

## 示例

[2–3 个覆盖常见用途的实例]

## 开发

### 设置

[如何配置开发环境]

### 测试

[如何运行测试]

### 构建

[如何构建项目]

## 贡献

[贡献指南或 CONTRIBUTING.md 链接]

## 许可证

[许可证信息]
```

#### 第 2.2 步：生成接口参考

为每个公开接口编写文档。

**函数／方法：**

```markdown
### `functionName(param1, param2, options?)`

简述函数用途。

**参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `param1` | `string` | 是 | — | 参数一说明 |
| `param2` | `number` | 是 | — | 参数二说明 |
| `options` | `Object` | 否 | `{}` | 配置选项 |
| `options.timeout` | `number` | 否 | `5000` | 超时毫秒数 |

**返回：** `Promise<Result>`——返回值说明

**异常：**
- `ValidationError`：param1 为空时。
- `TimeoutError`：操作超过超时时间。

**示例：**

\`\`\`javascript
const result = await functionName("你好", 42, { timeout: 10000 });
console.log(result.data);
\`\`\`
```

**类：**

```markdown
### `ClassName`

简述类及其用途。

**构造函数：**

\`\`\`javascript
new ClassName(config)
\`\`\`

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `config.option1` | `string` | 说明 |
| `config.option2` | `boolean` | 说明 |

**方法：**

- [`method1()`](#method1)：简述
- [`method2(param)`](#method2)：简述

**属性：**

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `property1` | `string` | 说明 |
| `property2` | `number` | 只读。说明 |
```

#### 第 2.3 步：架构文档

中大型项目包含：

```markdown
# 架构概览

## 系统图

[使用 Mermaid 展示高层架构]

\`\`\`mermaid
graph TD
    A[客户端] --> B[接口网关]
    B --> C[服务甲]
    B --> D[服务乙]
    C --> E[(数据库)]
    D --> E
\`\`\`

## 组件概览

### 组件名称
- **用途：** 组件做什么
- **位置：** `src/components/name/`
- **依赖：** 依赖什么
- **公开接口：** 主要导出或接口

## 数据流

[描述关键操作中数据如何流经系统]

## 设计决策

### 决策标题
- **背景：** 什么情况促成决策
- **决策：** 决定了什么
- **理由：** 为什么选择此方法
- **权衡：** 牺牲了什么
```

#### 第 2.4 步：行内文档

按语言习惯生成。

**Python（Google 风格文档字符串）：**

```python
def process_data(input_path: str, options: dict | None = None) -> ProcessResult:
    """处理给定路径的数据。

    读取输入文件，按选项转换，并返回结构化结果。

    Args:
        input_path: 输入文件绝对路径。
            支持 CSV、JSON 和 Parquet 格式。
        options: 可选配置字典。
            - "validate" (bool): 启用输入验证，默认 True。
            - "format" (str): 输出格式（"json" 或 "csv"），默认 "json"。

    Returns:
        包含转换数据和元数据的 ProcessResult。

    Raises:
        FileNotFoundError: input_path 不存在。
        ValidationError: 启用验证且数据格式错误。

    Example:
        >>> result = process_data("/data/input.csv", {"validate": True})
        >>> print(result.row_count)
        1500
    """
```

**TypeScript（JSDoc／TSDoc）：**

```typescript
/**
 * 从接口获取用户数据并转换为展示格式。
 *
 * @param userId - 用户唯一标识
 * @param options - 获取操作配置
 * @param options.includeProfile - 是否包含完整资料，默认 false
 * @param options.cache - 缓存秒数，0 表示禁用
 * @returns 转换后可供渲染的用户数据
 * @throws {NotFoundError} 用户标识不存在
 * @throws {NetworkError} 接口不可达
 *
 * @example
 * ```ts
 * const user = await fetchUser("usr_123", { includeProfile: true });
 * console.log(user.displayName);
 * ```
 */
```

**Go（GoDoc）：**

```go
// ProcessData 读取给定路径的输入文件，执行指定转换，返回处理结果。
//
// 输入必须是 CSV 或 JSON 文件的绝对路径。
// options 为 nil 时使用默认选项。
//
// 文件不存在或无法解析时，ProcessData 返回错误。
func ProcessData(inputPath string, options *ProcessOptions) (*Result, error) {
```

### 第 3 阶段：质量保障

#### 第 3.1 步：完整性检查

确认覆盖：

- [ ] **是什么：** 新手可理解的项目说明。
- [ ] **为何存在：** 解决的问题和价值。
- [ ] **如何安装：** 可直接复制的安装命令。
- [ ] **如何使用：** 至少一个最小可用示例。
- [ ] **公开接口：** 所有公开函数、类和类型有文档。
- [ ] **配置：** 全部环境变量、配置文件、选项。
- [ ] **错误处理：** 常见错误和解决方式。
- [ ] **贡献：** 开发环境设置和提交修改方式。

#### 第 3.2 步：质量标准

| 标准 | 检查 |
| --- | --- |
| **准确** | 所有代码示例均可用于描述的接口 |
| **完整** | 没有遗漏公开接口 |
| **一致** | 全文格式和结构统一 |
| **及时** | 对应当前代码，而非旧版本 |
| **易懂** | 术语有解释，缩写首次出现定义 |
| **示例** | 每个复杂概念至少一个实用示例 |

#### 第 3.3 步：交叉引用验证

确保：

- 提到的文件路径确实存在。
- 引用的函数和类确实存在。
- 示例使用正确函数签名。
- 版本号符合项目实际版本。
- 内外链接均有效。

## 文档风格指南

### 写作原则

1. **先说明原因：** 解释如何工作前，说明为何存在。
2. **渐进展示：** 从简单开始，逐步增加复杂度。
3. **用示例展示：** 优先代码示例，少写冗长解释。
4. **主动语态：** 写“函数返回某值”，不要写“某值被函数返回”。
5. **现在时：** 写“服务器在 8080 端口启动”，不要写“将会启动”。
6. **面向读者：** 写“你可以配置”，不要写“用户可以配置”。

### 格式规则

- 使用井号式标题（`#`、`##`、`###`）。
- 使用带语言标记的围栏代码块，例如 `python`、`bash`。
- 参数、选项、配置等结构化信息使用表格。
- 重要说明、警告和建议使用提示块。
- 源文件中自然语言行约 80–100 字符，保证易读。
- 函数名、路径、变量和命令行命令使用 `代码格式`。

### 各语言约定

| 语言 | 文档格式 | 风格指南 |
| --- | --- | --- |
| Python | Google 风格文档字符串 | PEP 257（Python Enhancement Proposal 257，Python 增强提案第 257 号） |
| TypeScript／JavaScript | TSDoc／JSDoc | TypeDoc 约定 |
| Go | GoDoc 注释 | Effective Go |
| Rust | Rustdoc（`///`） | Rust 接口指南 |
| Java | Javadoc | Oracle Javadoc 指南 |
| C／C++ | Doxygen | Doxygen 手册 |

## 输出处理

生成后：

- 文档保存到 `/mnt/user-data/outputs/`。
- 多文件文档保留项目目录结构。
- 使用 `present_files` 展示生成文件。
- 可继续调整具体章节或详细程度。
- 建议可能有价值的补充文档。

## 注意事项

- 始终先分析真实代码，再写文档，不猜测接口签名或行为。
- 有既有文档时保留结构，除非用户明确要求重写。
- 大代码库优先记录公开接口和关键抽象。
- 文档语言遵循项目既有文档；没有既有文档时默认中文。
- 更新日志采用 [Keep a Changelog](https://keepachangelog.com/) 格式。
- 记录第三方集成或依赖时，可结合 `deep-research`。
