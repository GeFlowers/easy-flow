'''校验并合并记忆事实，解析模型生成的更新方案，并管理记忆的读取、写入与复核。'''

import asyncio
import atexit
import concurrent.futures
import copy
import html
import json
import logging
import math
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from ..config import DeerMemConfig
from .prompt import (
    CONSOLIDATION_PROMPT,
    MEMORY_UPDATE_PROMPT,
    STALENESS_REVIEW_PROMPT,
    format_conversation_for_update,
)
from .storage import (
    MemoryStorage,
    create_empty_memory,
    utc_now_iso_z,
)

logger = logging.getLogger(__name__)


_SYNC_MEMORY_UPDATER_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="memory-updater-sync",
)
atexit.register(lambda: _SYNC_MEMORY_UPDATER_EXECUTOR.shutdown(wait=False))


def _validate_confidence(confidence: float) -> float:
    '''要求置信度为有限且介于 0 到 1 之间的数值，否则拒绝保存。'''
    if not math.isfinite(confidence) or confidence < 0 or confidence > 1:
        raise ValueError("confidence")
    return confidence


def _coerce_source_confidence(fact: dict[str, Any]) -> float:
    '''将可能损坏或类型不符的事实置信度安全转换为有限区间值，异常时采用默认值。'''
    raw = fact.get("confidence")
    if raw is None or isinstance(raw, bool):
        return 0.5
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(val, 1.0)) if math.isfinite(val) else 0.5


def _trim_facts_to_max(facts: list[dict[str, Any]], max_facts: int) -> list[dict[str, Any]]:
    '''超出事实数量上限时，按安全转换后的置信度从高到低保留事实。'''
    if len(facts) <= max_facts:
        return facts
    return sorted(facts, key=_coerce_source_confidence, reverse=True)[:max_facts]


def _extract_text(content: Any) -> str:
    '''提取模型响应中的纯文本，正确合并分块文本并读取结构化文本内容块。'''
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces: list[str] = []
        pending_str_parts: list[str] = []

        def flush_pending_str_parts() -> None:
            '''将连续的字符串片段合并为一个文本块，并清空暂存片段。'''
            if pending_str_parts:
                pieces.append("".join(pending_str_parts))
                pending_str_parts.clear()

        for block in content:
            if isinstance(block, str):
                pending_str_parts.append(block)
            elif isinstance(block, dict):
                flush_pending_str_parts()
                text_val = block.get("text")
                if isinstance(text_val, str):
                    pieces.append(text_val)

        flush_pending_str_parts()
        return "\n".join(pieces)
    return str(content)


_REQUIRED_MEMORY_UPDATE_TOP_LEVEL_KEYS = frozenset({"user", "history", "newFacts"})


def _normalize_memory_update_fact(fact: Any) -> dict[str, Any] | None:
    '''校验并规范一条模型生成的事实，丢弃内容、类别或置信度格式无效的条目。'''
    if not isinstance(fact, dict):
        return None

    raw_content = fact.get("content")
    if not isinstance(raw_content, str):
        return None
    content = raw_content.strip()
    if not content:
        return None

    raw_category = fact.get("category")
    category = raw_category.strip() if isinstance(raw_category, str) and raw_category.strip() else "context"

    raw_confidence = fact.get("confidence", 0.5)
    if isinstance(raw_confidence, bool):
        return None
    if isinstance(raw_confidence, str):
        raw_confidence = raw_confidence.strip()
        if not raw_confidence:
            return None
        try:
            raw_confidence = float(raw_confidence)
        except ValueError:
            return None
    elif isinstance(raw_confidence, (int, float)):
        raw_confidence = float(raw_confidence)
    else:
        return None

    if not math.isfinite(raw_confidence):
        return None

    normalized_fact = {
        "content": content,
        "category": category,
        "confidence": raw_confidence,
    }
    source_error = fact.get("sourceError")
    if isinstance(source_error, str):
        normalized_source_error = source_error.strip()
        if normalized_source_error:
            normalized_fact["sourceError"] = normalized_source_error

    raw_evd = fact.get("expected_valid_days")
    if isinstance(raw_evd, (int, float)) and not isinstance(raw_evd, bool):
        evd = int(raw_evd)
        if evd > 0:
            normalized_fact["expected_valid_days"] = evd

    return normalized_fact


