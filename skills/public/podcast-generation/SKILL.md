---
name: podcast-generation
description: 用户要求从文本生成、创作或制作播客时使用。把书面内容转换为两位主持人的自然对话播客音频。
---

# 播客生成技能

## 概述

根据文本生成高质量播客音频。流程包括创建结构化 JSON（JavaScript Object Notation，JavaScript 对象表示法）对话脚本，并通过语音合成生成音频。

## 核心能力

- 将文章、报告、文档等文本转换为播客脚本。
- 生成男、女两位主持人的自然对话。
- 使用 TTS（Text-to-Speech，文本转语音）合成语音。
- 混合音频片段，生成最终 MP3（MPEG Audio Layer III，动态图像专家组音频第三层）文件。
- 支持英语和中文。

## 工作流程

### 第 1 步：理解需求

用户要求生成播客时，识别：

- 来源内容：需要转换的文本、文章或报告。
- 语言：根据内容选择英语或中文。
- 输出位置：播客保存路径。
- 无需检查 `/mnt/user-data` 下的文件夹。

### 第 2 步：创建结构化脚本

在 `/mnt/user-data/workspace/` 创建 `{descriptive-name}-script.json` 文件。

结构：

```json
{
  "locale": "zh",
  "lines": [
    {"speaker": "male", "paragraph": "对话文本"},
    {"speaker": "female", "paragraph": "对话文本"}
  ]
}
```

### 第 3 步：执行生成

调用 Python 脚本：

```bash
python /mnt/skills/public/podcast-generation/scripts/generate.py \
  --script-file /mnt/user-data/workspace/script-file.json \
  --output-file /mnt/user-data/outputs/generated-podcast.mp3 \
  --transcript-file /mnt/user-data/outputs/generated-podcast-transcript.md
```

参数：

- `--script-file`：脚本文件绝对路径，必填。
- `--output-file`：输出音频绝对路径，必填。
- `--transcript-file`：输出 Markdown 逐字稿绝对路径，可选但推荐。

> [!IMPORTANT]
> - 一次完整调用脚本，不要将流程拆成独立步骤。
> - 脚本内部处理所有语音合成接口调用与音频生成。
> - 不要阅读 Python 文件，直接传入参数调用。
> - 始终包含 `--transcript-file`，为用户生成可读逐字稿。
> - 提供方和并发数由环境变量自动决定，无需选择或调节。

## 脚本格式

必须遵循：

```json
{
  "title": "人工智能的历史",
  "locale": "zh",
  "lines": [
    {"speaker": "male", "paragraph": "Hello Deer！欢迎回来，收听新一期节目。"},
    {"speaker": "female", "paragraph": "大家好！今天有个很有意思的话题。"},
    {"speaker": "male", "paragraph": "没错！我们要聊的是……"}
  ]
}
```

字段：

- `title`：节目标题，可选，作为逐字稿标题。
- `locale`：语言代码，英语为 `en`，中文为 `zh`。
- `lines`：对话数组。
  - `speaker`：`male` 或 `female`。
  - `paragraph`：该主持人的对话文本。

## 脚本写作指南

创建脚本时遵循：

### 格式要求

- 只有男、女两位主持人，自然交替发言。
- 目标时长约 10 分钟，约 40–60 条发言。
- 由男主持人以包含“Hello Deer”的问候开场。

### 语气与风格

- 自然口语，像两个朋友聊天。
- 使用轻松表达与自然过渡。
- 避免过度正式或学术化语言。
- 加入反应、追问和自然插话。

### 内容指南

- 主持人频繁来回互动。
- 句子简短，便于听懂。
- 仅使用纯文本，不在输出中加入 Markdown 格式。
- 将技术概念转化为易懂语言。
- 不含数学公式、代码或复杂符号。
- 对只听音频的听众也有吸引力、容易理解。
- 排除日期、作者姓名或文档结构等元信息。

## 播客生成示例

用户请求：“生成一期关于人工智能历史的播客。”

第 1 步：创建 `/mnt/user-data/workspace/ai-history-script.json`：

