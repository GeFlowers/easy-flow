'''构造记忆更新提示，并将摘要和事实按安全边界及令牌预算整理为注入文本。'''

from __future__ import annotations

import html
import logging
import math
import re
import threading
import time
from typing import Any, cast

from deerflow.agents.memory.schema import normalize_memory

logger = logging.getLogger(__name__)

try:
    import tiktoken

    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

MEMORY_UPDATE_PROMPT = """你是记忆管理系统，负责分析对话并更新用户的记忆档案。

当前记忆状态：
<current_memory>
{current_memory}
</current_memory>

待处理的新对话：
<conversation>
{conversation}
</conversation>

操作要求：
1. 分析对话，识别与用户有关的重要信息。
2. 提取相关事实、偏好和背景，保留具体细节（数字、名称、技术）。
3. 根据需要更新各记忆部分，遵循下方详细的长度要求。

提取事实前，先对对话进行结构化反思：
1. 错误与重试检测：代理是否遇到错误、需要重试或产生了不正确的结果？
   如果是，将根本原因和正确做法记录为高置信度事实，类别为 "correction"。
2. 用户纠正检测：用户是否纠正了代理的方向、理解或输出？
   如果是，将正确理解或做法记录为高置信度事实，类别为 "correction"。
   仅当类别为 "correction" 且对话明确指出错误时，才在 "sourceError" 中记录错误内容。
3. 项目约束发现：对话是否揭示了项目特有的约束？
   如果是，以最合适的类别和置信度将其记录为事实。

{correction_hint}

记忆各部分要求：

**用户上下文 user**：仅维护一个 summary，不再划分子类别。
- 综合描述用户当前的工作、主要项目、语言和沟通偏好、兴趣及近期重点。
- 用一段自然文字概括，通常 4-8 句；保留具体且仍有效的重要信息，不为凑句数添加内容。

**历史背景 history**：仅维护一个 summary，不再按时间段或背景类别拆分。
- 综合描述过去的重要经历、项目变化、学习历程和长期背景。
- 用一段自然文字概括，通常 4-8 句；已知时间关系可以写进正文，不得编造时间。

**事实提取**：
- 提取具体、可量化的细节（如“超过 1.6 万 GitHub 星标”“超过 200 个数据集”）。
- 包含专有名词（公司名、项目名、技术名）。
- 保留技术术语和版本号。
- 类别：
  * preference：用户喜欢或不喜欢的工具、风格和方法。
  * knowledge：具体专长、已掌握的技术和领域知识。
  * context：背景事实（职位、项目、地点、语言）。
  * behavior：工作习惯、沟通习惯和解决问题的方法。
  * goal：明确表达的目标、学习目标和项目愿景。
  * correction：明确的代理错误或用户纠正，包含正确做法。
- 事实有效期（``expected_valid_days``，可选整数）：
  经过多少天后应复核此事实，判断是否需要移除。
  系统会自动安排复核；无法确定时省略。
  * <= 14：高度短暂，例如当前缺陷、即时任务、当天重点。
  * 15-60：短期，例如当前实验、正在进行的支线项目、近期目标。
  * 60-180：中期，例如当前职务、正在使用的技术栈、持续偏好。
  * 180-365：稳定，例如职业背景、已形成的工作习惯。
  * > 365：非常稳定，例如核心技能、母语、性格特征。
  按语义选择合适的值；超过服务器配置上限的值会在存储时自动下调。
- 置信度：
  * 0.9-1.0：明确陈述的事实（“我从事 X”“我的职务是 Y”）。
  * 0.7-0.8：行动或讨论中强烈暗示的信息。
  * 0.5-0.6：推断出的模式（谨慎使用，仅限模式明确时）。

**摘要更新规则**：
- user 关注当前用户画像，history 关注经历与背景；避免在两者中机械重复相同段落。
- 结合已有摘要和新对话进行语义融合；新摘要是整个分区的完整替代文本，不是新增片段。
- 保留仍有效的旧信息，修正已被明确否定的内容，移除已完成或放弃的即时关注事项。
- 没有相关变化时返回 shouldUpdate=false，不得用空摘要删除旧内容。

**多语言内容**：
- 专有名词和公司名保留原始语言。
- 技术术语保留原始形式（如 DeepSeek、LangGraph）。
- 在 user 摘要中记录语言能力。

输出格式（JSON（JavaScript Object Notation，JavaScript 对象表示法））：
{{
  "user": {{ "summary": "完整的用户上下文摘要", "shouldUpdate": true/false }},
  "history": {{ "summary": "完整的历史背景摘要", "shouldUpdate": true/false }},
  "newFacts": [
    {{ "content": "...", "category": "preference|knowledge|context|behavior|goal|correction", "confidence": 0.0-1.0, "expected_valid_days": 90 }}
  ],
  "factsToRemove": ["fact_id_1", "fact_id_2"],
  "staleFactsToRemove": [{{ "id": "fact_id", "reason": "简要说明" }}],
  "staleFactsToExtend": [{{ "id": "fact_id", "extend_by_days": 365, "reason": "简要说明" }}],
  "factsToConsolidate": [
    {{
      "sourceIds": ["fact_id_1", "fact_id_2"],
      "consolidated": {{ "content": "综合后的事实", "category": "knowledge", "confidence": 0.9 }}
    }}
  ]
}}

重要规则：
- 只有出现有意义的新信息时才设置 shouldUpdate=true。
- 用户上下文和历史背景各只输出一份完整摘要，不再输出嵌套子类别。
- 事实中包含具体指标、版本号和专有名词。
- 只添加明确陈述（0.9+）或强烈暗示（0.7+）的事实。
- 对明确的代理错误或用户纠正使用 "correction" 类别；明确纠正的置信度应 >= 0.95。
- 仅当先前错误或错误做法被明确陈述时，才在明确的纠正事实中包含 "sourceError"；否则省略。
- 移除被新信息否定的事实。
- 更新用户上下文时纳入新的关注领域，并移除已完成或放弃的事项。
  仅保留有对话依据且仍然活跃的关注主题，不强行凑数。
- 历史背景中的新信息应与旧经历自然融合，必要时在同一摘要内说明时间关系。
- 保持技术准确性，保留技术、公司和项目的准确名称。
- 重点记录有助于未来交互和个性化的信息。
- 重要：不要将文件上传事件记录到记忆中。上传文件仅属于当前会话，且是临时的，
  未来会话无法访问。记录上传事件会导致后续对话混淆。

{staleness_review_section}

{consolidation_section}

仅返回有效的 JSON（JavaScript Object Notation，JavaScript 对象表示法），不要解释或添加 Markdown 标记。"""