def _normalize_memory_update_data(update_data: dict[str, Any]) -> dict[str, Any]:
    '''统一更新对象的字段结构，并拒绝包含危险的部分删除方案。'''
    user = update_data.get("user")
    history = update_data.get("history")
    new_facts = update_data.get("newFacts")
    facts_to_remove = update_data.get("factsToRemove")
    normalized_facts_to_remove = [fact_id for fact_id in facts_to_remove if isinstance(fact_id, str)] if isinstance(facts_to_remove, list) else []
    normalized_new_facts = []
    dropped_new_fact = not isinstance(new_facts, list)
    if isinstance(new_facts, list):
        for fact in new_facts:
            normalized_fact = _normalize_memory_update_fact(fact)
            if normalized_fact is not None:
                normalized_new_facts.append(normalized_fact)
            else:
                dropped_new_fact = True

    if normalized_facts_to_remove and dropped_new_fact:
        raise json.JSONDecodeError(
            "Unsafe partial memory update: factsToRemove with malformed newFacts",
            json.dumps(update_data, ensure_ascii=False),
            0,
        )

    stale_removals_raw = update_data.get("staleFactsToRemove")
    normalized_stale_removals: list[dict[str, str]] = []
    if isinstance(stale_removals_raw, list):
        for entry in stale_removals_raw:
            if not isinstance(entry, dict):
                continue
            fact_id = entry.get("id")
            if not isinstance(fact_id, str) or not fact_id:
                continue
            reason = entry.get("reason", "")
            normalized_stale_removals.append(
                {
                    "id": fact_id,
                    "reason": reason if isinstance(reason, str) else "",
                }
            )

    stale_extensions_raw = update_data.get("staleFactsToExtend")
    normalized_stale_extensions: list[dict[str, Any]] = []
    if isinstance(stale_extensions_raw, list):
        for entry in stale_extensions_raw:
            if not isinstance(entry, dict):
                continue
            fact_id = entry.get("id")
            if not isinstance(fact_id, str) or not fact_id:
                continue
            raw_extend = entry.get("extend_by_days")
            if isinstance(raw_extend, (int, float)) and not isinstance(raw_extend, bool):
                extend_by = int(raw_extend)
                if extend_by > 0:
                    reason = entry.get("reason", "")
                    normalized_stale_extensions.append(
                        {
                            "id": fact_id,
                            "extend_by_days": extend_by,
                            "reason": reason if isinstance(reason, str) else "",
                        }
                    )

    consolidation_raw = update_data.get("factsToConsolidate")
    normalized_consolidation: list[dict[str, Any]] = []
    if isinstance(consolidation_raw, list):
        for entry in consolidation_raw:
            if not isinstance(entry, dict):
                continue
            source_ids = entry.get("sourceIds")
            if not isinstance(source_ids, list) or not source_ids:
                continue
            clean_ids = list(dict.fromkeys(sid for sid in source_ids if isinstance(sid, str) and sid))
            if len(clean_ids) < 2:
                continue
            consolidated = entry.get("consolidated")
            if not isinstance(consolidated, dict):
                continue
            content = consolidated.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            _raw_conf = consolidated.get("confidence", 0.9)
            if isinstance(_raw_conf, bool) or not isinstance(_raw_conf, (int, float)):
                _norm_conf = 0.9
            else:
                _f = float(_raw_conf)
                _norm_conf = _f if math.isfinite(_f) else 0.9
            _raw_cat = consolidated.get("category")
            _norm_cat = _raw_cat.strip() if isinstance(_raw_cat, str) and _raw_cat.strip() else "context"
            normalized_consolidation.append(
                {
                    "sourceIds": clean_ids,
                    "consolidated": {
                        "content": content.strip(),
                        "category": _norm_cat,
                        "confidence": _norm_conf,
                    },
                }
            )

    return {
        "user": user if isinstance(user, dict) else {},
        "history": history if isinstance(history, dict) else {},
        "newFacts": normalized_new_facts,
        "factsToRemove": normalized_facts_to_remove,
        "staleFactsToRemove": normalized_stale_removals,
        "staleFactsToExtend": normalized_stale_extensions,
        "factsToConsolidate": normalized_consolidation,
    }


