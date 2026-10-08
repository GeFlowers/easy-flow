'''构造记忆更新提示，并将摘要和事实按安全边界及令牌预算整理为注入文本。'''

from __future__ import annotations

import html
import logging
import math
import re
import threading
import time
from typing import Any, cast

logger = logging.getLogger(__name__)

try:
    import tiktoken

    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

MEMORY_UPDATE_PROMPT = """You are a memory management system. Your task is to analyze a conversation and update the user's memory profile.

Current Memory State:
<current_memory>
{current_memory}
</current_memory>

New Conversation to Process:
<conversation>
{conversation}
</conversation>

Instructions:
1. Analyze the conversation for important information about the user
2. Extract relevant facts, preferences, and context with specific details (numbers, names, technologies)
3. Update the memory sections as needed following the detailed length guidelines below

Before extracting facts, perform a structured reflection on the conversation:
1. Error/Retry Detection: Did the agent encounter errors, require retries, or produce incorrect results?
   If yes, record the root cause and correct approach as a high-confidence fact with category "correction".
2. User Correction Detection: Did the user correct the agent's direction, understanding, or output?
   If yes, record the correct interpretation or approach as a high-confidence fact with category "correction".
   Include what went wrong in "sourceError" only when category is "correction" and the mistake is explicit in the conversation.
3. Project Constraint Discovery: Were any project-specific constraints discovered during the conversation?
   If yes, record them as facts with the most appropriate category and confidence.

{correction_hint}

Memory Section Guidelines:

**User Context** (Current state - concise summaries):
- workContext: Professional role, company, key projects, main technologies (2-3 sentences)
  Example: Core contributor, project names with metrics (16k+ stars), technical stack
- personalContext: Languages, communication preferences, key interests (1-2 sentences)
  Example: Bilingual capabilities, specific interest areas, expertise domains
- topOfMind: Multiple ongoing focus areas and priorities (3-5 sentences, detailed paragraph)
  Example: Primary project work, parallel technical investigations, ongoing learning/tracking
  Include: Active implementation work, troubleshooting issues, market/research interests
  Note: This captures SEVERAL concurrent focus areas, not just one task

**History** (Temporal context - rich paragraphs):
- recentMonths: Detailed summary of recent activities (4-6 sentences or 1-2 paragraphs)
  Timeline: Last 1-3 months of interactions
  Include: Technologies explored, projects worked on, problems solved, interests demonstrated
- earlierContext: Important historical patterns (3-5 sentences or 1 paragraph)
  Timeline: 3-12 months ago
  Include: Past projects, learning journeys, established patterns
- longTermBackground: Persistent background and foundational context (2-4 sentences)
  Timeline: Overall/foundational information
  Include: Core expertise, longstanding interests, fundamental working style

**Facts Extraction**:
- Extract specific, quantifiable details (e.g., "16k+ GitHub stars", "200+ datasets")
- Include proper nouns (company names, project names, technology names)
- Preserve technical terminology and version numbers
- Categories:
  * preference: Tools, styles, approaches user prefers/dislikes
  * knowledge: Specific expertise, technologies mastered, domain knowledge
  * context: Background facts (job title, projects, locations, languages)
  * behavior: Working patterns, communication habits, problem-solving approaches
  * goal: Stated objectives, learning targets, project ambitions
  * correction: Explicit agent mistakes or user corrections, including the correct approach
- Fact lifetime (``expected_valid_days``, optional integer):
  How many days before this fact should be reviewed for possible removal.
  The system schedules review automatically; omit when uncertain.
  * <= 14: highly transient - active bugs, immediate tasks, today's focus
  * 15-60: short-term - current experiments, in-progress side projects, near-term goals
  * 60-180: medium-term - current role, active tech stack, ongoing preferences
  * 180-365: stable - professional background, established working patterns
  * > 365: very stable - core skills, native language, personality traits
  Assign the value that semantically fits; values above the server-configured
  ceiling are silently reduced on storage.
- Confidence levels:
  * 0.9-1.0: Explicitly stated facts ("I work on X", "My role is Y")
  * 0.7-0.8: Strongly implied from actions/discussions
  * 0.5-0.6: Inferred patterns (use sparingly, only for clear patterns)

**What Goes Where**:
- workContext: Current job, active projects, primary tech stack
- personalContext: Languages, personality, interests outside direct work tasks
- topOfMind: Multiple ongoing priorities and focus areas user cares about recently (gets updated most frequently)
  Should capture 3-5 concurrent themes: main work, side explorations, learning/tracking interests
- recentMonths: Detailed account of recent technical explorations and work
- earlierContext: Patterns from slightly older interactions still relevant
- longTermBackground: Unchanging foundational facts about the user

**Multilingual Content**:
- Preserve original language for proper nouns and company names
- Keep technical terms in their original form (DeepSeek, LangGraph, etc.)
- Note language capabilities in personalContext

Output Format (JSON):
{{
  "user": {{
    "workContext": {{ "summary": "...", "shouldUpdate": true/false }},
    "personalContext": {{ "summary": "...", "shouldUpdate": true/false }},
    "topOfMind": {{ "summary": "...", "shouldUpdate": true/false }}
  }},
  "history": {{
    "recentMonths": {{ "summary": "...", "shouldUpdate": true/false }},
    "earlierContext": {{ "summary": "...", "shouldUpdate": true/false }},
    "longTermBackground": {{ "summary": "...", "shouldUpdate": true/false }}
  }},
  "newFacts": [
    {{ "content": "...", "category": "preference|knowledge|context|behavior|goal|correction", "confidence": 0.0-1.0, "expected_valid_days": 90 }}
  ],
  "factsToRemove": ["fact_id_1", "fact_id_2"],
  "staleFactsToRemove": [{{ "id": "fact_id", "reason": "brief explanation" }}],
  "staleFactsToExtend": [{{ "id": "fact_id", "extend_by_days": 365, "reason": "brief explanation" }}],
  "factsToConsolidate": [
    {{
      "sourceIds": ["fact_id_1", "fact_id_2"],
      "consolidated": {{ "content": "synthesized fact", "category": "knowledge", "confidence": 0.9 }}
    }}
  ]
}}

Important Rules:
- Only set shouldUpdate=true if there's meaningful new information
- Follow length guidelines: workContext/personalContext are concise (1-3 sentences), topOfMind and history sections are detailed (paragraphs)
- Include specific metrics, version numbers, and proper nouns in facts
- Only add facts that are clearly stated (0.9+) or strongly implied (0.7+)
- Use category "correction" for explicit agent mistakes or user corrections; assign confidence >= 0.95 when the correction is explicit
- Include "sourceError" only for explicit correction facts when the prior mistake or wrong approach is clearly stated; omit it otherwise
- Remove facts that are contradicted by new information
- When updating topOfMind, integrate new focus areas while removing completed/abandoned ones
  Keep 3-5 concurrent focus themes that are still active and relevant
- For history sections, integrate new information chronologically into appropriate time period
- Preserve technical accuracy - keep exact names of technologies, companies, projects
- Focus on information useful for future interactions and personalization
- IMPORTANT: Do NOT record file upload events in memory. Uploaded files are
  session-specific and ephemeral — they will not be accessible in future sessions.
  Recording upload events causes confusion in subsequent conversations.

{staleness_review_section}

{consolidation_section}

Return ONLY valid JSON, no explanation or markdown."""


