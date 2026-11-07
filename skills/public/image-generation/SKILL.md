---
name: image-generation
description: 用户要求生成、创作、想象或可视化图像时使用，包括角色、场景、产品及任何视觉内容。支持结构化提示词和参考图引导生成。
---

# 图像生成技能

## 概述

此技能使用结构化提示词和 Python 脚本生成高质量图像，流程包括创建 JSON（JavaScript Object Notation，JavaScript 对象表示法）提示词并执行生成，可选提供参考图。

## 核心能力

- 创建结构化提示词，用于人工智能图像生成。
- 支持多张参考图，引导风格和构图。
- 自动执行 Python 脚本生成图像。
- 处理角色设计、场景、产品等多种生成场景。

## 工作流程

### 第 1 步：理解需求

用户请求生成图像时，识别：

- 主体／内容：图中应该有什么。
- 风格偏好：艺术风格、情绪、配色。
- 技术规格：宽高比、构图、光照。
- 参考图：用于引导生成的图像。
- 无需检查 `/mnt/user-data` 下的文件夹。

### 第 2 步：创建结构化提示词

在 `/mnt/user-data/workspace/` 创建结构化文件，命名格式为 `{descriptive-name}.json`。

### 第 3 步：执行生成

调用 Python 脚本：
```bash
python /mnt/skills/public/image-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/prompt-file.json \
  --reference-images /path/to/ref1.jpg /path/to/ref2.png \
  --output-file /mnt/user-data/outputs/generated-image.jpg
  --aspect-ratio 16:9
```

参数：

- `--prompt-file`: 提示词文件绝对路径（必填）
- `--reference-images`: 参考图绝对路径（可选，以空格分隔）
- `--output-file`: 输出图像绝对路径（必填）
- `--aspect-ratio`: 生成图像的宽高比（可选，默认 16:9）

[!NOTE]
不要阅读 Python 文件，直接传入参数调用。

## 角色生成示例

用户请求：“创作一位 20 世纪 90 年代东京街头风格的女性角色”。

创建提示词文件： `/mnt/user-data/workspace/asian-woman.json`
```json
{
  "characters": [{
    "gender": "女性",
    "age": "二十五岁左右",
    "ethnicity": "日本",
    "body_type": "纤细、优雅",
    "facial_features": "五官精致，眼神生动，淡妆突出嘴唇，深色长发被雨水局部打湿",
    "clothing": "时尚风衣、设计师手袋、高跟鞋，东京都市街头时尚",
    "accessories": "简约首饰、醒目耳环、皮革手袋",
    "era": "二十世纪九十年代"
  }],
  "negative_prompt": "模糊面部、变形、低质量、过锐数字质感、颜色过饱和、人造光、摄影棚、摆拍、自拍角度",
  "style": "徕卡 M11 街头摄影美感、胶片般渲染、略暖的自然配色、散景背景虚化、模拟摄影质感",
  "composition": "中景、三分法、主体略偏离中心、可见东京街道环境、浅景深突出主体",
  "lighting": "招牌与店面霓虹、湿路反射、柔和城市环境光、自然街头光照、背景霓虹轮廓光",
  "color_palette": "柔和自然色调、温暖肤色、冷蓝与品红霓虹点缀、比数字摄影更低饱和度、胶片颗粒"
}
```

执行生成：
```bash
python /mnt/skills/public/image-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/cyberpunk-hacker.json \
  --output-file /mnt/user-data/outputs/cyberpunk-hacker-01.jpg \
  --aspect-ratio 2:3
```

