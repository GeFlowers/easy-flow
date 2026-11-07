'''仅在本轮实际加载技能后应用其工具白名单，并同步约束模型绑定和工具执行。'''

from collections.abc import Awaitable, Callable, Collection
import posixpath
from typing import override

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse, ModelCallResult
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.agents.middlewares.skill_context import extract_skills
from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware
from deerflow.runtime.secret_context import _SLASH_SECRET_SOURCE_KEY, _SLASH_SKILL_ACTIVATION_RUN_KEY
from deerflow.skills.tool_policy import ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES, allowed_tool_names_for_skills
from deerflow.skills.types import Skill
from deerflow.utils.messages import is_real_user_message

_ACTIVE_SKILL_POLICY_KEY = "__active_skill_tool_policy"


class SkillToolPolicyMiddleware(AgentMiddleware):
    '''从本轮斜杠激活或成功读取的技能中取得权限，不使用历史技能目录收窄普通对话。'''

    def __init__(self, *, skills: list[Skill], skills_root: str, read_tool_names: Collection[str]):
        '''按真实技能路径建立本次代理的可用技能索引，并保存读取工具名称。'''
        super().__init__()
        self._skills = {posixpath.normpath(skill.get_container_file_path(skills_root)): skill for skill in skills if skill.enabled}
        self._skills_root = skills_root
        self._read_tool_names = tuple(read_tool_names)

    def _allowed(self, state, runtime) -> set[str] | None:
        '''收集本轮实际激活的技能并缓存到运行上下文，使摘要压缩后仍能维持本轮限制。'''
        messages = list((state or {}).get("messages") or [])
        # 循环检测追加的提醒不是新一轮用户任务。
        user_index = next((i for i in range(len(messages) - 1, -1, -1)
                           if is_real_user_message(messages[i]) and messages[i].name != "loop_warning"), None)
        context = getattr(runtime, "context", None)
        context = context if isinstance(context, dict) else {}
        run_key = context.get("run_id") or (messages[user_index].id if user_index is not None else None) or str(id(runtime))
        previous = context.get(_ACTIVE_SKILL_POLICY_KEY) or {}
        paths = set(previous.get("paths", [])) if previous.get("run_key") == run_key else set()
        slash_source = context.get(_SLASH_SECRET_SOURCE_KEY)
        current_target = SkillActivationMiddleware._activation_run_key(messages[user_index]) if user_index is not None else None
        if (current_target is not None and context.get(_SLASH_SKILL_ACTIVATION_RUN_KEY) == current_target
                and isinstance(slash_source, dict) and isinstance(slash_source.get("path"), str)):
            paths.add(posixpath.normpath(slash_source["path"]))
        # 仅识别本轮工具读取；旧轮次的 skill_context 不会延续工具限制。
        if user_index is not None:
            entries = extract_skills(messages[user_index + 1:], skills_root=self._skills_root, read_tool_names=self._read_tool_names)
            paths.update(posixpath.normpath(entry["path"]) for entry in entries)
        paths.intersection_update(self._skills)
        context[_ACTIVE_SKILL_POLICY_KEY] = {"run_key": run_key, "paths": sorted(paths)}
        allowed = allowed_tool_names_for_skills([self._skills[path] for path in sorted(paths)])
        return allowed | set(ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES) if allowed is not None else None

    def _filter(self, request: ModelRequest) -> ModelRequest:
        '''在模型绑定前移除本轮技能不允许的工具；未激活限制技能时原样放行。'''
        allowed = self._allowed(request.state, request.runtime)
        if allowed is None:
            return request
        tools = [tool for tool in request.tools if (tool.get("name") if isinstance(tool, dict) else tool.name) in allowed]
        return request.override(tools=tools)

    @override
    def before_model(self, state, runtime) -> None:
        '''在后续摘要中间件裁剪消息前记住本轮成功加载的技能权限。'''
        self._allowed(state, runtime)

    @override
    async def abefore_model(self, state, runtime) -> None:
        '''异步模型调用前保存同一套本轮技能权限，避免摘要裁剪造成权限丢失。'''
        self._allowed(state, runtime)

    def _blocked(self, request: ToolCallRequest) -> ToolMessage | None:
        '''拒绝模型绕过可见工具集合发出的越权调用，保留工具结果配对。'''
        allowed = self._allowed(request.state, request.runtime)
        name = request.tool_call.get("name", "")
        if allowed is None or name in allowed:
            return None
        return ToolMessage(content=f"Error: 当前激活技能的工具白名单不允许调用 '{name}'。",
                           tool_call_id=request.tool_call["id"], name=name, status="error")

    @override
    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]) -> ModelCallResult:
        '''同步模型调用前应用本轮技能的工具可见范围。'''
        return handler(self._filter(request))

    @override
    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]) -> ModelCallResult:
        '''异步模型调用前应用与同步调用一致的工具可见范围。'''
        return await handler(self._filter(request))

    @override
    def wrap_tool_call(self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], ToolMessage | Command]) -> ToolMessage | Command:
        '''同步工具执行前校验本轮技能权限。'''
        blocked = self._blocked(request)
        return blocked if blocked is not None else handler(request)

    @override
    async def awrap_tool_call(self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]]) -> ToolMessage | Command:
        '''异步工具执行前校验本轮技能权限。'''
        blocked = self._blocked(request)
        return blocked if blocked is not None else await handler(request)
