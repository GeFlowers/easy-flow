# openai.yaml 字段：完整示例与说明

`agents/openai.yaml` 是供运行框架读取的产品专用扩展配置，不是给代理的指令。其他产品专用配置也可放在 `agents/` 中。

## 完整示例

```yaml
interface:
  display_name: "可选的用户可见名称"
  short_description: "可选的用户可见简短说明"
  icon_small: "./assets/small-400px.png"
  icon_large: "./assets/large-logo.svg"
  brand_color: "#3B82F6"
  default_prompt: "可选的技能调用提示，例如：使用 $skill-name 帮我完成任务。"

dependencies:
  tools:
    - type: "mcp"
      value: "github"
      description: "GitHub 工具协议服务"
      transport: "streamable_http"
      url: "https://api.githubcopilot.com/mcp/"

policy:
  allow_implicit_invocation: true
```

## 字段说明与约束

基本要求：

- 所有字符串值加引号。
- 字段名不加引号。
- `interface.default_prompt` 应是简短实用的起始提示，通常一句话，并明确提及 `$skill-name`，例如“使用 $skill-name-here 起草简洁的每周进展报告”。

- `interface.display_name`：技能列表和标签中展示给用户的标题。
- `interface.short_description`：便于快速浏览的简介，长度 25–64 个字符。
- `interface.icon_small`：相对于技能目录的小图标路径，默认放入 `./assets/`。
- `interface.icon_large`：相对于技能目录的大图标路径，默认放入 `./assets/`。
- `interface.brand_color`：用于徽标等界面装饰的十六进制颜色。
- `interface.default_prompt`：调用技能时插入的默认提示。
- `dependencies.tools[].type`：依赖类别，目前只支持 `mcp`。
- `dependencies.tools[].value`：工具或依赖的标识。
- `dependencies.tools[].description`：面向人的依赖说明。
- `dependencies.tools[].transport`：`type` 为 `mcp` 时的连接方式。
- `dependencies.tools[].url`：`type` 为 `mcp` 时的服务地址。
- `policy.allow_implicit_invocation`：默认 true。设为 false 时不自动注入模型上下文，仍可通过 `$skill` 显式调用。
