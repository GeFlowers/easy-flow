# 报告展示

规范机器契约为 `review-report.v1`。Markdown 是它的本地化视图，不是另一个事实来源。

## 完整审查章节

1. 执行摘要。
2. 就绪程度。
3. 保障程度。
4. 范围与完整性。
5. 发现。
6. 维度审查。
7. 触发分析。
8. 资源与脚本审查。
9. 证据。
10. 建议改写。
11. 建议行动。

重点审查可省略无关分析，但必须保留范围、就绪程度、保障程度、证据和建议行动。

## 机器枚举

不要翻译结构化输出中的枚举值：

- `blocked`
- `revise`
- `publish_candidate`
- `static_only`
- `trigger_checked`
- `behavior_verified`
- `regression_verified`
- `pass`
- `concern`
- `blocker`
- `not_assessed`

可在枚举旁显示本地化标签：

- `blocked`：不可发布。
- `revise`：需修订。
- `publish_candidate`：可作为发布候选。
- `static_only`：仅静态审查。

## 问题格式

每个问题应包含：

- 严重性：`blocker`、`major` 或 `minor`。
- 置信程度：`high`、`medium` 或 `low`。
- 位置：可获取时提供路径和行号。
- 观察到的证据。
- 用户影响。
- 修复方式。
- 如果修复很小，提供可直接粘贴的替换内容。

避免大段引用，绝不引用疑似秘密。
