"""处理显式斜杠技能激活，并按当前授权状态绑定请求中的技能密钥。"""

from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import posixpath
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, override

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.runtime.secret_context import (
    _SECRETS_BINDING_AUDIT_KEY,
    _SLASH_SECRET_SOURCE_KEY,
    _SLASH_SKILL_ACTIVATION_RUN_KEY,
    ACTIVE_SECRETS_CONTEXT_KEY,
    extract_request_secrets,
)
from deerflow.skills.slash import parse_slash_skill_reference, resolve_slash_skill
from deerflow.skills.storage import get_or_new_skill_storage, get_or_new_user_skill_storage
from deerflow.skills.storage.skill_storage import SkillStorage
from deerflow.skills.types import SKILL_MD_FILE, SecretRequirement, Skill, SkillCategory
from deerflow.utils.messages import get_original_user_content_text, is_real_user_message

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig

logger = logging.getLogger(__name__)

_SLASH_SKILL_ACTIVATION_KEY = "slash_skill_activation"
_SLASH_SKILL_ACTIVATION_TARGET_ID_KEY = "slash_skill_activation_target_id"

# 这些内部键分别缓存最近一次密钥绑定审计、显式技能来源路径和本轮已处理的斜杠消息。
# 只保存路径与名称，不把密钥值放入审计；运行上下文的敏感字段由 secret_context 集中脱敏。


@dataclass(frozen=True, slots=True)
class _Activation:
    """保存一次斜杠激活所需的技能内容、路径、类别和请求剩余文本。"""

    skill_name: str
    category: str
    container_file_path: str
    skill_content: str
    content_hash: str
    remaining_text: str
    editable: bool
    required_secrets: tuple[SecretRequirement, ...] = ()


@dataclass(frozen=True, slots=True)
class _ActivationResolution:
    """表示技能激活的解析结果：成功时包含激活数据，失败时包含提示文本。"""

    activation: _Activation | None = None
    failure_message: str | None = None


def is_slash_skill_activation_reminder(message: object) -> bool:
    """判断消息是否为隐藏的斜杠技能激活上下文。"""
    return isinstance(message, HumanMessage) and bool(message.additional_kwargs.get(_SLASH_SKILL_ACTIVATION_KEY))


def _is_user_activation_target(message: object) -> bool:
    """判断消息是否是可触发技能激活的真实用户消息。"""
    return is_real_user_message(message)


