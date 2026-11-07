'''提供创建和演进自定义技能的安全管理工具。'''

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any, NoReturn
from weakref import WeakValueDictionary

from langchain.tools import tool

from deerflow.agents.lead_agent.prompt import refresh_user_skills_system_prompt_cache_async
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.skills.security_scanner import scan_skill_content
from deerflow.skills.security_static_scanner import (
    StaticFinding,
    StaticScanBlockedError,
    StaticScannerError,
    enforce_static_scan,
)
from deerflow.skills.storage import get_or_new_user_skill_storage
from deerflow.skills.storage.skill_storage import SkillStorage
from deerflow.skills.types import SKILL_MD_FILE
from deerflow.tools.sync import make_sync_tool_wrapper
from deerflow.tools.types import Runtime

logger = logging.getLogger(__name__)

_skill_locks: WeakValueDictionary[tuple[str, str], asyncio.Lock] = WeakValueDictionary()


def _get_lock(user_id: str, name: str) -> asyncio.Lock:
    '''取得指定用户和技能名称对应的异步锁。'''
    key = (user_id, name)
    lock = _skill_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _skill_locks[key] = lock
    return lock


def _get_thread_id(runtime: Runtime | None) -> str | None:
    '''从运行时中提取线程标识。'''
    if runtime is None:
        return None
    if runtime.context and runtime.context.get("thread_id"):
        return runtime.context.get("thread_id")
    return runtime.config.get("configurable", {}).get("thread_id")


def _history_record(*, action: str, file_path: str, prev_content: str | None, new_content: str | None, thread_id: str | None, scanner: dict[str, Any]) -> dict[str, Any]:
    '''创建一条记录技能文件变更前后内容的历史条目。'''
    return {
        "action": action,
        "author": "agent",
        "thread_id": thread_id,
        "file_path": file_path,
        "prev_content": prev_content,
        "new_content": new_content,
        "scanner": scanner,
    }


async def _scan_or_raise(content: str, *, executable: bool, location: str, static_findings: list[StaticFinding] | None = None) -> dict[str, Any]:
    '''扫描技能内容；安全扫描阻止时抛出异常。'''
    result = await scan_skill_content(content, executable=executable, location=location, static_findings=static_findings or [])
    if result.decision == "block":
        raise ValueError(f"安全扫描已阻止写入： {result.reason}")
    if executable and result.decision != "allow":
        raise ValueError(f"安全扫描已拒绝可执行内容： {result.reason}")
    return {"decision": result.decision, "reason": result.reason}


def _raise_static_block(error: StaticScanBlockedError) -> NoReturn:
    '''将静态扫描阻止结果转换为调用方可见的异常。'''
    payload = {
        "skill_name": error.skill_name,
        "findings": error.findings,
    }
    raise ValueError(f"{error} 发现项： {json.dumps(payload, ensure_ascii=False)}") from error


def _raise_static_scan_failure(name: str, error: StaticScannerError) -> NoReturn:
    '''将静态扫描执行失败转换为调用方可见的异常。'''
    raise ValueError(f"技能 '{name}' 的静态安全扫描失败： {error}") from error


async def _scan_static_candidate_or_raise(name: str, updates: dict[str, str], skill_storage: SkillStorage | None = None) -> list[StaticFinding]:
    '''在临时技能副本上执行静态扫描，并在失败时阻止写入。'''

    def _scan_candidate() -> list[StaticFinding]:
        '''构建候选技能目录并返回静态扫描发现项。'''
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / name
            if skill_storage is None:
                skill_dir.mkdir(parents=True)
            else:
                shutil.copytree(skill_storage.get_custom_skill_dir(name), skill_dir)
            for relative_path, content in updates.items():
                target = skill_dir / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            return enforce_static_scan(skill_dir, skill_name=name)

    try:
        return await _to_thread(_scan_candidate)
    except StaticScanBlockedError as e:
        _raise_static_block(e)
    except StaticScannerError as e:
        _raise_static_scan_failure(name, e)


async def _to_thread(func, /, *args, **kwargs):
    '''在线程中执行同步函数，避免阻塞事件循环。'''
    return await asyncio.to_thread(func, *args, **kwargs)


