# APA（American Psychological Association，美国心理学会）第 7 版引用模板

用户要求该格式，或未指定引用格式时使用。采用作者—年份的文内引用形式。

## 引用规则

### 文内引用

- 单作者：`(Smith, 2024)` 或 `Smith (2024)`。
- 两位作者：括号内用 `(Smith & Jones, 2024)`，叙述式引用用 `Smith and Jones (2024)`。
- 三位及以上作者：从首次引用开始使用 `(Vaswani et al., 2017)` 或 `Vaswani et al. (2017)`。
- 同一括号内的多篇文献：按第一作者姓氏的字母顺序排列，以分号分隔，如 `(Devlin et al., 2018; Vaswani et al., 2017)`。

### arXiv 预印本的参考文献条目

采用带 arXiv 标识的格式：

```text
Author, A. A., Author, B. B., & Author, C. C. (Year). Title of the paper. arXiv. https://arxiv.org/abs/ARXIV_ID
```

真实示例来自论文元数据（标识 1706.03762、题名 Attention Is All You Need、发布日期 2017-06-12）：

```text
Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., Kaiser, Ł., & Polosukhin, I. (2017). Attention is all you need. arXiv. https://arxiv.org/abs/1706.03762
```

格式要求：

- 作者：`LastName, FirstInitial.`，中间名首字母可选。逗号分隔，最后一位前使用 `&`。
- 年份：取 `published` 中的年份，放在括号内。
- 标题：句首式大小写，仅首词和专有名词首字母大写。正式排版用斜体，纯 Markdown 中可用普通文本。
- 来源：固定写 `arXiv`，后接完整摘要页链接。
- 不添加数字对象标识符，除非论文已在有该标识的正式出版物发表；只有 arXiv 元数据时使用链接。

### 特殊情况

- 不超过 20 位作者：全部列出，用逗号分隔，最后一位前加 `&`。
- 至少 21 位作者：列出前 19 位、`...`，再列最后一位。
- arXiv 论文不应缺少链接，始终使用元数据中的 `abs_url`。

## 报告结构

严格按以下结构写综述正文，填入阶段 3 的提取结果和阶段 4 的综合分析。

```markdown
# 系统性文献综述：<主题>

**日期**：<YYYY-MM-DD>
**论文数量**：<N>
**范围**：<arXiv 查询、分类、时间窗口>
**引用格式**：美国心理学会第 7 版

## 执行摘要

<3-5 句综合说明该主题文献的整体状态、共同发现和领域格局。不要逐篇罗列。>

## 研究方法

本综述使用查询词 `<query>`，于 <YYYY-MM-DD> 检索了 <N> 篇 arXiv 论文<，限定分类 <cat>><，发表时间为 <start_date> 至 <end_date>>。按<相关性 | 提交日期>排序，纳入前 <N> 篇。由语言模型代理提取研究问题、方法、主要发现和局限，主代理完成跨论文综合分析。

**本综述的局限**：arXiv 预印本未经同行评审，部分论文可能与最终发表版本不同。覆盖范围限于 arXiv，未发布预印本的正式出版论文未被纳入。

## 研究主题

<3-6 个主题章节。每个主题应体现多篇论文反复出现的研究方向、问题框架或方法。>

### 主题 1：<主题名称>

<2-4 段说明主题，讨论时加入文内引用，例如“Vaswani et al. (2017) 提出 X，后续工作 (Devlin et al., 2018; Liu et al., 2019) 将其扩展到 Y”。描述论文之间的思想脉络，而非罗列论文。>

### 主题 2：<主题名称>

<...>

## 共识与分歧

**共识**：<多篇论文一致支持的发现，例如“多数论文认为 X 必不可少，并提供 Y 和 Z 的证据”。>

**分歧**：<结论不一致之处，例如“Vaswani et al. (2017) 主张 X，而 Dai et al. (2019) 在条件 Y 下发现相反结果”。>

## 研究空白与待解问题

<综合文献尚未解决的问题。从阶段 3 的 limitations 字段中识别重复模式；如五篇论文均提及同一缺失，应明确指出。>

## 逐篇注释

<每篇一小节，先按年份，再按第一作者排序，简要说明贡献。>

### Vaswani et al. (2017)

**研究问题**：<阶段 3 元数据中的 1 句描述>
**研究方法**：<1-2 句>
**主要发现**：
- <要点>
- <要点>
- <要点>
**局限**：<1-2 句>

### <下一篇论文>

<...>

## 参考文献

<按第一作者姓氏字母顺序排列，采用上方规定格式。>

Devlin, J., Chang, M.-W., Lee, K., & Toutanova, K. (2018). BERT: Pre-training of deep bidirectional transformers for language understanding. arXiv. https://arxiv.org/abs/1810.04805

Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., Kaiser, Ł., & Polosukhin, I. (2017). Attention is all you need. arXiv. https://arxiv.org/abs/1706.03762

<其余条目，每篇一条>
```

## 完成前的质量检查

保存报告前确认：

- [ ] 纳入的每篇论文同时出现在“逐篇注释”和“参考文献”中。
- [ ] 每处文内引用均对应参考文献条目。
- [ ] 作者采用 `LastName, FirstInitial.`，不采用 `FirstName LastName`。
- [ ] 文内年份放在括号中，参考文献年份位于条目前部。
- [ ] 参考文献标题采用句首式大小写，仅首词和专有名词大写。
- [ ] arXiv 链接使用 `abs_url`（`https://arxiv.org/abs/...`），不使用 `pdf_url`。
- [ ] 参考文献按第一作者姓氏字母顺序排列。