class SkillActivationMiddleware(AgentMiddleware):
    """识别用户的 ``/技能名`` 命令，加载技能说明并按需绑定其请求密钥。"""

    def __init__(
        self,
        *,
        available_skills: set[str] | None = None,
        app_config: AppConfig | None = None,
        user_id: str | None = None,
    ) -> None:
        """保存可用技能白名单、配置快照和当前用户范围。"""
        super().__init__()
        self._available_skills = set(available_skills) if available_skills is not None else None
        self._app_config = app_config
        self._user_id = user_id

    def _storage(self) -> SkillStorage:
        """按用户和配置范围取得技能存储实例。"""
        if self._user_id is not None:
            return get_or_new_user_skill_storage(self._user_id, app_config=self._app_config)
        if self._app_config is not None:
            return get_or_new_skill_storage(app_config=self._app_config)
        return get_or_new_skill_storage()

    @staticmethod
    def _read_skill_content(skill_file: Path, skills_root: Path, *, storage: SkillStorage | None = None) -> str:
        """校验技能文件位于允许的存储根中，再以 UTF-8 读取 SKILL.md。"""
        if skill_file.name != SKILL_MD_FILE:
            raise ValueError(f"Expected {SKILL_MD_FILE}, got {skill_file.name}")
        # 用户级技能可能位于全局技能根之外，优先使用存储后端自己的路径校验。
        if storage is not None and hasattr(storage, "validate_skill_file_path"):
            resolved_file = storage.validate_skill_file_path(skill_file)
        else:
            resolved_file = skill_file.resolve()
            resolved_root = skills_root.resolve()
            try:
                resolved_file.relative_to(resolved_root)
            except ValueError as exc:
                raise ValueError("Resolved skill file must stay within the configured skills root.") from exc
        if not resolved_file.is_file():
            raise FileNotFoundError(resolved_file)
        return resolved_file.read_text(encoding="utf-8")

    def _resolve_activation(self, text: str) -> _ActivationResolution | None:
        """解析斜杠命令，校验技能启用和白名单，并安全加载技能说明。"""
        reference = parse_slash_skill_reference(text)
        if reference is None:
            return None

        storage = self._storage()
        skills = storage.load_skills(enabled_only=False)
        skill = next((candidate for candidate in skills if candidate.name == reference.name), None)
        if skill is None:
            return _ActivationResolution(failure_message=f"Skill `/{reference.name}` is not installed.")
        if not skill.enabled:
            return _ActivationResolution(failure_message=f"Skill `/{reference.name}` is installed but disabled. Enable it before using slash activation.")
        if self._available_skills is not None and reference.name not in self._available_skills:
            return _ActivationResolution(failure_message=f"Skill `/{reference.name}` is not available for this agent.")

        resolved = resolve_slash_skill(
            text,
            skills,
            available_skills=self._available_skills,
            container_base_path=storage.get_container_root(),
        )
        if resolved is None:
            return _ActivationResolution(failure_message=f"Skill `/{reference.name}` could not be resolved.")

        try:
            skill_content = self._read_skill_content(resolved.skill.skill_file, storage.get_skills_root_path(), storage=storage)
        except (OSError, ValueError):
            logger.exception("Failed to read slash-activated skill %s", resolved.skill.name)
            return _ActivationResolution(failure_message=f"Skill `/{reference.name}` could not be loaded safely. Please check the skill installation.")

        content_hash = hashlib.sha256(skill_content.encode("utf-8")).hexdigest()
        # 只有用户自定义技能允许被编辑。
        editable = resolved.skill.category == SkillCategory.CUSTOM
        return _ActivationResolution(
            activation=_Activation(
                skill_name=resolved.skill.name,
                category=str(resolved.skill.category),
                container_file_path=resolved.container_file_path,
                skill_content=skill_content,
                content_hash=content_hash,
                remaining_text=resolved.remaining_text,
                editable=editable,
                required_secrets=tuple(resolved.skill.required_secrets or ()),
            )
        )

    @staticmethod
    def _build_activation_reminder(activation: _Activation) -> str:
        """生成包含用户原始任务和转义技能正文的隐藏激活提示。"""
        user_request = activation.remaining_text or ("斜杠技能命令后没有附加任务。若下一步不明确，请询问用户希望如何使用该技能。")
        escaped_user_request = html.escape(user_request, quote=False)
        escaped_skill_content = html.escape(activation.skill_content, quote=False)
        escaped_skill_name = html.escape(activation.skill_name, quote=True)
        escaped_category = html.escape(activation.category, quote=True)
        escaped_path = html.escape(activation.container_file_path, quote=True)
        escaped_content_hash = html.escape(activation.content_hash, quote=True)
        editable_str = "true" if activation.editable else "false"
        return f"""<slash_skill_activation>
The user explicitly activated the `{escaped_skill_name}` skill for this turn.
Treat the task text as:
<user_request>
{escaped_user_request}
</user_request>

Follow this skill before choosing a general workflow. Load supporting resources from the same skill directory only when needed.

<skill name="{escaped_skill_name}" category="{escaped_category}" path="{escaped_path}" sha256="{escaped_content_hash}" editable="{editable_str}">
<skill_content encoding="xml-escaped">
{escaped_skill_content}
</skill_content>
</skill>
</slash_skill_activation>"""

    @staticmethod
    def _has_existing_activation_for_target(messages: list, target_index: int, target: HumanMessage) -> bool:
        """检查目标用户消息之前是否已有对应激活提示，避免重复激活。"""
        if target_index <= 0:
            return False

        if target.id:
            for previous in messages[:target_index]:
                if not is_slash_skill_activation_reminder(previous):
                    continue
                target_id = previous.additional_kwargs.get(_SLASH_SKILL_ACTIVATION_TARGET_ID_KEY)
                if target_id == target.id or previous.id == f"{target.id}__slash_activation":
                    return True

        previous = messages[target_index - 1]
        return is_slash_skill_activation_reminder(previous)

    @staticmethod
    def _activation_run_key(target: HumanMessage) -> str:
        """为本轮斜杠消息生成稳定键；优先使用消息 ID，否则摘要原始用户文本。"""
        if target.id:
            return target.id
        content = get_original_user_content_text(target.content, target.additional_kwargs)
        return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _run_context(request: ModelRequest) -> dict | None:
        """取得模型请求对应的可变运行上下文；类型不符时返回 ``None``。"""
        runtime = getattr(request, "runtime", None)
        context = getattr(runtime, "context", None)
        return context if isinstance(context, dict) else None

    @staticmethod
    def _already_activated(run_context: dict | None, run_key: str) -> bool:
        """判断同一斜杠消息是否已在运行上下文登记，覆盖提示已离开消息窗口的情况。"""
        return isinstance(run_context, dict) and run_context.get(_SLASH_SKILL_ACTIVATION_RUN_KEY) == run_key

    def _find_activation_target(self, messages: list, *, run_context: dict | None = None) -> tuple[int, HumanMessage, _ActivationResolution, str] | None:
        """从最近的真实用户消息中寻找尚未处理的技能命令并解析其目标。"""
        if not messages:
            return None

        target_index = next((idx for idx in range(len(messages) - 1, -1, -1) if _is_user_activation_target(messages[idx])), None)
        if target_index is None:
            return None

        target = messages[target_index]
        if target is None:
            return None
        if self._has_existing_activation_for_target(messages, target_index, target):
            return None
        # 激活提示只存在于单次请求覆盖中，因此需要运行上下文避免工具循环期间再次读盘和审计。
        run_key = self._activation_run_key(target)
        if self._already_activated(run_context, run_key):
            return None

        content = get_original_user_content_text(target.content, target.additional_kwargs)
        resolution = self._resolve_activation(content)
        if resolution is None:
            return None
        return target_index, target, resolution, run_key

    @staticmethod
    def _record_activation(request: ModelRequest, activation: _Activation, *, hook: str) -> None:
        """向运行日志记录激活的技能信息，不记录技能密钥值。"""
        runtime = getattr(request, "runtime", None)
        context = getattr(runtime, "context", None)
        journal = context.get("__run_journal") if isinstance(context, dict) else None
        if journal is None:
            return
        try:
            journal.record_middleware(
                "skill_activation",
                name="SkillActivationMiddleware",
                hook=hook,
                action="activate",
                changes={
                    "skill_name": activation.skill_name,
                    "category": activation.category,
                    "path": activation.container_file_path,
                    "content_hash": activation.content_hash,
                },
            )
        except Exception:
            logger.debug("Failed to record slash skill activation audit event", exc_info=True)

    def _prepare_model_request(self, request: ModelRequest, *, hook: str) -> tuple[ModelRequest | AIMessage | None, _Activation | None]:
        """完成激活提示插入和审计，并登记本轮激活键以阻止重复处理。"""
        run_context = self._run_context(request)
        target_and_resolution = self._find_activation_target(list(request.messages), run_context=run_context)
        if target_and_resolution is None:
            return None, None

        target_index, target, resolution, run_key = target_and_resolution
        if resolution.failure_message:
            return AIMessage(content=resolution.failure_message), None

        activation = resolution.activation
        if activation is None:
            return None, None

        logger.info(
            "SkillActivationMiddleware: activating slash skill %s category=%s path=%s hash=%s",
            activation.skill_name,
            activation.category,
            activation.container_file_path,
            activation.content_hash,
        )
        self._record_activation(request, activation, hook=hook)
        # 每轮只需记住最近一次激活目标；新斜杠命令会覆盖旧键，工具循环中的重复请求则被跳过。
        if run_context is not None:
            run_context[_SLASH_SKILL_ACTIVATION_RUN_KEY] = run_key
        activation_msg = self._make_activation_message(target, self._build_activation_reminder(activation))
        messages = list(request.messages)
        messages.insert(target_index, activation_msg)
        return request.override(messages=messages), activation

    def _handle_model_request(self, request: ModelRequest, *, hook: str) -> ModelRequest | AIMessage:
        """准备激活请求并刷新密钥绑定；解析失败时直接返回给模型的错误消息。"""
        prepared, activation = self._prepare_model_request(request, hook=hook)
        if isinstance(prepared, AIMessage):
            return prepared
        effective = prepared if prepared is not None else request
        self._resolve_secret_bindings(effective, activation, hook=hook)
        return effective

    def _resolve_secret_bindings(self, request: ModelRequest, activation: _Activation | None, *, hook: str) -> None:
        """每次模型调用按显式激活和线程技能上下文重算密钥集合，并只注入请求提供的值。

        线程上下文中的技能会针对实时注册表重新校验启用状态、白名单和自主读取策略；
        显式斜杠激活按用户授权保留到本轮结束。注册表读取失败时不绑定任何密钥，审计
        仅记录技能名、密钥名和缺失项，不记录密钥值。
        """
        runtime = getattr(request, "runtime", None)
        context = getattr(runtime, "context", None)
        if not isinstance(context, dict):
            return

        # 运行上下文只保存技能路径，后续从实时注册表取声明，不能由调用方伪造密钥清单。
        if activation is not None:
            context[_SLASH_SECRET_SOURCE_KEY] = {"path": activation.container_file_path}

        request_secrets = extract_request_secrets(context)
        sources: list[tuple[str, tuple[SecretRequirement, ...]]] = []
        if request_secrets:
            registry = self._load_skill_registry_by_path()
            if registry is not None:
                # 显式斜杠激活不受自主密钥读取开关限制，但仍须通过启用和白名单校验。
                slash_source = context.get(_SLASH_SECRET_SOURCE_KEY)
                slash_path = slash_source.get("path") if isinstance(slash_source, dict) else None
                slash_skill = self._resolve_registry_skill(registry, slash_path, require_autonomous=False)
                if slash_skill is not None:
                    sources.append((slash_skill.name, tuple(slash_skill.required_secrets)))
                sources.extend(self._in_context_secret_sources(request, registry))

        injected: dict[str, str] = {}
        bound_skills: set[str] = set()
        missing: dict[str, list[str]] = {}
        for skill_name, requirements in sources:
            for req in requirements:
                if req.name in request_secrets:
                    injected[req.name] = request_secrets[req.name]
                    bound_skills.add(skill_name)
                elif not req.optional:
                    missing.setdefault(skill_name, []).append(req.name)

        if injected:
            context[ACTIVE_SECRETS_CONTEXT_KEY] = injected
        else:
            context.pop(ACTIVE_SECRETS_CONTEXT_KEY, None)

        audit_state = {
            "skills": sorted(bound_skills),
            "secrets": sorted(injected),
            "missing": {name: sorted(values) for name, values in sorted(missing.items())},
        }
        previous = context.get(_SECRETS_BINDING_AUDIT_KEY)
        if previous == audit_state:
            return
        if previous is None and not injected and not missing:
            return
        context[_SECRETS_BINDING_AUDIT_KEY] = audit_state
        for skill_name, names in sorted(missing.items()):
            logger.warning(
                "Skill %s is active but required secrets are missing from the request context: %s",
                skill_name,
                ", ".join(names),
            )
        self._record_secret_binding(context, audit_state, hook=hook)

    def _load_skill_registry_by_path(self) -> dict[str, Skill] | None:
        """每次读取实时技能注册表并按规范化容器路径索引；失败时返回 ``None`` 并拒绝绑定。

        不缓存启用状态，确保管理员禁用技能后下一次模型调用立即撤销其密钥访问。
        """
        try:
            storage = self._storage()
            skills = storage.load_skills(enabled_only=False)
            container_root = storage.get_container_root()
        except Exception:
            logger.exception("Failed to load skills while resolving secret bindings")
            return None
        return {posixpath.normpath(skill.get_container_file_path(container_root)): skill for skill in skills}

    def _resolve_registry_skill(self, registry: dict[str, Skill], path: object, *, require_autonomous: bool) -> Skill | None:
        """按规范化文件路径查找可绑定技能，并校验启用、密钥声明及 Agent 白名单。

        不按名称回退，避免同名自定义技能冒用公共技能引用；线程上下文来源还需遵守
        ``secrets-autonomous``，显式斜杠激活则代表用户直接授权。
        """
        if not isinstance(path, str) or not path:
            return None
        skill = registry.get(posixpath.normpath(path))
        if skill is None or not skill.enabled or not skill.required_secrets:
            return None
        if require_autonomous and not skill.secrets_autonomous:
            return None
        if self._available_skills is not None and skill.name not in self._available_skills:
            return None
        return skill

    def _in_context_secret_sources(self, request: ModelRequest, registry: dict[str, Skill]) -> list[tuple[str, tuple[SecretRequirement, ...]]]:
        """将线程状态中的已加载技能路径解析为密钥来源，并按实时注册表逐项复核资格。"""
        state = getattr(request, "state", None) or {}
        try:
            entries = state.get("skill_context") or []
        except AttributeError:
            return []

        sources: list[tuple[str, tuple[SecretRequirement, ...]]] = []
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            skill = self._resolve_registry_skill(registry, entry.get("path"), require_autonomous=True)
            if skill is None or skill.name in seen:
                continue
            seen.add(skill.name)
            sources.append((skill.name, tuple(skill.required_secrets)))
        return sources

    @staticmethod
    def _record_secret_binding(context: dict, audit_state: dict, *, hook: str) -> None:
        """记录密钥绑定审计摘要；摘要只包含名称，不包含任何密钥值。"""
        journal = context.get("__run_journal")
        if journal is None:
            return
        try:
            journal.record_middleware(
                "skill_secrets",
                name="SkillActivationMiddleware",
                hook=hook,
                action="bind_secrets",
                changes=audit_state,
            )
        except Exception:
            logger.debug("Failed to record skill secret binding audit event", exc_info=True)

    @staticmethod
    def _make_activation_message(target: HumanMessage, activation_content: str) -> HumanMessage:
        """为激活提示创建隐藏消息，并关联原用户消息 ID 以支持去重。"""
        stable_id = target.id or str(uuid.uuid4())
        additional_kwargs = {
            "hide_from_ui": True,
            _SLASH_SKILL_ACTIVATION_KEY: True,
        }
        if target.id:
            additional_kwargs[_SLASH_SKILL_ACTIVATION_TARGET_ID_KEY] = target.id
        return HumanMessage(
            content=activation_content,
            id=f"{stable_id}__slash_activation",
            additional_kwargs=additional_kwargs,
        )

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse | AIMessage:
        """同步调用前处理斜杠激活和密钥绑定，再执行模型处理器。"""
        prepared = self._handle_model_request(request, hook="wrap_model_call")
        if isinstance(prepared, AIMessage):
            return prepared
        return handler(prepared)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse | AIMessage:
        """在线程池执行磁盘读取等同步准备工作，再异步调用模型处理器。"""
        prepared = await asyncio.to_thread(self._handle_model_request, request, hook="awrap_model_call")
        if isinstance(prepared, AIMessage):
            return prepared
        return await handler(prepared)