STALENESS_REVIEW_PROMPT = """## 过期事实复核

以下事实已到达各自的复核时间，可能不再准确反映用户现状。
每条记录带有 ``valid:Nd`` 标记，表示预期保持有效、之后需要重新评估的天数。
请据此决定谨慎程度：``valid:30d`` 表示创建时认为容易变化，
``valid:365d`` 表示创建时认为较稳定。

<stale_facts>
{stale_facts}
</stale_facts>

对每条事实选择 KEEP、REMOVE 或 EXTEND：
- KEEP：很可能仍有效，即使本次对话未提及。
  稳定属性（母语、核心专长、性格特征）通常会长期保持不变。
- REMOVE：已过时、与近期背景矛盾或已不再相关。
  例如：技术栈迁移、换工作、办公室搬迁、放弃项目。
- EXTEND：保留，但重新校准复核周期（见下文）。

将 REMOVE 决定添加到输出的 "staleFactsToRemove" 中。
每条记录必须为 {{"id": "fact_id", "reason": "简要说明"}}。
原因应说明对话中的哪些信号（或信号缺失）支持移除。

对于选择 KEEP 且希望重新校准的事实，可将其加入 "staleFactsToExtend"，
注明从现在到下次复核的天数：
{{"id": "fact_id", "extend_by_days": 365, "reason": "简要说明"}}
当当前周期不合适时使用，例如明显稳定却被标记为 ``valid:30d`` 的核心技能，
或接近完成、应缩短复核周期的目标。当前周期已合适的事实应省略。

请保持谨慎：不确定时选择 KEEP。移除有效事实的损失大于保留略过时的事实，
因为下个复核周期还会重新评估。"""


CONSOLIDATION_PROMPT = """## 记忆整合

以下事实类别积累了较多独立条目。请检查每组，识别可以综合成一条更充实事实的条目，
并保留所有关键信息。

{consolidation_groups}

对每组做出决定：
- CONSOLIDATE：多条事实可以合并为一条更充实的事实。
  指定来源事实标识和整合内容。
- SKIP：各事实具有足够区别，应独立保留。

将整合决定添加到输出的 "factsToConsolidate" 中。
每条记录：{{"sourceIds": ["fact_id_1", "fact_id_2"], "consolidated": {{"content": "...", "category": "...", "confidence": 0.9}}}}

规则：
- 整合后的事实必须保留来源事实的所有关键细节。
- 只整合描述用户同一方面的事实。
- 整合后的置信度等于来源置信度的最大值。
- 保持谨慎，不确定时独立保留各事实。
- 每个周期最多整合 {max_groups} 组。"""


