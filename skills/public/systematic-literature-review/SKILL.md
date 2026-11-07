---
name: systematic-literature-review
description: 当用户需要针对某一主题跨多篇学术论文开展系统性文献综述、调查或综合分析时使用，也适用于带注释的参考文献列表和跨论文比较。检索 arXiv，并按 APA（American Psychological Association，美国心理学会）、IEEE（Institute of Electrical and Electronics Engineers，电气与电子工程师协会）或 BibTeX 格式输出报告。单篇论文评审请使用 academic-paper-review。
---

# 系统性文献综述技能

## 概述

本技能针对研究主题，跨多篇学术论文生成结构化的系统性文献综述。根据主题查询检索 arXiv，并行提取各篇论文的结构化元数据（研究问题、方法、主要发现、局限），归纳论文集合中的共同主题，最后输出引用格式统一的报告。

与 `academic-paper-review` 的区别：该技能深入评审单篇论文，本技能对多篇论文进行广度优先的综合分析。如果用户只提供一篇论文的链接并要求“评审这篇论文”，请转用 `academic-paper-review`。

## 适用情况

用户有以下需求时使用：

- 某一主题的文献调查，例如“调查 Transformer 注意力变体”“综述扩散模型文献”。
- 跨多篇论文的综合分析，例如“近期论文对 X 有什么结论”“比较 Y 领域论文的方法”。
- 引用格式统一的系统性综述，例如“按美国心理学会格式综述 Z”。
- 某一主题的带注释参考文献列表。
- 指定时间窗口内某领域的研究趋势概览。

以下情况不使用：

- 用户只提供一篇论文并请求评审，使用 `academic-paper-review`。
- 事实性问题无需综合多个来源，直接回答。
- 普通网页研究无需学术严谨性，使用常规网页搜索。

## 工作流程

共五个阶段，按顺序执行。

### 阶段 1：规划

开始检索前，确认以下信息。若有不明确之处，用一个澄清问题涵盖缺失信息，不要逐项询问。

- 主题：用通俗语言描述研究领域，例如“Transformer 注意力变体”。
- 范围：论文数量默认 20 篇，上限 50 篇；可选时间窗口（如“最近两年”）和 arXiv 分类（如 `cs.CL`、`cs.CV`）。
- 引用格式：APA（American Psychological Association，美国心理学会）、IEEE（Institute of Electrical and Electronics Engineers，电气与电子工程师协会）或 BibTeX。用户未指定且没有明确投稿目标时，默认采用美国心理学会格式。
- 输出位置：最终报告保存位置，默认 `/mnt/user-data/outputs/`。

如果用户要求“超过 50 篇”，礼貌地将数量限制为 50，并说明超过此规模后综合分析质量会迅速下降；更大规模的调查应按子主题拆分。

### 阶段 2：检索 arXiv

调用附带的检索脚本。不要通过其他方式抓取 arXiv，也不要自行编写网络客户端；脚本已正确处理链接编码、Atom 解析和标识规范化。

```bash
python /mnt/skills/public/systematic-literature-review/scripts/arxiv_search.py \
  "<topic>" \
  --max-results <N> \
  [--category <cat>] \
  [--sort-by relevance] \
  [--start-date YYYY-MM-DD] \
  [--end-date YYYY-MM-DD]
```

重要：检索前先提炼 2-3 个核心关键词。不要把用户的完整主题描述作为查询。调用脚本前，将主题缩减为最关键的 2-3 个词；“在计算机视觉中”“用于自然语言处理”“变体”“近期”等限定信息应放入 `--category` 或 `--start-date`，不要塞入查询字符串。

查询应简短。脚本会用双引号包裹多词查询，在 arXiv 上进行短语匹配：

- `"diffusion models"`：精确匹配该短语，通常能返回相关论文。
- `"diffusion models in computer vision"`：精确匹配整个五词短语，过于具体，可能返回零结果，因为很少有论文包含完全相同的字符串。

用 2-3 个核心关键词查询，通过分类参数缩小领域：

| 用户描述 | 合适的查询 | 不合适的查询 |
|---|---|---|
| “计算机视觉中的扩散模型” | `"diffusion models" --category cs.CV` | `"diffusion models in computer vision"` |
| “Transformer 注意力变体” | `"transformer attention"` | `"transformer attention variants in NLP"` |
| “用于分子的图神经网络” | `"graph neural networks" --category cs.LG` | `"graph neural networks for molecular property prediction"` |

脚本向标准输出打印 JSON（JavaScript Object Notation，JavaScript 对象表示法）数组，每篇论文包含 `id`、`title`、`authors`、`abstract`、`published`、`updated`、`categories`、`pdf_url`、`abs_url`。

排序策略：

- 始终使用 `relevance` 排序：arXiv 的相关性评分可确保结果确实围绕主题。`submittedDate` 会优先返回分类中最近提交的论文，可能大多偏离主题。
- 用户要求“近期”论文或指定时间窗口时，将 `--sort-by relevance` 与 `--start-date` 结合。例如“近期扩散模型论文”使用 `--sort-by relevance --start-date 2024-01-01`。
- 仅当用户明确要求按时间排列（如“按发表顺序展示论文”）时，使用 `submittedDate`。这种情况很少见。
- `lastUpdatedDate` 通常无用，除非用户要求，否则忽略。