STALENESS_REVIEW_PROMPT = """## Staleness Review

The following facts have reached their individual review window and may no longer
accurately reflect the user's current situation. Each entry shows a ``valid:Nd``
annotation - the number of days this fact was expected to remain valid before
re-evaluation. Use it to calibrate conservatism: a ``valid:30d`` fact was
considered volatile at creation; a ``valid:365d`` fact was considered stable.

<stale_facts>
{stale_facts}
</stale_facts>

For each fact, decide KEEP, REMOVE, or EXTEND:
- KEEP: Still likely valid - even if not mentioned in this conversation.
  Stable attributes (native language, core expertise, personality traits) often
  remain true indefinitely.
- REMOVE: Outdated, contradicted by recent context, or no longer relevant.
  Examples: tech-stack migrations, job changes, relocated offices, abandoned projects.
- EXTEND: Keep but recalibrate the review window (see below).

Add REMOVE decisions to "staleFactsToRemove" in your output JSON.
Each entry must be {{"id": "fact_id", "reason": "brief explanation"}}.
The reason should cite what signal in the conversation (or absence thereof)
supports the removal.

Optionally, for facts you KEEP and wish to recalibrate, add them to
"staleFactsToExtend" with the number of days from now before the next review:
{{"id": "fact_id", "extend_by_days": 365, "reason": "brief explanation"}}
Use this when the current window seems miscalibrated - e.g. a core skill marked
``valid:30d`` that is clearly stable, or a goal nearing completion whose window
should shrink. Omit facts whose current window already seems appropriate.

Be conservative - when in doubt, KEEP. Removing a valid fact is worse than
keeping a slightly stale one, because the next review cycle will re-evaluate it."""