FACT_EXTRACTION_PROMPT = """从这条消息中提取有关用户的事实信息。

消息：
{message}

按以下 JSON（JavaScript Object Notation，JavaScript 对象表示法）格式提取事实：
{{
  "facts": [
    {{ "content": "...", "category": "preference|knowledge|context|behavior|goal|correction", "confidence": 0.0-1.0 }}
  ]
}}

类别：
- preference：用户偏好（喜好、风格、工具）。
- knowledge：用户专长或知识领域。
- context：背景信息（地点、工作、项目）。
- behavior：行为模式。
- goal：用户目标。
- correction：明确的纠正或需要避免重复的错误。

规则：
- 仅提取明确、具体的事实。
- 置信度应反映确定程度（明确陈述 = 0.9+，暗示 = 0.6-0.8）。
- 跳过模糊或临时信息。

仅返回有效的 JSON（JavaScript Object Notation，JavaScript 对象表示法）。"""


_TIKTOKEN_ENCODING_MISSING = object()
_TIKTOKEN_ENCODING_LOADING = object()
_TIKTOKEN_RETRY_COOLDOWN_S = 600.0
_tiktoken_encoding_cache: dict[str, Any] = {}
_tiktoken_encoding_cache_lock = threading.Lock()


def _get_tiktoken_encoding(encoding_name: str = "cl100k_base") -> tiktoken.Encoding | None:
    '''获取指定编码器并复用缓存；并发加载、加载失败和重试冷却均由缓存状态协调。'''
    if not TIKTOKEN_AVAILABLE:
        return None

    with _tiktoken_encoding_cache_lock:
        cached = _tiktoken_encoding_cache.get(encoding_name, _TIKTOKEN_ENCODING_MISSING)
        if cached is _TIKTOKEN_ENCODING_LOADING:
            return None
        if isinstance(cached, tuple):
            _, failed_at = cached
            if time.monotonic() - failed_at < _TIKTOKEN_RETRY_COOLDOWN_S:
                return None
            cached = _TIKTOKEN_ENCODING_MISSING
        if cached is not _TIKTOKEN_ENCODING_MISSING:
            return cast("tiktoken.Encoding", cached)
        _tiktoken_encoding_cache[encoding_name] = _TIKTOKEN_ENCODING_LOADING

    try:
        encoding = tiktoken.get_encoding(encoding_name)
    except Exception:
        logger.warning("Failed to load tiktoken encoding %r; falling back to char-based estimation", encoding_name, exc_info=True)
        with _tiktoken_encoding_cache_lock:
            _tiktoken_encoding_cache[encoding_name] = (None, time.monotonic())
        return None

    with _tiktoken_encoding_cache_lock:
        _tiktoken_encoding_cache[encoding_name] = encoding
    return encoding


def _char_based_token_estimate(text: str) -> int:
    '''使用字符比例估算令牌数，并单独计算中日韩字符以避免低估多语言记忆长度。'''
    cjk = sum(
        1
        for ch in text
        if "\u4e00" <= ch <= "\u9fff"
        or "\u3040" <= ch <= "\u30ff"
        or "\uac00" <= ch <= "\ud7a3"
    )
    return (len(text) - cjk) // 4 + cjk // 2


def _count_tokens(text: str, encoding_name: str = "cl100k_base", *, use_tiktoken: bool = True) -> int:
    '''优先使用指定编码器计数；禁用或加载失败时回退到无需联网的字符估算。'''
    if not use_tiktoken:
        return _char_based_token_estimate(text)

    encoding = _get_tiktoken_encoding(encoding_name)
    if encoding is None:
        return _char_based_token_estimate(text)

    try:
        return len(encoding.encode(text))
    except Exception:
        return _char_based_token_estimate(text)


def warm_tiktoken_cache() -> bool:
    '''提前加载默认编码缓存，返回编码是否可用，供服务启动流程判断预热结果。'''
    return _get_tiktoken_encoding("cl100k_base") is not None


def _coerce_confidence(value: Any, default: float = 0.0) -> float:
    '''将任意置信度值转换为 0 到 1 之间的有限浮点数，非法值使用默认值。'''
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return max(0.0, min(1.0, default))
    if not math.isfinite(confidence):
        return max(0.0, min(1.0, default))
    return max(0.0, min(1.0, confidence))


