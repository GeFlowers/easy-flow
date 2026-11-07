---
name: chart-visualization
description: 用户希望可视化数据时使用此技能。它会从 26 种图表中智能选择最合适的类型，根据详细规范提取参数，并使用 JavaScript 脚本生成图表图像。
compatibility:
  nodejs: ">=18.0.0"
---

# 图表可视化技能

此技能提供把数据转换为图表的完整流程，包括图表选择、参数提取和图像生成。

## 工作流程

可视化数据时按以下步骤操作：

### 1. 智能选择图表

分析用户数据的特征，确定最合适的图表类型。参考以下规则，并查阅 `references/` 中的详细规范：

- **时间序列：** 使用 `generate_line_chart` 展示趋势，或 `generate_area_chart` 展示累计趋势；两种不同量纲使用 `generate_dual_axes_chart`。
- **比较：** 使用 `generate_bar_chart` 比较类别，或使用 `generate_column_chart`；频数分布使用 `generate_histogram_chart`。
- **部分与整体：** 使用 `generate_pie_chart`，层级关系使用 `generate_treemap_chart`。
- **关系与流动：** 相关性使用 `generate_scatter_chart`，流动使用 `generate_sankey_chart`，重叠使用 `generate_venn_chart`。
- **地图：** 区域使用 `generate_district_map`，点位使用 `generate_pin_map`，路线使用 `generate_path_map`。
- **层级与树：** 使用 `generate_organization_chart` 或 `generate_mind_map`。
- **专门用途：**
    - `generate_radar_chart`：多维比较。
    - `generate_funnel_chart`：流程阶段。
    - `generate_liquid_chart`：百分比／进度。
    - `generate_word_cloud_chart`：词频。
    - `generate_boxplot_chart` 或 `generate_violin_chart`：统计分布。
    - `generate_network_graph`：复杂的节点与边关系。
    - `generate_fishbone_diagram`：因果分析。
    - `generate_flow_diagram`：流程。
    - `generate_spreadsheet`：表格或透视表，用于结构化展示和交叉汇总。

### 2. 提取参数

选定类型后，读取 `references/` 中的对应文件（例如 `references/generate_line_chart.md`），识别必填和可选字段。
从用户输入中提取数据，并映射到要求的 `args` 格式。

### 3. 生成图表

使用 JSON（JavaScript Object Notation，JavaScript 对象表示法）载荷调用 `scripts/generate.js`。

**载荷格式：**
```json
{
  "tool": "generate_chart_type_name",
  "args": {
    "data": [...],
    "title": "...",
    "theme": "...",
    "style": { ... }
  }
}
```

**执行命令：**
```bash
node ./scripts/generate.js '<payload_json>'
```

### 4. 返回结果

脚本会输出生成图像的地址。向用户返回：

- 图像地址。
- 生成时使用的完整 `args` 规范。

## 参考资料

各类图表的详细规范位于 `references/`。查阅这些文件，确保传给脚本的 `args` 符合预期结构。

## License

This `SKILL.md` is provided by [antvis/chart-visualization-skills](https://github.com/antvis/chart-visualization-skills).
Licensed under the [MIT License](https://github.com/antvis/chart-visualization-skills/blob/master/LICENSE).