只执行一次检索。结果不够理想时，不要改写查询重试；反复更换措辞会浪费工具调用，并可能触发递归上限。若结果确实为零，告知用户，并建议扩大主题或取消分类过滤。

若返回论文少于请求数量，这就是该查询在 arXiv 上的实际结果规模。不要凑数；报告实际数量后继续。

脚本失败（网络错误或平台返回非成功状态）时，告知具体错误并停止，不要编造论文元数据。

不要将检索结果保存到文件。结果保留在上下文中供阶段 3 使用；整个流程只在阶段 5 保存最终报告。

### 阶段 3：并行提取元数据

必须通过 `task` 工具将提取任务委派给子代理，不要自行提取。这是明确要求。禁止：

- 编写 `python -c "papers = [...]"` 或其他脚本处理论文。
- 在自己的上下文中逐篇读取摘要并提取元数据。
- 在本阶段使用 `task` 以外的工具。

调用 `task` 启动子代理。自行提取 10-50 篇论文会占用过多上下文，降低阶段 4 的综合分析质量；每个子代理只接收自己的论文批次，在独立上下文中提取，结果更清晰。

按每批约 5 篇拆分，对每批调用 `task`，指定 `subagent_type: "general-purpose"`。子代理接收纯文本摘要，返回结构化结果。

并发上限：每轮最多 3 个子代理。DeerFlow 运行时强制 `MAX_CONCURRENT_SUBAGENTS = 3`，同轮多余派遣可能被静默丢弃，且不会通知模型。因此必须采用下表：

| 论文数 | 每批约 5 篇的批次数 | 轮数 | 各轮子代理数 |
|---|---|---|---|
| 1–5 | 1 批 | 1 轮 | 1 |
| 6–10 | 2 批 | 1 轮 | 2 |
| 11–15 | 3 批 | 1 轮 | 3 |
| 16–20 | 4 批 | 2 轮 | 3 + 1 |
| 21–25 | 5 批 | 2 轮 | 3 + 2 |
| 26–30 | 6 批 | 2 轮 | 3 + 3 |
| 31–35 | 7 批 | 3 轮 | 3 + 3 + 1 |
| 36–40 | 8 批 | 3 轮 | 3 + 3 + 2 |
| 41–45 | 9 批 | 3 轮 | 3 + 3 + 3 |
| 46–50 | 10 批 | 4 轮 | 3 + 3 + 3 + 1 |

同一轮绝不能派出超过 3 个子代理。例如“2 轮（3 + 1）”表示先并行派出 3 个，全部完成后再在下一轮派出 1 个。主代理层面各轮严格串行。

数量落在区间中时（如 23 篇），使用对应的向上取整布局，但只派出实际需要的批次。表格规定布局，不要求补齐不存在的论文。

由主代理分批：阶段 2 已获得每篇摘要，子代理只需接收文本，无需访问网络或沙箱，只负责阅读并返回结构化结果。不要让子代理重新运行 `arxiv_search.py`，以免浪费令牌和触发限流。

向每个子代理发送以下结构化提示：

```text
执行此任务：从以下 arXiv 论文提取结构化元数据和主要发现。

论文：
[论文 1]
arxiv_id: 1706.03762
title: Attention Is All You Need
authors: Ashish Vaswani, Noam Shazeer, ...
published: 2017-06-12
abstract: <完整摘要原文>

[论文 2]
arxiv_id: ...
...

对每篇论文返回一个包含以下字段的对象：
- arxiv_id（字符串）
- title（字符串）
- authors（字符串列表）
- published_date（字符串，YYYY-MM-DD）
- research_question（1 句，论文解决什么问题）
- methodology（1-2 句，如何解决）
- key_findings（3-5 个要点，实际发现了什么）
- limitations（1-2 句，作者承认的局限或明显缺失之处）

返回 JSON（JavaScript Object Notation，JavaScript 对象表示法）数组，
每篇论文对应一个对象，顺序与输入相同。数组之外不要添加任何文字：
不要开场白，不要代码围栏，只返回数组。
```

解析子代理结果：`task` 返回带固定前缀的字符串，例如 `任务成功。结果：[...JSON...]`。解析前应剥离 `任务成功。结果：`、`任务失败。`、`任务已超时。` 等前缀。若某批失败或返回内容不可解析，记录问题和受影响论文，继续处理其余批次，不要因一个批次失败而放弃整体综合分析。

所有轮次完成后，将各批数组合并为一份论文元数据列表，并保持原顺序。

### 阶段 4：综合分析与格式化

生成最终综述，包含跨论文的主题分析和引用格式化。

跨论文综合分析必须超越逐篇罗列，至少识别：