async def _skill_manage_impl(
    runtime: Runtime,
    action: str,
    name: str,
    content: str | None = None,
    path: str | None = None,
    find: str | None = None,
    replace: str | None = None,
    expected_count: int | None = None,
) -> str:
    '''执行自定义技能的创建、编辑、补丁和文件管理操作。'''
    name = SkillStorage.validate_skill_name(name)
    user_id = resolve_runtime_user_id(runtime)
    lock = _get_lock(user_id, name)
    thread_id = _get_thread_id(runtime)
    skill_storage = get_or_new_user_skill_storage(user_id)

    async with lock:
        if action == "create":
            if await _to_thread(skill_storage.custom_skill_exists, name):
                raise ValueError(f"自定义技能 '{name}' 已存在。")
            if content is None:
                raise ValueError("create 操作必须提供 content。")
            await _to_thread(skill_storage.validate_skill_markdown_content, name, content)
            static_findings = await _scan_static_candidate_or_raise(name, {SKILL_MD_FILE: content})
            scan = await _scan_or_raise(content, executable=False, location=f"{name}/{SKILL_MD_FILE}", static_findings=static_findings)
            scan["static_findings"] = static_findings
            await _to_thread(skill_storage.write_custom_skill, name, SKILL_MD_FILE, content)
            await _to_thread(
                skill_storage.append_history,
                name,
                _history_record(action="create", file_path=SKILL_MD_FILE, prev_content=None, new_content=content, thread_id=thread_id, scanner=scan),
            )
            await refresh_user_skills_system_prompt_cache_async(user_id)
            return f"已创建自定义技能 '{name}'。"
        if action == "edit":
            await _to_thread(skill_storage.ensure_custom_skill_is_editable, name)
            if content is None:
                raise ValueError("edit 操作必须提供 content。")
            await _to_thread(skill_storage.validate_skill_markdown_content, name, content)
            static_findings = await _scan_static_candidate_or_raise(name, {SKILL_MD_FILE: content})
            scan = await _scan_or_raise(content, executable=False, location=f"{name}/{SKILL_MD_FILE}", static_findings=static_findings)
            scan["static_findings"] = static_findings
            skill_file = skill_storage.get_custom_skill_file(name)
            prev_content = await _to_thread(skill_file.read_text, encoding="utf-8")
            await _to_thread(skill_storage.write_custom_skill, name, SKILL_MD_FILE, content)
            await _to_thread(
                skill_storage.append_history,
                name,
                _history_record(action="edit", file_path=SKILL_MD_FILE, prev_content=prev_content, new_content=content, thread_id=thread_id, scanner=scan),
            )
            await refresh_user_skills_system_prompt_cache_async(user_id)
            return f"已更新自定义技能 '{name}'。"

        if action == "patch":
            await _to_thread(skill_storage.ensure_custom_skill_is_editable, name)
            if find is None or replace is None:
                raise ValueError("patch 操作必须提供 find 和 replace。")
            skill_file = skill_storage.get_custom_skill_file(name)
            prev_content = await _to_thread(skill_file.read_text, encoding="utf-8")
            occurrences = prev_content.count(find)
            if occurrences == 0:
                raise ValueError("在 SKILL.md 中找不到补丁目标。")
            if expected_count is not None and occurrences != expected_count:
                raise ValueError(f"预期替换 {expected_count} 处，但找到 {occurrences} 处。")
            replacement_count = expected_count if expected_count is not None else 1
            new_content = prev_content.replace(find, replace, replacement_count)
            await _to_thread(skill_storage.validate_skill_markdown_content, name, new_content)
            static_findings = await _scan_static_candidate_or_raise(name, {SKILL_MD_FILE: new_content})
            scan = await _scan_or_raise(new_content, executable=False, location=f"{name}/{SKILL_MD_FILE}", static_findings=static_findings)
            scan["static_findings"] = static_findings
            await _to_thread(skill_storage.write_custom_skill, name, SKILL_MD_FILE, new_content)
            await _to_thread(
                skill_storage.append_history,
                name,
                _history_record(action="patch", file_path=SKILL_MD_FILE, prev_content=prev_content, new_content=new_content, thread_id=thread_id, scanner=scan),
            )
            await refresh_user_skills_system_prompt_cache_async(user_id)
            return f"已对自定义技能 '{name}' 应用补丁（已替换 {replacement_count} 处，找到 {occurrences} 处匹配）。"

        if action == "delete":
            await _to_thread(
                skill_storage.delete_custom_skill,
                name,
                history_meta=_history_record(
                    action="delete",
                    file_path=SKILL_MD_FILE,
                    prev_content=None,
                    new_content=None,
                    thread_id=thread_id,
                    scanner={"decision": "allow", "reason": "已请求删除。"},
                ),
            )
            await refresh_user_skills_system_prompt_cache_async(user_id)
            return f"已删除自定义技能 '{name}'。"

        if action == "write_file":
            await _to_thread(skill_storage.ensure_custom_skill_is_editable, name)
            if path is None or content is None:
                raise ValueError("write_file 操作必须提供 path 和 content。")
            target = await _to_thread(skill_storage.ensure_safe_support_path, name, path)
            exists = await _to_thread(target.exists)
            prev_content = await _to_thread(target.read_text, encoding="utf-8") if exists else None
            executable = "scripts/" in path or path.startswith("scripts/")
            static_findings = await _scan_static_candidate_or_raise(name, {path: content}, skill_storage)
            scan = await _scan_or_raise(content, executable=executable, location=f"{name}/{path}", static_findings=static_findings)
            scan["static_findings"] = static_findings
            await _to_thread(skill_storage.write_custom_skill, name, path, content)
            await _to_thread(
                skill_storage.append_history,
                name,
                _history_record(action="write_file", file_path=path, prev_content=prev_content, new_content=content, thread_id=thread_id, scanner=scan),
            )
            await refresh_user_skills_system_prompt_cache_async(user_id)
            return f"已为自定义技能 '{name}' 写入 '{path}'。"

        if action == "remove_file":
            await _to_thread(skill_storage.ensure_custom_skill_is_editable, name)
            if path is None:
                raise ValueError("remove_file 操作必须提供 path。")
            target = await _to_thread(skill_storage.ensure_safe_support_path, name, path)
            if not await _to_thread(target.exists):
                raise FileNotFoundError(f"找不到技能 '{name}' 的辅助文件 '{path}'。")
            prev_content = await _to_thread(target.read_text, encoding="utf-8")
            await _to_thread(target.unlink)
            await _to_thread(
                skill_storage.append_history,
                name,
                _history_record(action="remove_file", file_path=path, prev_content=prev_content, new_content=None, thread_id=thread_id, scanner={"decision": "allow", "reason": "已请求删除。"}),
            )
            await refresh_user_skills_system_prompt_cache_async(user_id)
            return f"已从自定义技能 '{name}' 中移除 '{path}'。"

        if await _to_thread(skill_storage.public_skill_exists, name):
            raise ValueError(f"'{name}' 为只读技能（内置或旧版共享）。如需自定义，请创建同名的个人版本。")
        raise ValueError(f"不支持的操作 '{action}'。")


@tool("skill_manage", parse_docstring=True)
async def skill_manage_tool(
    runtime: Runtime,
    action: str,
    name: str,
    content: str | None = None,
    path: str | None = None,
    find: str | None = None,
    replace: str | None = None,
    expected_count: int | None = None,
) -> str:
    '''管理 skills/custom/ 下的自定义技能，包括创建、更新、补丁应用和删除。

    Args:
        action: 操作类型，可为 create、patch、edit、delete、write_file 或 remove_file。
        name: 以连字符分隔单词的技能名称。
        content: create、edit 或 write_file 操作的新文件内容。
        path: write_file 或 remove_file 操作所涉及的辅助文件路径。
        find: patch 操作中要替换的现有文本。
        replace: patch 操作使用的新文本。
        expected_count: patch 操作可选的预期替换次数。
    '''
    return await _skill_manage_impl(
        runtime=runtime,
        action=action,
        name=name,
        content=content,
        path=path,
        find=find,
        replace=replace,
        expected_count=expected_count,
    )


skill_manage_tool.func = make_sync_tool_wrapper(_skill_manage_impl, "skill_manage")
