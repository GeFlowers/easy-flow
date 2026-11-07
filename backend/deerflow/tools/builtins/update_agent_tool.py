'''让自定义代理持久化更新自身配置和角色说明的工具。

该工具仅在现有自定义代理会话中提供。它按用户隔离写入代理目录，并先写入临时文件，
待全部文件准备完成后再替换目标文件，避免部分失败导致配置与角色说明不一致。
'''

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Annotated, Any

import yaml
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command
from pydantic import BeforeValidator

from deerflow.config.agents_config import load_agent_config, preserve_non_managed_fields, validate_agent_name
from deerflow.config.app_config import get_app_config
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.tools.types import Runtime

logger = logging.getLogger(__name__)

_NULLISH_STRINGS = frozenset({"null", "none", "undefined"})

_UNTRUSTED_CHANNELS: frozenset[str] = frozenset({"github"})


def _stage_temp(path: Path, text: str) -> Path:
    '''将文本写入同级临时文件并返回其路径。

    调用方负责在全部文件准备就绪后替换目标文件，或在失败时删除临时文件。
    '''
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    )
    try:
        fd.write(text)
        fd.flush()
        fd.close()
        return Path(fd.name)
    except BaseException:
        fd.close()
        Path(fd.name).unlink(missing_ok=True)
        raise


def _cleanup_temps(temps: list[Path]) -> None:
    '''尽力删除已暂存的临时文件。'''
    for tmp in temps:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            logger.debug("Failed to clean up temp file %s", tmp, exc_info=True)


def _is_nullish_string(value: object) -> bool:
    '''判断值是否为表示空值的字符串。'''
    return isinstance(value, str) and value.strip().lower() in _NULLISH_STRINGS


def _normalize_nullish_string(value: object) -> object:
    '''将表示空值的字符串规范化为 ``None``。'''
    return None if _is_nullish_string(value) else value


OptionalText = Annotated[str | None, BeforeValidator(_normalize_nullish_string)]
OptionalStringList = Annotated[list[str] | None, BeforeValidator(_normalize_nullish_string)]