def _parse_memory_update_response(response_content: Any) -> dict[str, Any]:
    '''从模型响应中定位首个字段齐全且可解析的 JSON 更新对象；不尝试修补无效内容。'''
    response_text = _extract_text(response_content).strip()
    decoder = json.JSONDecoder()

    for match in re.finditer(r"\{", response_text):
        try:
            parsed, _end = decoder.raw_decode(response_text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and _REQUIRED_MEMORY_UPDATE_TOP_LEVEL_KEYS.issubset(parsed):
            return _normalize_memory_update_data(parsed)

    raise json.JSONDecodeError("No valid memory update JSON object found", response_text, 0)


_UPLOAD_SENTENCE_RE = re.compile(
    r"[^.!?]*\b(?:"
    r"upload(?:ed|ing)?(?:\s+\w+){0,3}\s+(?:file|files?|document|documents?|attachment|attachments?)"
    r"|file\s+upload"
    r"|/mnt/user-data/uploads/"
    r"|<uploaded_files>"
    r")[^.!?]*[.!?]?\s*",
    re.IGNORECASE,
)


def _strip_upload_mentions_from_memory(memory_data: dict[str, Any]) -> dict[str, Any]:
    '''从摘要和事实中移除上传事件描述，避免把仅在当前会话有效的文件写入长期记忆。'''
    for section in ("user", "history"):
        section_data = memory_data.get(section, {})
        for _key, val in section_data.items():
            if isinstance(val, dict) and "summary" in val:
                cleaned = _UPLOAD_SENTENCE_RE.sub("", val["summary"]).strip()
                cleaned = re.sub(r"  +", " ", cleaned)
                val["summary"] = cleaned

    facts = memory_data.get("facts", [])
    if facts:
        memory_data["facts"] = [f for f in facts if not _UPLOAD_SENTENCE_RE.search(f.get("content", ""))]

    return memory_data


def _fact_content_key(content: Any) -> str | None:
    '''将非空事实内容规范为不区分大小写的去重键。'''
    if not isinstance(content, str):
        return None
    stripped = content.strip()
    if not stripped:
        return None
    return stripped.casefold()




def _parse_fact_datetime(raw: str) -> datetime | None:
    '''解析事实的创建时间；无时区的值按 UTC 处理，格式错误时返回 None。'''
    if not raw:
        return None
    try:
        result = datetime.fromisoformat(raw)
        if result.tzinfo is None:
            result = result.replace(tzinfo=UTC)
        return result
    except (ValueError, TypeError):
        return None


def _effective_fact_staleness_age(fact: dict[str, Any], config: Any) -> int:
    '''优先采用事实自身的有效复核周期；缺失或无效时回退到全局默认天数。'''
    raw = fact.get("expected_valid_days")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0:
        return int(raw)
    return config.staleness_age_days


def _select_stale_candidates(
    current_memory: dict[str, Any],
    config: Any,
) -> list[dict[str, Any]]:
    '''筛出创建时间已超过各自复核周期的事实，并保留受保护类别以免自动清理用户纠正。'''
    now = datetime.now(UTC)
    protected = frozenset(config.staleness_protected_categories)
    candidates: list[dict[str, Any]] = []
    for fact in current_memory.get("facts", []):
        if not isinstance(fact, dict):
            continue
        category = fact.get("category", "")
        if isinstance(category, str) and category in protected:
            continue
        created_at = _parse_fact_datetime(fact.get("createdAt", ""))
        if created_at is None:
            continue
        effective_age = _effective_fact_staleness_age(fact, config)
        if created_at < now - timedelta(days=effective_age):
            candidates.append(fact)
    return candidates


def _build_staleness_section(
    stale_candidates: list[dict[str, Any]],
    config: Any,
) -> str:
    '''将待复核事实及其有效周期格式化为模型可处理的提示区段。'''
    if not stale_candidates:
        return ""
    lines: list[str] = []
    for fact in stale_candidates:
        fid = fact.get("id", "?")
        cat = html.escape(str(fact.get("category", "context")).strip() or "context", quote=False)
        conf = _coerce_source_confidence(fact)
        created_raw = fact.get("createdAt", "")
        created_short = created_raw[:10] if isinstance(created_raw, str) and len(created_raw) >= 10 else created_raw
        content = html.escape(str(fact.get("content", "")), quote=False)
        effective_age = _effective_fact_staleness_age(fact, config)
        lines.append(f'- [{fid} | {cat} | {conf:.2f} | {created_short} | valid:{effective_age}d] "{content}"')
    return STALENESS_REVIEW_PROMPT.format(stale_facts="\n".join(lines))




def _select_consolidation_candidates(
    current_memory: dict[str, Any],
    config: Any,
) -> dict[str, list[dict[str, Any]]]:
    '''按类别分组并筛出数量达到合并阈值的事实组，同时排除受保护类别。'''
    facts = current_memory.get("facts", [])
    if not facts:
        return {}
    by_category: dict[str, list[dict[str, Any]]] = {}
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        cat = fact.get("category", "context")
        if isinstance(cat, str) and cat.strip():
            by_category.setdefault(cat.strip(), []).append(fact)
    threshold = config.consolidation_min_facts
    protected = set(config.staleness_protected_categories)
    return {cat: group for cat, group in by_category.items() if len(group) >= threshold and cat not in protected}


def _build_consolidation_section(
    candidates: dict[str, list[dict[str, Any]]],
    max_groups: int = 3,
    max_sources: int = 8,
) -> str:
    '''按碎片数量排序并限制组数和每组事实数，生成与后续可执行范围一致的合并提示。'''
    if not candidates:
        return ""
    sorted_candidates = sorted(candidates.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    parts: list[str] = []
    for cat, group in sorted_candidates[:max_groups]:
        lines: list[str] = []
        for fact in group[:max_sources]:
            fid = fact.get("id", "?")
            conf = _coerce_source_confidence(fact)
            content = html.escape(str(fact.get("content", "")))
            lines.append(f'- [{fid} | {conf:.2f}] "{content}"')
        shown = min(len(group), max_sources)
        parts.append(f'<consolidation_candidates category="{html.escape(cat)}" count="{shown}">\n' + "\n".join(lines) + "\n</consolidation_candidates>")
    return CONSOLIDATION_PROMPT.format(consolidation_groups="\n\n".join(parts), max_groups=max_groups)


def _escape_memory_for_prompt(memory: Any) -> Any:
    '''复制记忆数据并转义所有字符串字段，防止用户内容突破提示词中的结构边界。'''
    if isinstance(memory, str):
        return html.escape(memory)
    if isinstance(memory, dict):
        return {key: _escape_memory_for_prompt(value) for key, value in memory.items()}
    if isinstance(memory, list):
        return [_escape_memory_for_prompt(item) for item in memory]
    return memory


class MemoryUpdater:
    '''协调记忆存储与模型更新流程，提供事实数据访问、校验、合并和复核能力。'''

    def __init__(self, config: DeerMemConfig, storage: MemoryStorage, llm: Any = None):
        '''接收配置、存储和模型依赖；模型缺失时仍可执行非模型类记忆操作。'''
        self._config = config
        self._storage = storage
        self._llm = llm


    def _save_memory_to_file(self, memory_data: dict[str, Any], agent_name: str | None = None, *, user_id: str | None = None) -> bool:
        '''通过注入的存储实现持久化，并返回存储层的保存结果。'''
        return self._storage.save(memory_data, agent_name, user_id=user_id)

    def get_memory_data(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        '''通过存储层读取当前记忆数据，并复用其缓存策略。'''
        return self._storage.load(agent_name, user_id=user_id)

    def reload_memory_data(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        '''要求存储层绕过缓存重新读取当前记忆数据。'''
        return self._storage.reload(agent_name, user_id=user_id)

    def import_memory_data(self, memory_data: dict[str, Any], agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        '''保存导入的记忆文档；持久化失败时抛出错误，成功后返回存储中的版本。'''
        if not self._storage.save(memory_data, agent_name, user_id=user_id):
            raise OSError("Failed to save imported memory data")
        return self._storage.load(agent_name, user_id=user_id)

    def clear_memory_data(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        '''创建空白记忆文档并持久化；保存失败时抛出错误。'''
        cleared_memory = create_empty_memory()
        if not self._save_memory_to_file(cleared_memory, agent_name, user_id=user_id):
            raise OSError("Failed to save cleared memory data")
        return cleared_memory

    def create_memory_fact(self, content: str, category: str = "context", confidence: float = 0.5, agent_name: str | None = None, *, user_id: str | None = None) -> tuple[dict[str, Any], str | None]:
        '''校验并添加手工事实，按置信度执行数量上限；若新事实被淘汰则返回空编号。'''
        normalized_content = content.strip()
        if not normalized_content:
            raise ValueError("content")
        normalized_category = category.strip() or "context"
        validated_confidence = _validate_confidence(confidence)
        now = utc_now_iso_z()
        memory_data = self.get_memory_data(agent_name, user_id=user_id)
        updated_memory = dict(memory_data)
        facts = list(memory_data.get("facts", []))
        fact_id = f"fact_{uuid.uuid4().hex[:8]}"
        facts.append(
            {
                "id": fact_id,
                "content": normalized_content,
                "category": normalized_category,
                "confidence": validated_confidence,
                "createdAt": now,
                "source": "manual",
            }
        )
        updated_memory["facts"] = _trim_facts_to_max(facts, self._config.max_facts)
        if not self._save_memory_to_file(updated_memory, agent_name, user_id=user_id):
            raise OSError("Failed to save memory data after creating fact")
        stored = any(f.get("id") == fact_id for f in updated_memory["facts"])
        return updated_memory, (fact_id if stored else None)

    def delete_memory_fact(self, fact_id: str, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        '''按事实编号删除记录并持久化；找不到目标或保存失败时报告错误。'''
        memory_data = self.get_memory_data(agent_name, user_id=user_id)
        facts = memory_data.get("facts", [])
        updated_facts = [fact for fact in facts if fact.get("id") != fact_id]
        if len(updated_facts) == len(facts):
            raise KeyError(fact_id)
        updated_memory = dict(memory_data)
        updated_memory["facts"] = updated_facts
        if not self._save_memory_to_file(updated_memory, agent_name, user_id=user_id):
            raise OSError(f"Failed to save memory data after deleting fact '{fact_id}'")
        return updated_memory

    def update_memory_fact(self, fact_id: str, content: str | None = None, category: str | None = None, confidence: float | None = None, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        '''按事实 ID 更新指定字段，并将变更后的记忆数据写回存储。'''
        memory_data = self.get_memory_data(agent_name, user_id=user_id)
        updated_memory = dict(memory_data)
        updated_facts: list[dict[str, Any]] = []
        found = False
        for fact in memory_data.get("facts", []):
            if fact.get("id") == fact_id:
                found = True
                updated_fact = dict(fact)
                if content is not None:
                    normalized_content = content.strip()
                    if not normalized_content:
                        raise ValueError("content")
                    updated_fact["content"] = normalized_content
                if category is not None:
                    updated_fact["category"] = category.strip() or "context"
                if confidence is not None:
                    updated_fact["confidence"] = _validate_confidence(confidence)
                updated_facts.append(updated_fact)
            else:
                updated_facts.append(fact)
        if not found:
            raise KeyError(fact_id)
        updated_memory["facts"] = updated_facts
        if not self._save_memory_to_file(updated_memory, agent_name, user_id=user_id):
            raise OSError(f"Failed to save memory data after updating fact '{fact_id}'")
        return updated_memory

    def _build_correction_hint(
        self,
        correction_detected: bool,
        reinforcement_detected: bool,
    ) -> str:
        '''把对话中检测到的纠正和肯定信号转换为模型更新事实时的指导文本。'''
        correction_hint = ""
        if correction_detected:
            correction_hint = (
                "IMPORTANT: Explicit correction signals were detected in this conversation. "
                "Pay special attention to what the agent got wrong, what the user corrected, "
                "and record the correct approach as a fact with category "
                '"correction" and confidence >= 0.95 when appropriate.'
            )
        if reinforcement_detected:
            reinforcement_hint = (
                "IMPORTANT: Positive reinforcement signals were detected in this conversation. "
                "The user explicitly confirmed the agent's approach was correct or helpful. "
                "Record the confirmed approach, style, or preference as a fact with category "
                '"preference" or "behavior" and confidence >= 0.9 when appropriate.'
            )
            correction_hint = (correction_hint + "\n" + reinforcement_hint).strip() if correction_hint else reinforcement_hint

        return correction_hint

    def _prepare_update_prompt(
        self,
        messages: list[Any],
        agent_name: str | None,
        correction_detected: bool,
        reinforcement_detected: bool,
        user_id: str | None = None,
    ) -> tuple[dict[str, Any], str] | None:
        '''读取当前记忆，生成对话文本，并按配置加入纠正、过期复核和事实合并提示。'''
        config = self._config
        if not messages:
            return None

        current_memory = self.get_memory_data(agent_name, user_id=user_id)
        conversation_text = format_conversation_for_update(messages)
        if not conversation_text.strip():
            return None

        correction_hint = self._build_correction_hint(
            correction_detected=correction_detected,
            reinforcement_detected=reinforcement_detected,
        )

        staleness_section = ""
        if config.staleness_review_enabled:
            stale_candidates = _select_stale_candidates(current_memory, config)
            if len(stale_candidates) >= config.staleness_min_candidates:
                staleness_section = _build_staleness_section(stale_candidates, config)

        consolidation_section = ""
        if config.consolidation_enabled:
            consolidation_candidates = _select_consolidation_candidates(current_memory, config)
            if consolidation_candidates:
                consolidation_section = _build_consolidation_section(
                    consolidation_candidates,
                    max_groups=config.consolidation_max_groups_per_cycle,
                    max_sources=config.consolidation_max_sources,
                )

        prompt = MEMORY_UPDATE_PROMPT.format(
            current_memory=json.dumps(_escape_memory_for_prompt(current_memory), indent=2, ensure_ascii=False),
            conversation=conversation_text,
            correction_hint=correction_hint,
            staleness_review_section=staleness_section,
            consolidation_section=consolidation_section,
        )
        return current_memory, prompt

    def _finalize_update(
        self,
        current_memory: dict[str, Any],
        response_content: Any,
        thread_id: str | None,
        agent_name: str | None,
        user_id: str | None = None,
    ) -> bool:
        '''解析模型更新、在副本上应用变更并清理上传事件描述，最后保存结果。'''
        update_data = _parse_memory_update_response(response_content)
        updated_memory = self._apply_updates(copy.deepcopy(current_memory), update_data, thread_id)
        updated_memory = _strip_upload_mentions_from_memory(updated_memory)
        return self._storage.save(updated_memory, agent_name, user_id=user_id)

    async def aupdate_memory(
        self,
        messages: list[Any],
        thread_id: str | None = None,
        agent_name: str | None = None,
        correction_detected: bool = False,
        reinforcement_detected: bool = False,
        user_id: str | None = None,
        trace_id: str | None = None,
    ) -> bool:
        '''将同步模型更新流程交给工作线程执行，避免在异步调用方内阻塞事件循环。'''
        return await asyncio.to_thread(
            self._do_update_memory_sync,
            messages=messages,
            thread_id=thread_id,
            agent_name=agent_name,
            correction_detected=correction_detected,
            reinforcement_detected=reinforcement_detected,
            user_id=user_id,
            trace_id=trace_id,
        )

    def _do_update_memory_sync(
        self,
        messages: list[Any],
        thread_id: str | None = None,
        agent_name: str | None = None,
        correction_detected: bool = False,
        reinforcement_detected: bool = False,
        user_id: str | None = None,
        trace_id: str | None = None,
    ) -> bool:
        '''在线程上下文中临时绑定请求追踪编号，再委托同步更新实现并恢复原上下文。'''
        cm = self._config.trace_context_manager
        if cm is not None and trace_id is not None:
            with cm(trace_id):
                return self._do_update_memory_sync_impl(
                    messages=messages,
                    thread_id=thread_id,
                    agent_name=agent_name,
                    correction_detected=correction_detected,
                    reinforcement_detected=reinforcement_detected,
                    user_id=user_id,
                    trace_id=trace_id,
                )
        return self._do_update_memory_sync_impl(
            messages=messages,
            thread_id=thread_id,
            agent_name=agent_name,
            correction_detected=correction_detected,
            reinforcement_detected=reinforcement_detected,
            user_id=user_id,
            trace_id=trace_id,
        )

    def _do_update_memory_sync_impl(
        self,
        messages: list[Any],
        thread_id: str | None = None,
        agent_name: str | None = None,
        correction_detected: bool = False,
        reinforcement_detected: bool = False,
        user_id: str | None = None,
        trace_id: str | None = None,
    ) -> bool:
        '''准备提示、调用同步模型生成记忆更新，并处理解析、追踪及持久化失败。'''
        try:
            prepared = self._prepare_update_prompt(
                messages=messages,
                agent_name=agent_name,
                correction_detected=correction_detected,
                reinforcement_detected=reinforcement_detected,
                user_id=user_id,
            )
            if prepared is None:
                return False

            current_memory, prompt = prepared
            model_name = self._config.model.model
            model = self._llm
            if model is None:
                raise RuntimeError("DeerMem memory update requested but no LLM is configured (set memory.backend_config.model in config).")
            invoke_config: dict[str, Any] = {"run_name": "memory_agent"}
            if self._config.tracing_callback is not None:
                self._config.tracing_callback(
                    invoke_config,
                    thread_id=thread_id,
                    user_id=user_id,
                    trace_id=trace_id,
                    model_name=model_name,
                )
            logger.info("Invoking memory-update LLM (thread=%s trace_id=%s)", thread_id, trace_id)
            response = model.invoke(prompt, config=invoke_config)
            return self._finalize_update(
                current_memory=current_memory,
                response_content=response.content,
                thread_id=thread_id,
                agent_name=agent_name,
                user_id=user_id,
            )
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse LLM response for memory update: %s", e)
            return False
        except Exception as e:
            logger.exception("Memory update failed: %s", e)
            return False

    def update_memory(
        self,
        messages: list[Any],
        thread_id: str | None = None,
        agent_name: str | None = None,
        correction_detected: bool = False,
        reinforcement_detected: bool = False,
        user_id: str | None = None,
        trace_id: str | None = None,
    ) -> bool:
        '''同步更新记忆；若调用方已有运行中的事件循环，则将阻塞模型请求移至线程池。'''
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            try:
                future = _SYNC_MEMORY_UPDATER_EXECUTOR.submit(
                    self._do_update_memory_sync,
                    messages=messages,
                    thread_id=thread_id,
                    agent_name=agent_name,
                    correction_detected=correction_detected,
                    reinforcement_detected=reinforcement_detected,
                    user_id=user_id,
                    trace_id=trace_id,
                )
                return future.result()
            except Exception:
                logger.exception("Failed to offload memory update to executor")
                return False

        return self._do_update_memory_sync(
            messages=messages,
            thread_id=thread_id,
            agent_name=agent_name,
            correction_detected=correction_detected,
            reinforcement_detected=reinforcement_detected,
            user_id=user_id,
            trace_id=trace_id,
        )

    def _apply_updates(
        self,
        current_memory: dict[str, Any],
        update_data: dict[str, Any],
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        '''按模型方案更新摘要和事实，处理删除、过期复核、有效期延长及事实合并。'''
        config = self._config
        now = utc_now_iso_z()

        user_updates = update_data.get("user", {})
        for section in ["workContext", "personalContext", "topOfMind"]:
            section_data = user_updates.get(section, {})
            if section_data.get("shouldUpdate") and section_data.get("summary"):
                current_memory["user"][section] = {
                    "summary": section_data["summary"],
                    "updatedAt": now,
                }

        history_updates = update_data.get("history", {})
        for section in ["recentMonths", "earlierContext", "longTermBackground"]:
            section_data = history_updates.get(section, {})
            if section_data.get("shouldUpdate") and section_data.get("summary"):
                current_memory["history"][section] = {
                    "summary": section_data["summary"],
                    "updatedAt": now,
                }

        facts_to_remove = set(update_data.get("factsToRemove", []))
        if facts_to_remove:
            current_memory["facts"] = [f for f in current_memory.get("facts", []) if f.get("id") not in facts_to_remove]

        stale_removals = update_data.get("staleFactsToRemove", [])
        stale_extensions = update_data.get("staleFactsToExtend", [])
        has_staleness_ops = (isinstance(stale_removals, list) and stale_removals) or (isinstance(stale_extensions, list) and stale_extensions)
        if has_staleness_ops:
            candidate_ids = {f["id"] for f in _select_stale_candidates(current_memory, config) if f.get("id") is not None}

            proposed_remove_ids: set[str] = set()
            if isinstance(stale_removals, list) and stale_removals:
                proposed_remove_ids = {entry["id"] for entry in stale_removals if isinstance(entry, dict) and "id" in entry}
                stale_ids_to_remove = proposed_remove_ids & candidate_ids

                if not stale_ids_to_remove:
                    stale_removals = []
                else:
                    max_stale = config.staleness_max_removals_per_cycle
                    if len(stale_ids_to_remove) > max_stale:
                        stale_facts = [f for f in current_memory.get("facts", []) if f.get("id") in stale_ids_to_remove]
                        stale_facts.sort(key=_coerce_source_confidence)
                        stale_ids_to_remove = {f["id"] for f in stale_facts[:max_stale]}

                    current_memory["facts"] = [f for f in current_memory.get("facts", []) if f.get("id") not in stale_ids_to_remove]

                for entry in stale_removals:
                    if isinstance(entry, dict) and entry.get("id") in stale_ids_to_remove:
                        logger.info(
                            "Staleness review removed fact %s: %s",
                            entry["id"],
                            entry.get("reason", "no reason provided"),
                        )

            if isinstance(stale_extensions, list) and stale_extensions:
                extendable_ids = candidate_ids - proposed_remove_ids
                ext_by_id = {e["id"]: e for e in stale_extensions if isinstance(e, dict) and isinstance(e.get("id"), str) and e["id"] in extendable_ids}
                if ext_by_id:
                    now_utc = datetime.now(UTC)
                    max_ext = config.staleness_max_extension_days
                    updated_facts: list[dict[str, Any]] = []
                    for fact in current_memory.get("facts", []):
                        fid = fact.get("id")
                        ext = ext_by_id.get(fid) if fid else None
                        if ext is not None:
                            extend_by = ext.get("extend_by_days")
                            if isinstance(extend_by, (int, float)) and not isinstance(extend_by, bool):
                                extend_by_int = int(extend_by)
                                if extend_by_int > 0:
                                    created = _parse_fact_datetime(fact.get("createdAt", ""))
                                    if created is None:
                                        updated_facts.append(fact)
                                        continue
                                    days_since = int((now_utc - created).total_seconds() // 86400)
                                    new_evd = min(days_since + extend_by_int, max_ext)
                                    fact = {**fact, "expected_valid_days": new_evd}
                                    logger.info(
                                        "Staleness review extended fact %s by %d days (new expected_valid_days: %d): %s",
                                        fid,
                                        extend_by_int,
                                        new_evd,
                                        ext.get("reason", "no reason provided"),
                                    )
                        updated_facts.append(fact)
                    current_memory["facts"] = updated_facts

        existing_fact_keys = {fact_key for fact_key in (_fact_content_key(fact.get("content")) for fact in current_memory.get("facts", [])) if fact_key is not None}
        new_facts = update_data.get("newFacts", [])
        for fact in new_facts:
            confidence = fact.get("confidence", 0.5)
            if confidence >= config.fact_confidence_threshold:
                raw_content = fact.get("content", "")
                if not isinstance(raw_content, str):
                    continue
                normalized_content = raw_content.strip()
                fact_key = _fact_content_key(normalized_content)
                if fact_key is None:
                    continue
                if fact_key in existing_fact_keys:
                    continue

                fact_entry = {
                    "id": f"fact_{uuid.uuid4().hex[:8]}",
                    "content": normalized_content,
                    "category": fact.get("category", "context"),
                    "confidence": confidence,
                    "createdAt": now,
                    "source": thread_id or "unknown",
                }
                source_error = fact.get("sourceError")
                if isinstance(source_error, str):
                    normalized_source_error = source_error.strip()
                    if normalized_source_error:
                        fact_entry["sourceError"] = normalized_source_error
                evd = fact.get("expected_valid_days")
                if isinstance(evd, int) and not isinstance(evd, bool) and evd > 0:
                    creation_cap = int(config.staleness_age_days * config.staleness_max_lifetime_multiplier)
                    fact_entry["expected_valid_days"] = min(evd, creation_cap)
                current_memory["facts"].append(fact_entry)
                if fact_key is not None:
                    existing_fact_keys.add(fact_key)

        current_memory["facts"] = _trim_facts_to_max(current_memory["facts"], config.max_facts)

        if config.consolidation_enabled:
            consolidation_decisions = update_data.get("factsToConsolidate", [])
            if isinstance(consolidation_decisions, list) and consolidation_decisions:
                fact_index = {f.get("id"): f for f in current_memory.get("facts", []) if isinstance(f, dict)}
                max_groups = config.consolidation_max_groups_per_cycle
                max_sources = config.consolidation_max_sources
                ids_consumed: set[str] = set()
                new_consolidated: list[dict[str, Any]] = []
                merge_count = 0

                allowed_source_ids = {f["id"] for group in _select_consolidation_candidates(current_memory, config).values() for f in group if f.get("id") is not None}

                for decision in consolidation_decisions:
                    if merge_count >= max_groups:
                        break

                    source_ids = decision.get("sourceIds", [])
                    consolidated = decision.get("consolidated", {})

                    if any(sid in ids_consumed or sid not in fact_index or sid not in allowed_source_ids for sid in source_ids):
                        continue
                    if not (2 <= len(source_ids) <= max_sources):
                        continue

                    content = consolidated.get("content", "")
                    if not isinstance(content, str) or not content.strip():
                        continue

                    source_confidences = [_coerce_source_confidence(fact_index[sid]) for sid in source_ids]
                    max_source_conf = max(source_confidences)

                    raw_llm_conf = consolidated.get("confidence")
                    if isinstance(raw_llm_conf, (int, float)) and not isinstance(raw_llm_conf, bool) and math.isfinite(float(raw_llm_conf)):
                        fact_confidence = min(max(0.0, min(float(raw_llm_conf), 1.0)), max_source_conf)
                    else:
                        fact_confidence = max_source_conf

                    if fact_confidence < config.fact_confidence_threshold:
                        continue

                    _fallback_dt = _parse_fact_datetime(now) or datetime.now(UTC)
                    _source_dts = [_parse_fact_datetime(fact_index[sid].get("createdAt") or "") or _fallback_dt for sid in source_ids]
                    _newest_dt = max(_source_dts)
                    source_created_at = _newest_dt.isoformat().removesuffix("+00:00") + "Z"
                    new_fact: dict[str, Any] = {
                        "id": f"fact_{uuid.uuid4().hex[:8]}",
                        "content": content.strip(),
                        "category": consolidated.get("category", "context"),
                        "confidence": fact_confidence,
                        "createdAt": source_created_at,
                        "consolidatedAt": now,
                        "source": "consolidation",
                        "consolidatedFrom": list(source_ids),
                    }
                    source_errors = list(dict.fromkeys(e for sid in source_ids if isinstance((e := fact_index[sid].get("sourceError")), str) and e.strip()))
                    if source_errors:
                        new_fact["sourceError"] = "\n".join(source_errors)

                    ids_consumed.update(source_ids)
                    new_consolidated.append(new_fact)
                    merge_count += 1
                    logger.info(
                        "Consolidation merged %d facts into: %s",
                        len(source_ids),
                        content.strip()[:80],
                    )

                if ids_consumed:
                    current_memory["facts"] = [f for f in current_memory.get("facts", []) if f.get("id") not in ids_consumed]
                    current_memory["facts"].extend(new_consolidated)

        return current_memory