```json
{
  "title": "人工智能的历史",
  "locale": "zh",
  "lines": [
    {"speaker": "male", "paragraph": "Hello Deer！欢迎回来。今天聊一个正在塑造未来的话题：人工智能的历史。"},
    {"speaker": "female", "paragraph": "我很喜欢这个话题！人工智能看起来很现代，但它的根源其实可以追溯到七十多年前。"},
    {"speaker": "male", "paragraph": "没错，一切始于二十世纪五十年代。约翰·麦卡锡在一九五六年著名的达特茅斯会议上提出了人工智能这个术语。"},
    {"speaker": "female", "paragraph": "等等，那时人们就已经开始思考会思考的机器了？真不可思议！"},
    {"speaker": "male", "paragraph": "是啊，早期先驱非常乐观，认为一代人之内就能实现人类水平的人工智能。"},
    {"speaker": "female", "paragraph": "但后来的发展并没有完全按照他们的预期，对吧？"},
    {"speaker": "male", "paragraph": "确实如此。二十世纪七十年代迎来了第一次人工智能寒冬……"}
  ]
}
```

第 2 步：执行生成：

```bash
python /mnt/skills/public/podcast-generation/scripts/generate.py \
  --script-file /mnt/user-data/workspace/ai-history-script.json \
  --output-file /mnt/user-data/outputs/ai-history-podcast.mp3 \
  --transcript-file /mnt/user-data/outputs/ai-history-transcript.md
```

生成：

- `ai-history-podcast.mp3`：播客音频。
- `ai-history-transcript.md`：可读 Markdown 逐字稿。

## 专用模板

仅当用户请求匹配时阅读：

- [技术讲解](templates/tech-explainer.md)：将技术文档和教程转为播客。

## 输出格式

生成播客遵循“Hello Deer”格式：

- 一男一女两位主持人。
- 自然对话。
- 用“Hello Deer”问候开场。
- 目标时长约 10 分钟。
- 主持人轮流发言，使交流流畅。

## 输出处理

生成后：

- 播客和逐字稿保存在 `/mnt/user-data/outputs/`。
- 用 `present_files` 同时分享音频和逐字稿。
- 简要说明主题、时长和主持人。
- 如需调整，可重新生成。

## 环境要求

必须设置相应环境变量：

- 火山引擎：`VOLCENGINE_TTS_APPID` 和 `VOLCENGINE_TTS_ACCESS_TOKEN`。
- MiniMax：`MINIMAX_API_KEY`。
- `VOLCENGINE_TTS_CLUSTER`：火山引擎语音合成集群，可选，默认 `volcano_tts`。

## 注意事项

- **始终一次调用完整流程**，无需单独测试步骤或担心超时。
- 脚本语言代码应匹配内容语言，`en` 或 `zh`。
- 在脚本中简化技术内容，便于音频理解。
- 将公式、代码等复杂符号转述为通俗语言。
- 长内容可能生成更长播客。

## 提供方（火山引擎／MiniMax）

通过环境变量自动选择：

- 设置 `VOLCENGINE_TTS_APPID` 和 `VOLCENGINE_TTS_ACCESS_TOKEN`：使用默认火山引擎。
- 只设置 `MINIMAX_API_KEY`：使用 MiniMax（`/v1/t2a_v2`）。
- 用 `PODCAST_GENERATION_PROVIDER=volcengine|minimax` 强制指定。

MiniMax 覆盖项：

- `MINIMAX_API_HOST`，默认 `https://api.minimaxi.com`。
- `MINIMAX_TTS_MODEL`，默认 `speech-2.6-hd`。
- `MINIMAX_TTS_VOICE_MALE`，默认 `male-qn-qingse`。
- `MINIMAX_TTS_VOICE_FEMALE`，默认 `female-tianmei`。

并发由各提供方内部管理：MiniMax 单线程运行以减少限流失败，火山引擎使用 4 个工作线程。调用方没有并发调节参数；短期限流由自动退避重试处理。