@tool(parse_docstring=True)
def update_agent(
    runtime: Runtime,
    soul: OptionalText = None,
    description: OptionalText = None,
    skills: OptionalStringList = None,
    tool_groups: OptionalStringList = None,
    model: OptionalText = None,
) -> Command:
    '''更新自定义代理的身份、描述、技能白名单、工具组白名单或默认模型。

    仅更新明确传入的字段；省略的字段保持原值。
    ``soul`` 必须为完整的 SOUL.md 替换内容，不支持补丁语义，因此应从当前
    SOUL 内容开始修改后再传入。

    传入 ``skills=[]`` 可禁用该代理的全部技能；省略 ``skills`` 保留现有白名单。
    不要以 ``"null"``、``"none"`` 或 ``"undefined"`` 字符串表示不修改字段，
    应直接省略这些字段。

    Args:
        soul: 可选的完整 SOUL.md 替换内容。
        description: 可选的新一行描述。
        skills: 可选技能白名单；``[]`` 表示不使用技能，省略则保持原值。
        tool_groups: 可选工具组白名单；``[]`` 表示空列表，省略则保持原值。
        model: 可选模型覆盖值，必须匹配已配置的模型名称。

    Returns:
        携带描述结果的 ToolMessage 的 Command。下一轮用户输入时，主代理会使用
        新的 SOUL.md 和 config.yaml 重新构建，届时修改生效。
    '''
    tool_call_id = runtime.tool_call_id
    agent_name_raw: str | None = runtime.context.get("agent_name") if runtime.context else None
    channel_name: str | None = runtime.context.get("channel_name") if runtime.context else None

    def _err(message: str) -> Command:
        '''构造包含错误信息的工具结果命令。'''
        return Command(update={"messages": [ToolMessage(content=f"Error: {message}", tool_call_id=tool_call_id, status="error")]})

    if channel_name in _UNTRUSTED_CHANNELS:
        return _err(f"通道 {channel_name!r} 已禁用 update_agent。自我修改请求必须来自操作者信任的入口（聊天界面或超文本传输协议应用程序接口），不能来自网络钩子的转发。")

    if soul is None and description is None and skills is None and tool_groups is None and model is None:
        return _err('未提供任何字段。请至少传入 soul、description、skills、tool_groups、model 中的一项。未修改的字段应省略，不要传入 "null"、"none" 或 "undefined" 等表示空值的字符串。')

    try:
        agent_name = validate_agent_name(agent_name_raw)
    except ValueError as e:
        return _err(str(e))

    if not agent_name:
        return _err("update_agent 只能在自定义代理的聊天中使用。当前运行时上下文没有 agent_name，因此没有可更新的目标。若正在进行初始设置，请使用 setup_agent。")

    user_id = resolve_runtime_user_id(runtime)

    if model is not None and get_app_config().get_model_config(model) is None:
        return _err(f"未知模型 '{model}'。请使用 config.yaml 的 models 部分中已有的模型名称。")

    paths = get_paths()
    agent_dir = paths.user_agent_dir(user_id, agent_name)
    legacy_dir = paths.agent_dir(agent_name)
    if not (agent_dir / "config.yaml").exists() and (legacy_dir / "config.yaml").exists():
        return _err(f"代理 '{agent_name}' 仅存在于旧版共享布局中，没有归属具体用户；旧版代理只读，不能通过此工具更新。")

    try:
        existing_cfg = load_agent_config(agent_name, user_id=user_id)
    except FileNotFoundError:
        return _err(f"当前用户没有代理 '{agent_name}'。请先使用 setup_agent 创建新代理。")
    except ValueError as e:
        return _err(f"无法读取代理 '{agent_name}' 的配置： {e}")

    if existing_cfg is None:
        return _err(f"无法加载代理 '{agent_name}'。")

    updated_fields: list[str] = []

    config_data: dict[str, Any] = {"name": agent_name}
    new_description = description if description is not None else existing_cfg.description
    config_data["description"] = new_description
    if description is not None and description != existing_cfg.description:
        updated_fields.append("description")

    new_model = model if model is not None else existing_cfg.model
    if new_model is not None:
        config_data["model"] = new_model
    if model is not None and model != existing_cfg.model:
        updated_fields.append("model")

    new_tool_groups = tool_groups if tool_groups is not None else existing_cfg.tool_groups
    if new_tool_groups is not None:
        config_data["tool_groups"] = new_tool_groups
    if tool_groups is not None and tool_groups != existing_cfg.tool_groups:
        updated_fields.append("tool_groups")

    new_skills = skills if skills is not None else existing_cfg.skills
    if new_skills is not None:
        config_data["skills"] = new_skills
    if skills is not None and skills != existing_cfg.skills:
        updated_fields.append("skills")

    preserved = preserve_non_managed_fields(existing_cfg)
    for key, value in preserved.items():
        config_data.setdefault(key, value)

    config_changed = bool({"description", "model", "tool_groups", "skills"} & set(updated_fields))

    pending: list[tuple[Path, Path]] = []
    staged_temps: list[Path] = []

    try:
        agent_dir.mkdir(parents=True, exist_ok=True)

        if config_changed:
            yaml_text = yaml.dump(config_data, default_flow_style=False, allow_unicode=True, sort_keys=False)
            config_target = agent_dir / "config.yaml"
            config_tmp = _stage_temp(config_target, yaml_text)
            staged_temps.append(config_tmp)
            pending.append((config_tmp, config_target))

        if soul is not None:
            soul_target = agent_dir / "SOUL.md"
            soul_tmp = _stage_temp(soul_target, soul)
            staged_temps.append(soul_tmp)
            pending.append((soul_tmp, soul_target))
            updated_fields.append("soul")

        committed: list[Path] = []
        try:
            for tmp, target in pending:
                tmp.replace(target)
                committed.append(target)
        except Exception as e:
            _cleanup_temps([t for t, _ in pending if t not in committed])
            if committed:
                logger.error(
                    "[update_agent] Partial write for agent '%s' (user=%s): committed=%s, failed during rename: %s",
                    agent_name,
                    user_id,
                    [p.name for p in committed],
                    e,
                    exc_info=True,
                )
                return _err(f"代理 '{agent_name}' 已部分更新：已更新 {[p.name for p in committed]}，其余字段更新失败（{e}）。请重新运行 update_agent 重试剩余字段。")
            raise

    except Exception as e:
        _cleanup_temps(staged_temps)
        logger.error("[update_agent] Failed to update agent '%s' (user=%s): %s", agent_name, user_id, e, exc_info=True)
        return _err(f"更新代理 '{agent_name}' 失败： {e}")

    if not updated_fields:
        return Command(update={"messages": [ToolMessage(content=f"代理 '{agent_name}' 未发生变化。提供的值与现有配置一致。", tool_call_id=tool_call_id)]})

    logger.info("[update_agent] Updated agent '%s' (user=%s) fields: %s", agent_name, user_id, updated_fields)
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=(f"代理 '{agent_name}' 已成功更新。已修改： {', '.join(updated_fields)}。新配置将在用户下一轮对话时生效。"),
                    tool_call_id=tool_call_id,
                )
            ]
        }
    )