使用参考图：
```json
{
  "characters": [{
    "gender": "基于[图 1]",
    "age": "基于[图 1]",
    "ethnicity": "将[图 1]中的人物适配到星球大战宇宙",
    "body_type": "基于[图 1]",
    "facial_features": "匹配[图 1]，带有太空旅行造成的轻微风霜感",
    "clothing": "星球大战风格服装：旧皮夹克、功能背心、带战术袋的工装裤、磨损靴子和枪套腰带",
    "accessories": "腰间爆能手枪、腕部通讯器、推至额头的护目镜、装补给品的挎包、基于[图 2]的个人载具",
    "era": "星球大战宇宙，帝国之后的时代"
  }],
  "prompt": "以[图 1]为灵感的角色站在以[图 2]为灵感的载具旁，背景是繁忙的外星街道，整体采用星球大战宇宙美学。角色穿旧皮夹克、功能背心、带战术袋的工装裤、磨损靴子和爆能枪套腰带。载具有风化金属面板、反重力发动机和沙漠尘土，停在街边。异域集市包含多层建筑、风化金属结构、悬挂摊位和彩色遮阳篷，外星种族在背景经过。双日投下温暖金光，空气漂浮尘埃，远方可见水汽凝结器。粗粝而有人居住感的星球大战美学，实拍特效外观、胶片颗粒和电影构图。",
  "negative_prompt": "洁净未来感、无菌环境、过度计算机生成外观、奇幻中世纪元素、地球建筑、现代城市",
  "style": "星球大战原三部曲美学、有人居住感的宇宙、实拍特效灵感、电影胶片观感、低饱和暖色",
  "composition": "中远景、角色在前景、外星街道延伸至背景、环境叙事、三分法",
  "lighting": "双日黄金时刻暖光、角色轮廓光、空气薄雾、集市摊位真实光源",
  "color_palette": "温暖沙色、赭石与赭黄、灰蓝、风化金属、柔和大地色配外星集市鲜艳点缀",
  "technical": {
    "aspect_ratio": "9:16",
    "quality": "high",
    "detail_level": "高度细节、胶片般质感"
  }
}
```
```bash
python /mnt/skills/public/image-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/star-wars-scene.json \
  --reference-images /mnt/user-data/uploads/character-ref.jpg /mnt/user-data/uploads/vehicle-ref.jpg \
  --output-file /mnt/user-data/outputs/star-wars-scene-01.jpg \
  --aspect-ratio 16:9
```

## 常见场景

不同场景使用不同的数据结构。

**角色设计：**
- 外貌属性：性别、年龄、族裔、体型。
- 面部特征与表情。
- 服装与配饰。
- 历史年代或背景。
- 姿态与情境。

**场景生成：**
- 环境描述。
- 时段与天气。
- 情绪与氛围。
- 焦点与构图。

**产品可视化：**
- 产品细节和材料。
- 布光设置。
- 背景与情境。
- 展示角度。

## 专用模板

仅当用户请求匹配时阅读以下模板文件。

- [哆啦A梦漫画](templates/doraemon.md)

## 输出处理

生成后：

- 图像通常保存在 `/mnt/user-data/outputs/`。
- 使用 present_files 工具向用户展示生成的图像。
- 简要描述生成结果。
- 如需调整，继续迭代。

## 建议：使用参考图提升生成质量

对于视觉准确性至关重要的场景，生成前**先使用 `image_search` 工具**查找参考图。

**建议使用 image_search 的场景：**
- **角色／肖像生成：** 搜索相似姿态、表情或风格，指导面部特征和身体比例。
- **具体物品或产品：** 查找实物参考图，确保准确呈现。
- **建筑或环境场景：** 搜索地点参考，捕捉真实细节。
- **时尚和服装：** 查找风格参考，确保衣服细节与造型准确。

**示例流程：**
1. 调用 `image_search` 查找合适参考图：
   ```
   image_search(query="二十世纪九十年代日本女性街头摄影", size="Large")
   ```
2. 将返回地址对应的图像下载为本地文件。
3. 将下载图像作为生成脚本的 `--reference-images` 参数。

此方法为模型提供具体视觉指导，减少仅依赖文字描述造成的偏差，显著提升生成质量。

## 服务提供方（Gemini／MiniMax）

此技能通过环境变量自动选择服务提供方，命令行用法不变：

- 已设置 `GEMINI_API_KEY`：使用 Gemini，为原有默认行为。
- 只设置 `MINIMAX_API_KEY`：使用 MiniMax（`/v1/image_generation`，模型 `image-01`）。
- 可用 `IMAGE_GENERATION_PROVIDER=gemini|minimax` 显式指定。

MiniMax 可选覆盖项：`MINIMAX_API_HOST`（默认 `https://api.minimaxi.com`）和 `MINIMAX_IMAGE_MODEL`（默认 `image-01`）。参考图作为 MiniMax 的 `subject_reference` 角色图发送。两种服务的命令行及 `--prompt-file`／`--reference-images`／`--output-file`／`--aspect-ratio` 参数完全相同。

**MiniMax 提示词处理（服务内部行为）。** 编写方式不依赖服务提供方，始终使用相同结构。MiniMax `image-01` 只接收一段文本，因此 MiniMax 路径仅发送 `prompt` 字段；`style`、`composition`、`negative_prompt` 等其他字段仅用于 Gemini 路径。MiniMax 路径启用 `prompt_optimizer`，由服务端扩展提示词。MiniMax 将提示词限制为 1500 字符；`prompt` 超过长度时脚本直接报错，不调用接口。Gemini 路径会接收完整结构。

## 注意事项

- 提示词默认使用中文；用户明确指定其他语言时遵循其要求。
- 数据格式保证提示词结构清晰且可解析。
- 参考图可显著提高生成质量。
- 为取得最佳结果，迭代优化属于正常过程。
- 生成角色时，同时提供详细角色对象和汇总后的 prompt 字段。
