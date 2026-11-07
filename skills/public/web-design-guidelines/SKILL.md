---
name: web-design-guidelines
description: 审查用户界面代码是否符合网页界面指南。用户要求“审查界面”、“检查无障碍”、“审核设计”、“审查用户体验”或“检查网站是否符合最佳实践”时使用。
metadata:
  author: vercel
  version: "1.0.0"
  argument-hint: <file-or-pattern>
---

# 网页界面指南

检查文件是否符合网页界面指南。

## 工作方式

1. 从下方来源地址获取最新版指南。
2. 阅读指定文件，或请用户提供文件／匹配模式。
3. 对照获取的指南检查全部规则。
4. 以简短的 `file:line` 格式输出发现。

## 指南来源

每次审查前获取最新指南：

```
https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md
```

使用 WebFetch 获取最新规则。返回内容包含所有规则和输出格式说明。

## 用法

用户提供文件或匹配模式参数时：

1. 从上述来源地址获取指南。
2. 阅读指定文件。
3. 应用获取的指南中的全部规则。
4. 按指南指定的格式输出发现。

如果没有指定文件，询问用户要审查哪些文件。
