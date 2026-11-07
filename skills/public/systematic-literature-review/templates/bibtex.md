# BibTeX 引用模板

用户提到 BibTeX、LaTeX，需要机器可读参考文献，或准备用 natbib、biblatex 等引用样式排版论文时使用。

## 关键要求：arXiv 论文使用 `@misc`，不使用 `@article`

arXiv 预印本必须采用 `@misc`。误用期刊条目是常见错误：

- `@article` 要求 `journal` 字段。arXiv 是预印本服务器，不是期刊；`journal = {arXiv}` 技术上不正确，有些参考文献样式会报错或显示不一致。
- `@misc` 适用于预印本、技术报告及其他非期刊出版物，可接受 `howpublished` 和 `eprint`，符合 arXiv 引用需求。
- 只有论文正式发表于同行评审出版物，且掌握出版元数据时，才改用 `@article` 或 `@inproceedings`。本流程仅有 arXiv 元数据，因此始终输出 `@misc`。

## 引用规则

### arXiv 预印本条目结构

```bibtex
@misc{citekey,
  author        = {LastName1, FirstName1 and LastName2, FirstName2 and ...},
  title         = {Title of the Paper},
  year          = {YYYY},
  eprint        = {ARXIV_ID},
  archivePrefix = {arXiv},
  primaryClass  = {PRIMARY_CATEGORY},
  url           = {https://arxiv.org/abs/ARXIV_ID}
}
```

真实示例：

```bibtex
@misc{vaswani2017attention,
  author        = {Vaswani, Ashish and Shazeer, Noam and Parmar, Niki and Uszkoreit, Jakob and Jones, Llion and Gomez, Aidan N. and Kaiser, {\L}ukasz and Polosukhin, Illia},
  title         = {Attention Is All You Need},
  year          = {2017},
  eprint        = {1706.03762},
  archivePrefix = {arXiv},
  primaryClass  = {cs.CL},
  url           = {https://arxiv.org/abs/1706.03762}
}
```

### 字段要求

- 引用键：`<firstauthorlast><year><firstwordoftitle>`，全部小写，无标点，例如 `vaswani2017attention`；报告内必须唯一。
- `author`：`LastName, FirstName and LastName, FirstName and ...`。作者间必须使用固定分隔词 `and`，不能用逗号替代；先姓、逗号、再名。
- 特殊字符：转义或用花括号包裹 LaTeX 敏感字符。例如 `Łukasz` 写为 `{\L}ukasz`，`é` 写为 `{\'e}`；也可将完整姓名用花括号包裹，如 `{Łukasz}`。不确定时，用花括号包裹有问题的姓名。
- `title`：含需保留大写的缩略词或专名时，使用双层花括号，例如 `title = {{BERT}: Pre-training of Deep Bidirectional Transformers}`；其他情况普通花括号即可。
- `year`：取 `published` 中的四位年份。
- `eprint`：裸 arXiv 标识，例如 `1706.03762`，不带 `arXiv:` 前缀或版本后缀。
- `archivePrefix`：固定为 `{arXiv}`。
- `primaryClass`：取 `categories` 中第一个分类，如 `cs.CL`、`cs.CV`、`stat.ML`，代表主要学科。
- `url`：使用元数据中的完整 `abs_url`。

## 报告结构

BibTeX 与其他两种格式略有区别：参考文献通常单独保存在 `.bib` 文件中，正文使用 LaTeX 风格的 `\cite{key}` 引用。本流程输出 Markdown，因此在正文中原样显示引用命令，并在末尾代码块中提供条目。

```markdown
# 系统性文献综述：<主题>

**日期**：<YYYY-MM-DD>
**论文数量**：<N>
**范围**：<arXiv 查询、分类、时间窗口>
**引用格式**：BibTeX

## 执行摘要

<3-5 句，使用 \cite{key} 引用，例如“Transformer 架构 \cite{vaswani2017attention} 已成为主流”。>

## 研究方法

本综述使用查询词 `<query>`，于 <YYYY-MM-DD> 检索了 <N> 篇 arXiv 论文<，限定分类 <cat>><，发表时间为 <start_date> 至 <end_date>>。语言模型代理提取元数据，主代理完成跨论文综合分析。正文使用 BibTeX 引用键，对应条目位于文末。

**本综述的局限**：arXiv 预印本未经同行评审，覆盖范围限于 arXiv。

## 研究主题

### 主题 1：<主题名称>

<用段落说明主题，使用 \cite{key} 引用，例如“原始 Transformer 架构 \cite{vaswani2017attention} 引入自注意力，随后在 \cite{dai2019transformerxl} 中扩展”。>

### 主题 2：<主题名称>

<...>

## 共识与分歧

**共识**：<例如“多篇论文 \cite{key1,key2,key3} 一致认为 X 必不可少”。>

**分歧**：<...>

## 研究空白与待解问题

<...>

## 逐篇注释

### \cite{vaswani2017attention} — "Attention Is All You Need" (2017)

**研究问题**：<1 句>
**研究方法**：<1-2 句>
**主要发现**：
- <要点>
- <要点>
- <要点>
**局限**：<1-2 句>

### \cite{devlin2018bert} — "BERT: Pre-training of Deep Bidirectional Transformers" (2018)

<...>

## BibTeX 参考文献

将以下条目保存为 .bib 文件，并在 LaTeX 文档中通过 \bibliography{filename} 引用。

\`\`\`bibtex
@misc{vaswani2017attention,
  author        = {Vaswani, Ashish and Shazeer, Noam and Parmar, Niki and Uszkoreit, Jakob and Jones, Llion and Gomez, Aidan N. and Kaiser, {\L}ukasz and Polosukhin, Illia},
  title         = {Attention Is All You Need},
  year          = {2017},
  eprint        = {1706.03762},
  archivePrefix = {arXiv},
  primaryClass  = {cs.CL},
  url           = {https://arxiv.org/abs/1706.03762}
}

@misc{devlin2018bert,
  author        = {Devlin, Jacob and Chang, Ming-Wei and Lee, Kenton and Toutanova, Kristina},
  title         = {{BERT}: Pre-training of Deep Bidirectional Transformers for Language Understanding},
  year          = {2018},
  eprint        = {1810.04805},
  archivePrefix = {arXiv},
  primaryClass  = {cs.CL},
  url           = {https://arxiv.org/abs/1810.04805}
}

其余条目，每篇一条。
\`\`\`
```

实际报告中使用真正的 BibTeX 代码围栏。此处内层反引号的转义仅用于避免嵌套模板显示冲突。

## 完成前的质量检查

保存报告前确认：

- [ ] 所有条目都是 `@misc`，不使用 `@article`，因为本流程只有 arXiv 元数据。
- [ ] 引用键在报告内唯一。
- [ ] 引用键遵循 `<firstauthorlast><year><firstword>`，全部小写。
- [ ] `author` 中使用固定的 ` and ` 分隔作者。
- [ ] 姓名中的 LaTeX 特殊字符已转义或包裹花括号。
- [ ] `eprint` 为裸标识，不带前缀或版本后缀。
- [ ] `primaryClass` 来自第一个分类。
- [ ] 每个 `\cite{key}` 都对应一个参考文献条目。
- [ ] 条目放入 BibTeX 代码围栏，用户可直接复制到 `.bib` 文件。