- 主题：整组文献中重复出现的 3-6 个研究方向、方法或问题框架。
- 共识：多篇论文一致支持的发现。
- 分歧：不同结论或不可兼容的方法。
- 空白：整个文献集合仍未解决的问题，通常可从 `limitations` 中识别。

论文过少或差异过大、无法支持主题综合时（如 5 篇论文分属完全不同子主题），在报告中明确说明，不要强行归纳不存在的主题。

引用格式依用户偏好决定，只读取对应模板，不要一次读取全部三个：

- [templates/apa.md](templates/apa.md)：APA（American Psychological Association，美国心理学会）第 7 版。适合社会科学和多数计算机科学期刊；用户指定该格式或未指定时使用。
- [templates/ieee.md](templates/ieee.md)：IEEE（Institute of Electrical and Electronics Engineers，电气与电子工程师协会）数字引用。面向该协会会议、期刊或用户明确要求时使用。
- [templates/bibtex.md](templates/bibtex.md)：BibTeX 条目。用户提及 BibTeX、LaTeX 或需要机器可读参考文献时使用。重要：arXiv 预印本使用 `@misc`，不是 `@article`，模板对此有明确规定。

模板同时包含引用规则和完整报告结构（执行摘要、主题、逐篇注释、参考文献、方法部分）。严格按模板结构填入阶段 3 的元数据。

### 阶段 5：保存并展示

将完整报告保存到 `/mnt/user-data/outputs/slr-<topic-slug>-<YYYYMMDD>.md`，其中 `<topic-slug>` 为主题的小写连字符形式，例如 `transformer-attention`。然后调用 `present_files`，传入路径供用户下载。

聊天回复中展示简短预览：

1. 执行摘要：原样展示报告开头的 3-5 句段落。
2. 主题列表：仅列主题名及一句解释，不复制完整主题章节。
3. 论文数量和文件指引，例如“包含 20 篇论文、逐篇注释和规范参考文献的完整报告已保存为 `slr-transformer-attention-20260409.md`”。

不要把超过 2000 词的完整报告直接贴进聊天。逐篇注释、参考文献和方法留在文件中；预览用于让用户快速判断是否打开文件。

## 示例

### 示例 1：典型的系统性文献综述

用户：“综述近期 Transformer 注意力变体，20 篇，采用美国心理学会引用格式。”

流程：
1. 阶段 1：确认主题、20 篇范围和引用格式。仅有信息缺失时问一个问题，例如“有特定时间窗口吗，还是默认最近三年？”
2. 阶段 2：`arxiv_search.py "transformer attention" --max-results 20 --sort-by relevance --start-date 2023-01-01`。
3. 阶段 3：20 篇分两轮，先 3 个子代理各 5 篇，再 1 个子代理 5 篇，最后汇总。
4. 阶段 4：读取 `templates/apa.md`，按结构写报告，填入主题和逐篇注释。
5. 阶段 5：保存为 `slr-transformer-attention-20260409.md`，调用 `present_files`。

### 示例 2：有歧义的小规模请求

用户：“帮我调查几篇扩散模型论文。”

流程：
1. 阶段 1：“几篇”含糊，合并询问数量（10、20 或 30）和引用格式偏好，说明默认格式。
2. 用户回复“10 篇，BibTeX”。
3. 阶段 2：`arxiv_search.py "diffusion models" --max-results 10 --category cs.CV`。
4. 阶段 3：一轮，2 个子代理各 5 篇。
5. 阶段 4：读取 `templates/bibtex.md`，输出 `@misc` 条目，不用 `@article`。
6. 阶段 5：保存并展示。

### 示例 3：不适用的请求

用户：“这篇论文 https://arxiv.org/abs/1706.03762 能帮我评审吗？”

这是单篇论文评审，应转用 `academic-paper-review`。

## 注意事项

- 前提：`subagent_enabled` 必须为 `true`。阶段 3 依赖 `task` 并行提取；只有运行时配置 `config.configurable.subagent_enabled` 开启时才会加载该工具，否则无法按设计执行。
- 按设计只检索 arXiv，不查询 Semantic Scholar、PubMed 或 Google Scholar。arXiv 涵盖计算机科学、机器学习、物理和数学的大量预印本，是 DeerFlow 用户常见需求；多来源学术检索应由专用的模型上下文协议服务提供，不放在本技能内部。
- 论文硬上限为 50 篇，与阶段 3 每轮最多 3 个子代理、每批约 5 篇的策略相关。超过 50 篇会降低综合分析质量，应按子主题拆分。
- 若子代理未启用，不要声称执行了阶段 3 的并行计划；告知用户完整流程需要启用子代理，或建议缩小、拆分为较小规模的人工式评述。
- 子代理结果是字符串。解析载荷前先剥离 `任务成功。结果：`、`任务失败。`、`任务已超时。` 等前缀。
- `id` 是裸 arXiv 标识（如 `1706.03762`），不是链接，也不带版本后缀。完整链接位于 `abs_url`、`pdf_url`。
- 目标是综合分析。最终报告必须识别主题并比较结论；只逐篇罗列属于失败。无法发现主题时明确说明，不要伪造。