def _format_fact_line(fact: dict[str, Any]) -> str | None:
    '''校验并格式化单条事实，同时转义可由用户编辑的文本以保护系统提示边界。'''
    content_value = fact.get("content")
    if not isinstance(content_value, str):
        return None
    content = content_value.strip()
    if not content:
        return None
    category = str(fact.get("category", "context")).strip() or "context"
    confidence = _coerce_confidence(fact.get("confidence"), default=0.0)
    source_error = fact.get("sourceError")
    content = html.escape(content, quote=False)
    category = html.escape(category, quote=False)
    if category == "correction" and isinstance(source_error, str) and source_error.strip():
        source_error = html.escape(source_error.strip(), quote=False)
        return f"- [{category} | {confidence:.2f}] {content}（应避免：{source_error}）"
    return f"- [{category} | {confidence:.2f}] {content}"


def _escape_summary(value: Any) -> str:
    '''转义用户可编辑的摘要文本，避免其内容闭合记忆提示区块。'''
    return html.escape(str(value), quote=False)


def _select_fact_lines(
    ranked_facts: list[dict[str, Any]],
    *,
    token_budget: int,
    use_tiktoken: bool,
) -> tuple[list[str], int]:
    '''按输入排序依次选取事实行，达到预算时停止，并返回文本行及其消耗量。'''
    lines: list[str] = []
    consumed = 0
    for fact in ranked_facts:
        formatted = _format_fact_line(fact)
        if formatted is None:
            continue
        line_text = ("\n" + formatted) if lines else formatted
        line_tokens = _count_tokens(line_text, use_tiktoken=use_tiktoken)
        if consumed + line_tokens > token_budget:
            break
        lines.append(formatted)
        consumed += line_tokens
    return lines, consumed


def _fallback_format_facts(
    valid_facts: list[dict[str, Any]],
    *,
    preceding_section_cost: int,
    max_tokens: int,
    use_tiktoken: bool,
) -> tuple[str, list[str]] | tuple[None, None]:
    '''主格式化流程出错时改按置信度排序事实，并在剩余预算内返回备用区段。'''
    ranked = sorted(valid_facts, key=lambda f: _coerce_confidence(f.get("confidence"), default=0.0), reverse=True)

    header = "事实：\n"
    overhead = _count_tokens(header, use_tiktoken=use_tiktoken)
    line_budget = max_tokens - preceding_section_cost - overhead
    if line_budget <= 0:
        return None, None

    lines, _ = _select_fact_lines(ranked, token_budget=line_budget, use_tiktoken=use_tiktoken)
    if not lines:
        return None, None
    return header + "\n".join(lines), lines


