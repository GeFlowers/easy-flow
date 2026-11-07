# 技术讲解播客模板

将技术文档、API（Application Programming Interface，应用程序编程接口）指南或开发者教程转换为播客时使用。

## 输入准备

用户希望转换技术内容时，帮助组织输入：

1. **简化代码示例：** 用通俗描述替代代码片段。
   - 描述代码做什么，不直接展示代码。
   - 聚焦概念而非语法。
2. **移除复杂符号：**
   - 用文字解释数学公式。
   - 按功能描述接口端点，而非列出路径。
   - 将配置示例概括为设置说明。
3. **补充背景：**
   - 解释技术为何重要。
   - 包含真实用例。
   - 为复杂概念加入类比。

## 转换示例

### 原始技术内容

```markdown
# 使用接口

POST /api/v1/users
{
  "name": "张三",
  "email": "zhangsan@example.com"
}

响应：201 Created
```

### 适合播客的内容

```markdown
# 通过接口创建用户

用户创建功能允许应用在系统中注册新用户。
需要新增用户时，将其姓名和邮箱发送给服务器。
如果一切顺利，服务器会确认用户创建成功。
此功能常见于注册流程、管理仪表盘或从其他系统导入用户。
```

## 生成命令

```bash
python /mnt/skills/public/podcast-generation/scripts/generate.py \
  --script-file /mnt/user-data/workspace/tech-explainer-script.json \
  --output-file /mnt/user-data/outputs/tech-explainer-podcast.mp3 \
  --transcript-file /mnt/user-data/outputs/tech-explainer-transcript.md
```

## 技术播客建议

- 每期聚焦一个主要概念。
- 用类比解释抽象概念。
- 加入“为什么重要”的实际背景。
- 使用术语时提供解释。
- 让初学者也能理解对话。
