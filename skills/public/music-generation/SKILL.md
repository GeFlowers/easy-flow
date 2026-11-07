---
name: music-generation
description: 用户要求生成、创作、作曲或制作音乐、歌曲时使用，包括背景音乐、主题曲、广告短曲或纯音乐。通过 MiniMax 音乐接口，根据风格／情绪提示和可选歌词生成歌曲。
---

# 音乐生成技能

## 概述

此技能通过 MiniMax 音乐生成接口（`/v1/music_generation`），根据结构化 JSON（JavaScript Object Notation，JavaScript 对象表示法）规范生成含人声歌曲或纯音乐。在 `prompt` 中描述风格、情绪和场景，可选提供 `lyrics`；脚本返回 MP3（MPEG Audio Layer III，动态图像专家组音频第三层）音频。

## 工作流程

### 第 1 步：理解需求

确定所需风格、情绪、场景、语言，以及是否需要人声或纯音乐。决定提供歌词，还是让模型创作歌词。

### 第 2 步：创建规范文件

在 `/mnt/user-data/workspace/` 中创建名为 `{descriptive-name}.json` 的文件：

```json
{
  "title": "雨夜咖啡馆",
  "prompt": "独立民谣，忧郁，内省，独自行走，咖啡馆",
  "lyrics": "[verse]\n路灯微亮夜风轻叹\n[chorus]\n推开木门暖意扑面"
}
```

字段：

- `title`（可选）：便于人阅读的名称。
- `prompt`（必填）：风格、情绪和场景，决定音乐的整体特征。
- `lyrics`（可选）：歌词。行间用 `\n` 分隔，并使用 `[Intro]`、`[Verse]`、`[Pre Chorus]`、`[Chorus]`、`[Bridge]`、`[Outro]` 等结构标签。
- `is_instrumental`（可选，布尔值）：纯音乐设置为 `true`，无需歌词。

行为：

- 提供 `lyrics`：演唱这些歌词。
- 设置 `is_instrumental: true`：生成无人声的纯音乐。
- 两者均未提供：模型根据 `prompt` 自动写词（`lyrics_optimizer`）。

### 第 3 步：执行生成

```bash
python /mnt/skills/public/music-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/rainy-night-cafe.json \
  --output-file /mnt/user-data/outputs/rainy-night-cafe.mp3
```

参数：

- `--prompt-file`：规范文件绝对路径，必填。
- `--output-file`：输出音频绝对路径，必填。

[!NOTE]
不要阅读 Python 文件，直接传入参数调用。

## 环境

- `MINIMAX_API_KEY`（必填）：MiniMax 接口密钥。
- `MINIMAX_API_HOST`（可选）：默认 `https://api.minimaxi.com`。
- `MINIMAX_MUSIC_MODEL`（可选）：默认 `music-2.6-free`，适用于所有接口密钥用户；付费或 Token-Plan 用户可以设置为 `music-2.6` 以提高限额。

## 输出处理

- 音乐保存为音频文件，通常位于 `/mnt/user-data/outputs/`。
- 使用 present_files 工具向用户展示生成文件。
- 如需调整，可继续迭代风格或歌词。

## 注意事项

- `prompt` 聚焦风格、情绪和场景，实际演唱文字放入 `lyrics`。
- 非英语歌曲应使用目标语言编写 `lyrics`。
