---
name: video-generation
description: 用户要求生成、创作或构想视频时使用。支持结构化提示词和参考图引导生成。
---

# 视频生成技能

## 概述

此技能使用结构化提示词和 Python 脚本生成高质量视频，流程包括创建 JSON（JavaScript Object Notation，JavaScript 对象表示法）提示词并执行生成，可选提供参考图。

## 核心能力

- 创建结构化提示词，用于人工智能视频生成。
- 支持用参考图引导，或作为视频的首帧／末帧。
- 自动执行 Python 脚本生成视频。

## 工作流程

### 第 1 步：理解需求

用户请求生成视频时，识别：

- 主体／内容：画面中应包含什么。
- 风格偏好：艺术风格、情绪、配色。
- 技术规格：宽高比、构图、光照。
- 参考图：引导生成的图像。
- 无需检查 `/mnt/user-data` 下的文件夹。

### 第 2 步：创建结构化提示词

在 `/mnt/user-data/workspace/` 创建结构化文件，命名格式为 `{descriptive-name}.json`。

### 第 3 步：创建参考图（有 image-generation 技能时可选）

为视频生成创建参考图。

- 如果只提供一张图，就将其作为视频引导帧。

### 第 3 步：执行生成

调用 Python 脚本：
```bash
python /mnt/skills/public/video-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/prompt-file.json \
  --reference-images /path/to/ref1.jpg \
  --output-file /mnt/user-data/outputs/generated-video.mp4 \
  --aspect-ratio 16:9
```

参数：

- `--prompt-file`: 提示词文件绝对路径（必填）
- `--reference-images`: 参考图绝对路径（可选）
- `--output-file`: 输出图像文件绝对路径（必填）
- `--aspect-ratio`: 生成图像宽高比（可选，默认 16:9）

[!NOTE]
不要阅读 Python 文件，直接传入参数调用。

## 视频生成示例

用户请求：“生成一段短片，呈现《纳尼亚传奇：狮子、女巫和魔衣橱》的开场场景。”

第 1 步：在线搜索《纳尼亚传奇：狮子、女巫和魔衣橱》的开场场景。

第 2 步：创建以下提示词文件：

```json
{
  "title": "纳尼亚传奇——火车站告别",
  "background": {
    "description": "第二次世界大战期间，拥挤的伦敦火车站正在疏散人群。蒸汽和烟雾弥漫，孩子们被送往乡村躲避伦敦大轰炸。",
    "era": "二十世纪四十年代，战时英国",
    "location": "伦敦火车站站台"
  },
  "characters": ["佩文西太太", "露西·佩文西"],
  "camera": {
    "type": "双人近景",
    "movement": "固定机位，带轻微手持晃动",
    "angle": "侧面视角，亲密构图",
    "focus": "两张面孔均合焦，背景柔和虚化"
  },
  "dialogue": [
    {
      "character": "佩文西太太",
      "text": "亲爱的，为了我你要勇敢。我会来接你……我保证。"
    },
    {
      "character": "露西·佩文西",
      "text": "我会勇敢的，妈妈。我保证。"
    }
  ],
  "audio": [
    {
      "type": "汽笛响起，示意发车",
      "volume": 1
    },
    {
      "type": "弦乐情绪渐强，然后淡出",
      "volume": 0.5
    },
    {
      "type": "火车站环境声",
      "volume": 0.5
    }
  ]
}
```

第 3 步：使用 image-generation 技能生成参考图。

加载 image-generation 技能，按其说明生成单张参考图 `narnia-farewell-scene-01.jpg`。

第 4 步：使用 generate.py 脚本生成视频。
```bash
python /mnt/skills/public/video-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/narnia-farewell-scene.json \
  --reference-images /mnt/user-data/outputs/narnia-farewell-scene-01.jpg \
  --output-file /mnt/user-data/outputs/narnia-farewell-scene-01.mp4 \
  --aspect-ratio 16:9
```
> 不要阅读 Python 文件，直接传入参数调用。

## 输出处理

生成后：

- 视频通常保存在 `/mnt/user-data/outputs/`。
- 使用 `present_files` 向用户展示生成视频（视频优先），如有生成图像也一并展示。
- 简要描述生成结果。
- 如需调整，继续迭代。

## 注意事项

- 提示词默认使用中文；用户明确指定其他语言时遵循其要求。
- 数据格式保证提示词结构清晰且可解析。
- 参考图可显著提高生成质量。
- 为取得最佳结果，迭代优化属于正常过程。

## 服务提供方（Gemini／MiniMax）

通过环境变量自动选择，命令行用法不变：

- 设置 `GEMINI_API_KEY`：使用 Gemini Veo，为原有默认行为。
- 只设置 `MINIMAX_API_KEY`：使用 MiniMax 视频（`/v1/video_generation`，异步提交、轮询、下载三步流程）。
- 使用 `VIDEO_GENERATION_PROVIDER=gemini|minimax` 强制指定。

MiniMax 覆盖项：`MINIMAX_API_HOST`（默认 `https://api.minimaxi.com`）和 `MINIMAX_VIDEO_MODEL`（默认 `MiniMax-Hailuo-2.3`）。首张参考图用作 MiniMax 的 `first_frame_image`。MiniMax 忽略 `--aspect-ratio`，改用分辨率和时长。