def format_memory_for_injection(
    memory_data: dict[str, Any],
    max_tokens: int = 2000,
    *,
    use_tiktoken: bool = True,
    guaranteed_categories: list[str] | None = None,
    guaranteed_token_budget: int = 500,
) -> str:
    '''将用户摘要、历史背景和事实整理为系统提示文本，并按类别优先级及令牌预算裁剪。'''
    if not memory_data:
        return ""

    if isinstance(guaranteed_categories, str):
        raise TypeError("guaranteed_categories must be an iterable of strings, not a bare str")
    effective_guaranteed: frozenset[str] = frozenset(c.strip() for c in guaranteed_categories if isinstance(c, str) and c.strip()) if guaranteed_categories else frozenset()

    sections: list[str] = []
    memory_data = normalize_memory(memory_data)
    for key, label in (("user", "用户上下文"), ("history", "历史背景")):
        summary = memory_data[key]["summary"]
        if summary:
            sections.append(f"{label}：\n{_escape_summary(summary)}")

    facts_data = memory_data.get("facts", [])
    guaranteed_line_tokens = 0
    facts_header = "事实：\n"
    all_fact_lines: list[str] = []
    if isinstance(facts_data, list) and facts_data:
        base_text = "\n\n".join(sections)
        base_tokens = _count_tokens(base_text, use_tiktoken=use_tiktoken) if base_text else 0

        valid_facts = [f for f in facts_data if isinstance(f, dict) and isinstance(f.get("content"), str) and f.get("content", "").strip()]

        try:
            def _confidence_key(fact: dict[str, Any]) -> float:
                '''将事实置信度规范为可排序的有限数值。'''
                return _coerce_confidence(fact.get("confidence"), default=0.0)

            if effective_guaranteed:

                def _category_match(fact: dict[str, Any]) -> bool:
                    '''判断事实类别是否属于配置要求始终注入的类别。'''
                    raw = fact.get("category")
                    if not isinstance(raw, str):
                        return False
                    cat = raw.strip()
                    return bool(cat) and cat in effective_guaranteed

                guaranteed = sorted(
                    [f for f in valid_facts if _category_match(f)],
                    key=_confidence_key,
                    reverse=True,
                )
                regular = sorted(
                    [f for f in valid_facts if not _category_match(f)],
                    key=_confidence_key,
                    reverse=True,
                )
            else:
                guaranteed = []
                regular = sorted(valid_facts, key=_confidence_key, reverse=True)

            header_cost = _count_tokens(facts_header, use_tiktoken=use_tiktoken)

            guaranteed_lines: list[str] = []
            if guaranteed:
                guaranteed_line_budget = guaranteed_token_budget
                guaranteed_lines, guaranteed_line_tokens = _select_fact_lines(
                    guaranteed,
                    token_budget=guaranteed_line_budget,
                    use_tiktoken=use_tiktoken,
                )

            regular_lines: list[str] = []
            if regular:
                inter_group_newline_tokens = _count_tokens("\n", use_tiktoken=use_tiktoken) if guaranteed_lines else 0
                used_before_regular = base_tokens + header_cost + guaranteed_line_tokens + inter_group_newline_tokens
                regular_line_budget = max_tokens - used_before_regular
                if regular_line_budget > 0:
                    regular_lines, _ = _select_fact_lines(
                        regular,
                        token_budget=regular_line_budget,
                        use_tiktoken=use_tiktoken,
                    )

            all_fact_lines = guaranteed_lines + regular_lines
            if all_fact_lines:
                section_text = facts_header + "\n".join(all_fact_lines)
                sections.append(section_text)

        except Exception:
            logger.warning(
                "Memory injection: guaranteed-category path failed, falling back to confidence-only ranking",
                exc_info=True,
            )
            fallback, fallback_lines = _fallback_format_facts(
                valid_facts,
                preceding_section_cost=base_tokens,
                max_tokens=max_tokens,
                use_tiktoken=use_tiktoken,
            )
            if fallback:
                sections.append(fallback)
                all_fact_lines = fallback_lines

    if not sections:
        return ""

    result = "\n\n".join(sections)

    token_count = _count_tokens(result, use_tiktoken=use_tiktoken)
    effective_limit = max_tokens + guaranteed_line_tokens
    if token_count > effective_limit:
        facts_block = (facts_header + "\n".join(all_fact_lines)) if all_fact_lines else ""
        facts_block_tokens = _count_tokens(facts_block, use_tiktoken=use_tiktoken)
        separator_tokens = _count_tokens("\n\n", use_tiktoken=use_tiktoken)
        budget_for_non_facts = max(
            0,
            effective_limit - facts_block_tokens - (separator_tokens if facts_block else 0),
        )

        preceding_sections = sections[:-1] if all_fact_lines else sections
        preceding = "\n\n".join(preceding_sections)

        if preceding:
            preceding_tokens = _count_tokens(preceding, use_tiktoken=use_tiktoken)
            if preceding_tokens > budget_for_non_facts:
                char_per_token = len(preceding) / max(preceding_tokens, 1)
                target_chars = int(budget_for_non_facts * char_per_token * 0.95)
                preceding = preceding[:target_chars].rstrip() + "\n..."
            result = (preceding + "\n\n" + facts_block) if facts_block else preceding
        else:
            result = facts_block

    return result


def format_conversation_for_update(messages: list[Any]) -> str:
    '''将多模态对话转换为安全的用户/助手文本，移除上传路径并截断过长消息。'''
    lines = []
    for msg in messages:
        role = getattr(msg, "type", "unknown")
        content = getattr(msg, "content", str(msg))

        if isinstance(content, list):
            text_parts = []
            for p in content:
                if isinstance(p, str):
                    text_parts.append(p)
                elif isinstance(p, dict):
                    text_val = p.get("text")
                    if isinstance(text_val, str):
                        text_parts.append(text_val)
            content = " ".join(text_parts) if text_parts else str(content)

        if role == "human":
            content = re.sub(r"<uploaded_files>[\s\S]*?</uploaded_files>\n*", "", str(content)).strip()
            if not content:
                continue

        if len(str(content)) > 1000:
            content = str(content)[:1000] + "..."

        content = html.escape(str(content), quote=False)

        if role == "human":
            lines.append(f"用户：{content}")
        elif role == "ai":
            lines.append(f"助手：{content}")

    return "\n\n".join(lines)