CONSOLIDATION_PROMPT = """## Memory Consolidation

The following fact categories have accumulated many individual entries.
Review each group and identify facts that can be synthesized into a single,
richer consolidated fact that preserves all key information.

{consolidation_groups}

For each group, decide:
- CONSOLIDATE: Multiple facts can be merged into one richer fact.
  Specify the source fact IDs and the consolidated content.
- SKIP: Facts are distinct enough to remain separate.

Add consolidation decisions to "factsToConsolidate" in your output JSON.
Each entry: {{"sourceIds": ["fact_id_1", "fact_id_2"], "consolidated": {{"content": "...", "category": "...", "confidence": 0.9}}}}

Rules:
- The consolidated fact must preserve ALL key details from source facts
- Only consolidate facts that describe the same aspect of the user
- Confidence of consolidated fact = max of source confidences
- Be conservative - when in doubt, keep facts separate
- Maximum {max_groups} consolidation groups per cycle"""


FACT_EXTRACTION_PROMPT = """Extract factual information about the user from this message.

Message:
{message}

Extract facts in this JSON format:
{{
  "facts": [
    {{ "content": "...", "category": "preference|knowledge|context|behavior|goal|correction", "confidence": 0.0-1.0 }}
  ]
}}

Categories:
- preference: User preferences (likes/dislikes, styles, tools)
- knowledge: User's expertise or knowledge areas
- context: Background context (location, job, projects)
- behavior: Behavioral patterns
- goal: User's goals or objectives
- correction: Explicit corrections or mistakes to avoid repeating

Rules:
- Only extract clear, specific facts
- Confidence should reflect certainty (explicit statement = 0.9+, implied = 0.6-0.8)
- Skip vague or temporary information

Return ONLY valid JSON."""


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
        return f"- [{category} | {confidence:.2f}] {content} (avoid: {source_error})"
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

    header = "Facts:\n"
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

    user_data = memory_data.get("user", {})
    if user_data:
        user_sections = []

        work_ctx = user_data.get("workContext", {})
        if work_ctx.get("summary"):
            user_sections.append(f"Work: {_escape_summary(work_ctx['summary'])}")

        personal_ctx = user_data.get("personalContext", {})
        if personal_ctx.get("summary"):
            user_sections.append(f"Personal: {_escape_summary(personal_ctx['summary'])}")

        top_of_mind = user_data.get("topOfMind", {})
        if top_of_mind.get("summary"):
            user_sections.append(f"Current Focus: {_escape_summary(top_of_mind['summary'])}")

        if user_sections:
            sections.append("User Context:\n" + "\n".join(f"- {s}" for s in user_sections))

    history_data = memory_data.get("history", {})
    if history_data:
        history_sections = []

        recent = history_data.get("recentMonths", {})
        if recent.get("summary"):
            history_sections.append(f"Recent: {_escape_summary(recent['summary'])}")

        earlier = history_data.get("earlierContext", {})
        if earlier.get("summary"):
            history_sections.append(f"Earlier: {_escape_summary(earlier['summary'])}")

        background = history_data.get("longTermBackground", {})
        if background.get("summary"):
            history_sections.append(f"Background: {_escape_summary(background['summary'])}")

        if history_sections:
            sections.append("History:\n" + "\n".join(f"- {s}" for s in history_sections))

    facts_data = memory_data.get("facts", [])
    guaranteed_line_tokens = 0
    facts_header = "Facts:\n"
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
            lines.append(f"User: {content}")
        elif role == "ai":
            lines.append(f"Assistant: {content}")

    return "\n\n".join(lines)
