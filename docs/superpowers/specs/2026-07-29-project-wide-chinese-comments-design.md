# 全项目中文注释补全设计

## 目标

为仓库内 Python、TypeScript、TSX 与 JavaScript 代码补充高价值中文注释。Python 以 docstring 为主要形式，TypeScript、TSX 与 JavaScript 以 JSDoc 为主要形式；仅在并发控制、协议转换、状态维护、边界条件及其他非直观逻辑处添加行内注释。

## 范围

- 覆盖 `backend/`、`frontend/`、`scripts/` 与测试目录中的代码文件。
- Python 的模块、类、方法和函数应具有说明职责与关键约束的中文 docstring。
- TypeScript、TSX 与 JavaScript 的公开组件、函数、Hook、类和重要内部函数应具有中文 JSDoc。
- 现有准确英文注释翻译为符合代码上下文的中文说明。
- 标识符、API 名称、协议字段、事件名、命令、路径、配置键、代码示例和必须精确匹配的文本保持原文。

## 注释质量规则

1. 注释解释“为什么这样设计”“必须保持什么约束”以及“违反约束会产生什么后果”，不复述语句表面行为。
2. 简单 getter、薄包装函数和声明式组件只说明职责，不逐个解释显而易见的参数或返回值。
3. 对流式协议、异步边界、锁粒度、状态合并、缓存失效、权限边界和兼容层优先补充设计意图。
4. 不通过机械模板批量生成同质注释；每个文件按其上下文人工审阅。
5. 注释变更不得改变运行逻辑、公共接口、格式化结果之外的代码语义。

## 分批策略

按高内聚目录逐批处理，每批约 15 至 30 个相关文件：

1. `backend/app/channels/`
2. `backend/app/gateway/`
3. `backend/packages/harness/deerflow/` 的运行时、Agent 与中间件
4. `backend/packages/harness/deerflow/` 的配置、工具、沙箱及其余模块
5. 后端与根目录测试、脚本
6. `frontend/src/core/`
7. `frontend/src/components/` 与页面
8. 前端测试、配置和其余 JavaScript/TypeScript 文件

每批先建立文件清单与缺失注释清单，再编辑并运行该目录适用的格式检查、类型检查或测试。不同批次不并行修改同一文件。

## 验证

- Python 批次至少运行 `ruff format --check` 与相关 pytest。
- 前端批次至少运行 ESLint、TypeScript 类型检查与相关测试。
- 使用差异检查确认每批只包含注释或注释引起的格式调整。
- 通过抽样审阅排除复述代码、错误翻译和与实现不一致的注释。

## 完成标准

- 范围内函数、方法和主要代码单元具备符合语言习惯的中文 docstring/JSDoc。
- 复杂逻辑拥有解释设计原因和约束的独立中文注释。
- 不存在为满足数量而生成的低信息量注释。
- 所有受影响模块的检查与测试通过，且代码行为未改变。
