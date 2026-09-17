"""消费即时通讯入站消息，并通过 Gateway 把它们分发给 DeerFlow Agent。"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import re
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from langgraph_sdk.errors import ConflictError

# 导入即注册内置策略，确保直接构造 ChannelManager 时与 Gateway 启动路径一致。
from app.channels import feishu_run_policy as _feishu_run_policy  # noqa: F401
from app.channels.commands import KNOWN_CHANNEL_COMMANDS
from app.channels.message_bus import (
    PENDING_CLARIFICATION_METADATA_KEY,
    InboundMessage,
    InboundMessageType,
    MessageBus,
    OutboundMessage,
    ResolvedAttachment,
)
from app.channels.run_policy import CHANNEL_RUN_POLICY, ChannelRunPolicy
from app.channels.store import ChannelStore
from app.gateway.csrf_middleware import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token
from app.gateway.github import run_policy as _github_run_policy  # noqa: F401
from app.gateway.internal_auth import create_internal_auth_headers
from deerflow.config.agents_config import load_agent_config
from deerflow.config.paths import make_safe_user_id
from deerflow.runtime.goal import parse_goal_command
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.skills.slash import parse_slash_skill_reference
from deerflow.skills.storage import get_or_new_skill_storage
from deerflow.skills.storage.skill_storage import SkillStorage
from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY

logger = logging.getLogger(__name__)

DEFAULT_LANGGRAPH_URL = "http://localhost:8001/api"
DEFAULT_GATEWAY_URL = "http://localhost:8001"
DEFAULT_ASSISTANT_ID = "lead_agent"
CUSTOM_AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")

# 此预算只限制主图的 LangGraph super-step。一次 ``task()`` 调度在主图中只占一个
# 工具节点步骤，子 Agent 另由 ``subagents.max_turns`` 限制，二者不能混用。
DEFAULT_RUN_CONFIG: dict[str, Any] = {"recursion_limit": 100}
DEFAULT_RUN_CONTEXT: dict[str, Any] = {
    "thinking_enabled": True,
    "is_plan_mode": False,
    "subagent_enabled": False,
}
STREAM_UPDATE_MIN_INTERVAL_SECONDS = 1.0
STREAM_UPDATE_MIN_CHARS = 60  # 累积到该字符数时无需等待时间窗口，立即刷新平台消息。
# SDK 请求使用 ``messages-tuple``，但嵌入式运行时和 LangGraph Platform 可能把
# 相同事件标记为 ``messages``，消费端必须兼容两个事件名。
STREAM_MODES = ["messages-tuple", "values"]
MESSAGE_STREAM_EVENTS = ("messages-tuple", "messages")
THREAD_BUSY_MESSAGE = "This conversation is already processing another request. Please wait for it to finish and try again."
BOUND_IDENTITY_REQUIRED_MESSAGE = "Connect this channel from DeerFlow Settings, complete the in-channel connect step, then send your message again."
BOUND_IDENTITY_UNAVAILABLE_MESSAGE = "Channel connection verification is temporarily unavailable. Please try again later or contact the DeerFlow operator."
INBOUND_DEDUPE_TTL_SECONDS = 10 * 60
INBOUND_DEDUPE_MAX_ENTRIES = 4096
# 只使用平台服务端稳定生成的消息 ID。``client_msg_id`` 等客户端 ID 在平台重投时
# 可能变化，若用其去重，恰好会漏掉需要吸收的重复投递。
INBOUND_DEDUPE_METADATA_KEYS = ("event_id", "message_id", "msg_id")

CHANNEL_CAPABILITIES = {
    "dingtalk": {"supports_streaming": False},
    "discord": {"supports_streaming": False},
    "feishu": {"supports_streaming": True},
    "github": {"supports_streaming": False},
    "slack": {"supports_streaming": False},
    "telegram": {"supports_streaming": True},
    "wechat": {"supports_streaming": False},
    "wecom": {"supports_streaming": True},
}

InboundFileReader = Callable[[dict[str, Any], httpx.AsyncClient], Awaitable[bytes | None]]

_METADATA_DROP_KEYS = frozenset({"raw_message", "ref_msg"})


def _slim_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """复制元数据并移除不应随每次流式更新重复传递的大对象。"""
    return {k: v for k, v in meta.items() if k not in _METADATA_DROP_KEYS}


INBOUND_FILE_READERS: dict[str, InboundFileReader] = {}


def register_inbound_file_reader(channel_name: str, reader: InboundFileReader) -> None:
    """为通道注册入站文件读取策略，覆盖默认 HTTP 下载方式。"""
    INBOUND_FILE_READERS[channel_name] = reader


async def _read_http_inbound_file(file_info: dict[str, Any], client: httpx.AsyncClient) -> bytes | None:
    """从可信文件元数据中的 URL 下载内容，缺少 URL 时跳过。"""
    url = file_info.get("url")
    if not isinstance(url, str) or not url:
        return None

    resp = await client.get(url)
    resp.raise_for_status()
    return resp.content


async def _read_wecom_inbound_file(file_info: dict[str, Any], client: httpx.AsyncClient) -> bytes | None:
    """下载企业微信文件，并在提供 ``aeskey`` 时完成平台侧解密。"""
    data = await _read_http_inbound_file(file_info, client)
    if data is None:
        return None

    aeskey = file_info.get("aeskey") if isinstance(file_info.get("aeskey"), str) else None
    if not aeskey:
        return data

    try:
        from aibot.crypto_utils import decrypt_file
    except Exception:
        logger.exception("[Manager] failed to import WeCom decrypt_file")
        return None

    return decrypt_file(data, aeskey)


async def _read_wechat_inbound_file(file_info: dict[str, Any], client: httpx.AsyncClient) -> bytes | None:
    """优先读取微信适配器已落盘的文件，否则回退到远端 URL。"""
    raw_path = file_info.get("path")
    if isinstance(raw_path, str) and raw_path.strip():
        try:
            return await asyncio.to_thread(Path(raw_path).read_bytes)
        except OSError:
            logger.exception("[Manager] failed to read WeChat inbound file from local path: %s", raw_path)
            return None

    full_url = file_info.get("full_url")
    if isinstance(full_url, str) and full_url.strip():
        return await _read_http_inbound_file({"url": full_url}, client)

    return None


register_inbound_file_reader("wecom", _read_wecom_inbound_file)
register_inbound_file_reader("wechat", _read_wechat_inbound_file)


class InvalidChannelSessionConfigError(ValueError):
    """表示即时通讯会话覆盖中包含无效的 Agent 配置。"""


class SlashSkillCommandResolutionError(RuntimeError):
    """表示斜杠技能命令无法在可信配置下完成解析。"""


@dataclass(frozen=True, slots=True)
class _SlashSkillCommandResolution:
    """描述斜杠输入应路由到聊天流程还是返回确定性失败。"""

    route_to_chat: bool = False
    failure_message: str | None = None


@dataclass(frozen=True, slots=True)
class _BoundIdentityRejection:
    """封装身份拒绝文本及仅供安全出站路由使用的服务端身份提示。"""

    message: str = BOUND_IDENTITY_REQUIRED_MESSAGE
    # 连接 ID 只来自服务端重新查询，绝不信任被拒绝消息自行声明的身份字段。
    outbound_connection_id: str | None = None
    # 所有者信息仅帮助通道选择正确凭据发送拒绝消息，不授予入站请求任何权限。
    outbound_owner_user_id: str | None = None


@dataclass(slots=True)
class _SerializedThreadRunState:
    """维护需要串行处理同一线程回合的锁及等待者计数。"""

    lock: asyncio.Lock
    waiters: int = 0


def _is_thread_busy_error(exc: BaseException | None) -> bool:
    """兼容 SDK 冲突异常与旧运行时文本，识别同线程运行冲突。"""
    if exc is None:
        return False
    if isinstance(exc, ConflictError):
        return True
    return "already running a task" in str(exc)


def _as_dict(value: Any) -> dict[str, Any]:
    """只接受映射型配置层，并复制为可安全合并的普通字典。"""
    return dict(value) if isinstance(value, Mapping) else {}


def _merge_dicts(*layers: Any) -> dict[str, Any]:
    """按参数顺序叠加映射配置，使后层覆盖前层。"""
    merged: dict[str, Any] = {}
    for layer in layers:
        if isinstance(layer, Mapping):
            merged.update(layer)
    return merged


def _normalize_custom_agent_name(raw_value: str) -> str:
    """把旧通道 assistant ID 规范化为合法的自定义 Agent 名称。"""
    normalized = raw_value.strip().lower().replace("_", "-")
    if not normalized:
        raise InvalidChannelSessionConfigError("Channel session assistant_id is empty. Use 'lead_agent' or a valid custom agent name.")
    if not CUSTOM_AGENT_NAME_PATTERN.fullmatch(normalized):
        raise InvalidChannelSessionConfigError(f"Invalid channel session assistant_id {raw_value!r}. Use 'lead_agent' or a custom agent name containing only letters, digits, and hyphens.")
    return normalized


def _extract_response_text(result: dict | list) -> str:
    """从 LangGraph ``runs.wait`` 最终状态提取本轮可展示文本。

    搜索边界止于最近一条真实用户消息，避免误取上轮回答；如果本轮通过
    ``ask_clarification`` 中断，则工具消息中的问题优先作为回复。
    """
    if isinstance(result, list):
        messages = result
    elif isinstance(result, dict):
        messages = result.get("messages", [])
    else:
        return ""

    # 逆序搜索能优先拿到最终回答，但必须在当前回合边界停止。
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue

        msg_type = msg.get("type")

        # 隐藏控制消息不是真实回合边界，不能阻止继续查找当前用户输入。
        if msg_type == "human":
            if _is_hidden_human_control_message(msg):
                continue
            break

        # 澄清中断没有普通最终 AI 文本，问题内容保存在工具消息中。
        if msg_type == "tool" and msg.get("name") == "ask_clarification":
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                return content

        if msg_type == "ai":
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                return content
            # 兼容提供商返回的多内容块消息，而非假定 content 永远是字符串。
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        parts.append(block)
                text = "".join(parts)
                if text:
                    return text
    return ""


def _messages_from_result(result: dict | list) -> list[Any]:
    """统一提取最终状态或直接消息列表中的 ``messages``。"""
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        messages = result.get("messages", [])
        if isinstance(messages, list):
            return messages
    return []


def _current_turn_messages(result: dict | list) -> list[dict[str, Any]]:
    """截取最近一条用户消息之后的当前回合消息，并恢复原始顺序。"""
    messages = _messages_from_result(result)
    current_turn: list[dict[str, Any]] = []
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        if msg.get("type") == "human":
            break
        current_turn.append(msg)
    current_turn.reverse()
    return current_turn


def _has_current_turn_clarification(result: dict | list) -> bool:
    """仅在本轮最终可见结果为澄清工具消息时返回真。"""
    for msg in reversed(_current_turn_messages(result)):
        msg_type = msg.get("type")
        if msg_type == "tool":
            return msg.get("name") == "ask_clarification"
        if msg_type == "ai":
            content = msg.get("content")
            if isinstance(content, str):
                if content:
                    return False
            elif content:
                return False
            if msg.get("tool_calls"):
                return False
    return False


def _response_metadata(base_metadata: dict[str, Any], *, pending_clarification: bool = False) -> dict[str, Any]:
    """构造适合重复出站的精简元数据，并标记待回复澄清状态。"""
    metadata = _slim_metadata(base_metadata)
    if pending_clarification:
        metadata[PENDING_CLARIFICATION_METADATA_KEY] = True
    return metadata


def _thread_channel_metadata(msg: InboundMessage) -> dict[str, Any]:
    """生成写入 DeerFlow 线程的稳定通道来源元数据。"""
    channel_source: dict[str, Any] = {
        "type": "im_channel",
        "provider": msg.channel_name,
        "chat_id": msg.chat_id,
    }
    if msg.topic_id:
        channel_source["topic_id"] = msg.topic_id
    if msg.thread_ts:
        channel_source["thread_ts"] = msg.thread_ts
    if msg.connection_id:
        channel_source["connection_id"] = msg.connection_id

    return {"channel_source": channel_source}


def _extract_text_content(content: Any) -> str:
    """从多种流式载荷形状中提取可展示文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
                else:
                    nested = block.get("content")
                    if isinstance(nested, str):
                        parts.append(nested)
        return "".join(parts)
    if isinstance(content, Mapping):
        for key in ("text", "content"):
            value = content.get(key)
            if isinstance(value, str):
                return value
    return ""


def _merge_stream_text(existing: str, chunk: str) -> str:
    """把增量文本或累计快照合并为最新完整文本。"""
    if not chunk:
        return existing
    if not existing:
        return chunk
    # 更长且以前缀包含旧文本的载荷是累计快照，可直接替换。
    if len(chunk) > len(existing) and chunk.startswith(existing):
        return chunk
    # 其余载荷按增量追加，即使内容恰好等于已有后缀也不能去重，例如中文“谢”+
    # “谢”。``values`` 快照由另一分支处理，因此这里的相同文本仍代表新 token。
    return existing + chunk


def _extract_stream_message_id(payload: Any, metadata: Any) -> str | None:
    """兼容不同 SDK 载荷形状，尽力提取流式 AI 消息 ID。"""
    candidates = [payload, metadata]
    if isinstance(payload, Mapping):
        candidates.append(payload.get("kwargs"))

    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        for key in ("id", "message_id"):
            value = candidate.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _accumulate_stream_text(
    buffers: dict[str, str],
    current_message_id: str | None,
    event_data: Any,
) -> tuple[str | None, str | None]:
    """按消息 ID 累积 ``messages-tuple`` 事件并返回最新可展示文本。"""
    payload = event_data
    metadata: Any = None
    if isinstance(event_data, (list, tuple)):
        if event_data:
            payload = event_data[0]
        if len(event_data) > 1:
            metadata = event_data[1]

    if isinstance(payload, str):
        message_id = current_message_id or "__default__"
        buffers[message_id] = _merge_stream_text(buffers.get(message_id, ""), payload)
        return buffers[message_id], message_id

    if not isinstance(payload, Mapping):
        return None, current_message_id

    payload_type = str(payload.get("type", "")).lower()
    if "tool" in payload_type:
        return None, current_message_id

    text = _extract_text_content(payload.get("content"))
    if not text and isinstance(payload.get("kwargs"), Mapping):
        text = _extract_text_content(payload["kwargs"].get("content"))
    if not text:
        return None, current_message_id

    message_id = _extract_stream_message_id(payload, metadata) or current_message_id or "__default__"
    buffers[message_id] = _merge_stream_text(buffers.get(message_id, ""), text)
    return buffers[message_id], message_id


def _extract_artifacts(result: dict | list) -> list[str]:
    """只提取最近一个 AI 回合通过 ``present_files`` 发布的产物。

    线程级 ``artifacts`` 状态包含历史全部产物，直接读取会在后续回合重复发送旧文件。
    因此这里只检查最近真实用户消息之后的工具调用。
    """
    if isinstance(result, list):
        messages = result
    elif isinstance(result, dict):
        messages = result.get("messages", [])
    else:
        return []

    artifacts: list[str] = []
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        # 隐藏控制消息不划分用户回合，遇到真实用户消息才停止。
        if msg.get("type") == "human":
            if _is_hidden_human_control_message(msg):
                continue
            break
        # 产物以 AI 发起的 present_files 工具调用为权威发布记录。
        if msg.get("type") == "ai":
            for tc in msg.get("tool_calls", []):
                if isinstance(tc, dict) and tc.get("name") == "present_files":
                    args = tc.get("args", {})
                    paths = args.get("filepaths", [])
                    if isinstance(paths, list):
                        artifacts.extend(p for p in paths if isinstance(p, str))
    return artifacts


def _is_hidden_human_control_message(msg: Mapping[str, Any]) -> bool:
    """判断 human 消息是否为不应划分真实回合的内部控制消息。"""
    if msg.get("type") != "human":
        return False

    additional_kwargs = msg.get("additional_kwargs")
    if not isinstance(additional_kwargs, Mapping):
        return False

    return additional_kwargs.get("hide_from_ui") is True


def _format_artifact_text(artifacts: list[str]) -> str:
    """把产物路径转换为仅展示文件名的用户可读文本。"""
    import posixpath

    filenames = [posixpath.basename(p) for p in artifacts]
    if len(filenames) == 1:
        return f"Created File: 📎 {filenames[0]}"
    return "Created Files: 📎 " + "、".join(filenames)


_OUTPUTS_VIRTUAL_PREFIX = "/mnt/user-data/outputs/"


def _unknown_command_reply(command: str | None = None) -> str:
    """构造包含当前权威命令集合的未知命令提示。"""
    available = " | ".join(sorted(KNOWN_CHANNEL_COMMANDS))
    if command:
        return f"Unknown command: /{command}. Available commands: {available}"
    return f"Unknown command. Available commands: {available}"


def _human_input_message(content: str, *, original_content: str | None = None) -> dict[str, Any]:
    """构造用户消息，并在注入文件上下文后保留原始用户文本。"""
    message: dict[str, Any] = {"role": "human", "content": content}
    if original_content is not None and original_content != content:
        message["additional_kwargs"] = {ORIGINAL_USER_CONTENT_KEY: original_content}
    return message


def _auth_disabled_owner_user_id() -> str | None:
    """在关闭认证的部署中解析统一的服务端所有者 ID。"""
    try:
        from app.gateway.auth_disabled import AUTH_DISABLED_USER_ID, is_auth_disabled
    except Exception:
        logger.debug("Unable to inspect auth-disabled mode for channel owner fallback", exc_info=True)
        return None
    return AUTH_DISABLED_USER_ID if is_auth_disabled() else None


def _effective_owner_user_id(msg: InboundMessage) -> str | None:
    """解析当前部署模式下真正用于资源归属的 DeerFlow 用户。"""
    return _auth_disabled_owner_user_id() or msg.owner_user_id


def _apply_effective_owner(msg: InboundMessage) -> InboundMessage:
    """把服务端解析的有效所有者写回消息，避免后续阶段重复分叉。"""
    owner_user_id = _effective_owner_user_id(msg)
    if owner_user_id:
        msg.owner_user_id = owner_user_id
    return msg


def _owner_headers(msg: InboundMessage) -> dict[str, str] | None:
    """为绑定用户的内部 Gateway 请求生成所有者认证头。"""
    owner_user_id = _effective_owner_user_id(msg)
    if not owner_user_id:
        return None
    return create_internal_auth_headers(owner_user_id=owner_user_id)


def _safe_user_id_for_run(raw_user_id: str) -> str:
    """准备文件系统安全的运行用户目录，并在准备失败时确定性降级。"""
    from deerflow.config.paths import get_paths

    try:
        return get_paths().prepare_user_dir_for_raw_id(raw_user_id)
    except Exception:
        logger.exception("Failed to prepare channel run user directory")
        return make_safe_user_id(raw_user_id)


def _channel_storage_user_id(msg: InboundMessage) -> str | None:
    """解析通道消息在文件系统中使用的规范 DeerFlow 用户 ID。

    该结果同时用于 Agent 运行身份和上传/产物存储桶，确保 Agent 读取的目录与通道
    暂存文件的位置一致。优先使用绑定的 DeerFlow 所有者，否则回退到净化后的平台
    用户 ID；两者都不存在时才交由调用方使用上下文默认用户。

    本函数面向进程内文件系统，因此返回已净化 ID；``_owner_headers`` 则故意发送
    原始所有者 ID，让 Gateway 在 HTTP 信任边界内重新解析，两者职责不同。
    """
    owner_user_id = _effective_owner_user_id(msg)
    if owner_user_id:
        return _safe_user_id_for_run(owner_user_id)
    if msg.user_id:
        return _safe_user_id_for_run(msg.user_id)
    return None


def _resolve_slash_skill_command(
    text: str,
    available_skills: set[str] | None = None,
    storage: SkillStorage | Callable[[], SkillStorage] | None = None,
) -> _SlashSkillCommandResolution | None:
    """验证斜杠技能引用是否已安装、启用且对当前 Agent 可用。"""
    reference = parse_slash_skill_reference(text)
    if reference is None:
        return None
    try:
        resolved_storage = storage() if callable(storage) else storage or get_or_new_skill_storage()
        skills = resolved_storage.load_skills(enabled_only=False)

        skill = next((candidate for candidate in skills if candidate.name == reference.name), None)
        if skill is None:
            return None
        if not skill.enabled:
            return _SlashSkillCommandResolution(failure_message=f"Skill `/{reference.name}` is installed but disabled. Enable it before using slash activation.")
        if available_skills is not None and reference.name not in available_skills:
            return _SlashSkillCommandResolution(failure_message=f"Skill `/{reference.name}` is not available for this agent.")

        return _SlashSkillCommandResolution(route_to_chat=True)
    except Exception as exc:
        logger.exception("[Manager] failed to resolve slash skill command")
        raise SlashSkillCommandResolutionError("Failed to resolve slash skill command. Please check the skill configuration.") from exc


def _resolve_attachments(thread_id: str, artifacts: list[str], *, user_id: str | None = None) -> list[ResolvedAttachment]:
    """把允许的虚拟产物路径解析为可上传的宿主机附件。

    只接受 ``/mnt/user-data/outputs/`` 下的文件，阻止借即时通讯通道外传 uploads
    或 workspace 内容。缺失、无效或越界路径会被跳过并记录告警。
    """
    from deerflow.config.paths import get_paths

    attachments: list[ResolvedAttachment] = []
    paths = get_paths()
    effective_user_id = user_id or get_effective_user_id()
    outputs_dir = paths.sandbox_outputs_dir(thread_id, user_id=effective_user_id).resolve()
    for virtual_path in artifacts:
        # 前缀白名单先拒绝明显不属于 Agent 输出目录的路径。
        if not virtual_path.startswith(_OUTPUTS_VIRTUAL_PREFIX):
            logger.warning("[Manager] rejected non-outputs artifact path: %s", virtual_path)
            continue
        try:
            actual = paths.resolve_virtual_path(thread_id, virtual_path, user_id=effective_user_id)
            # 解析后再次校验真实路径，抵御通过 ``..`` 或符号链接绕过前缀检查。
            try:
                actual.resolve().relative_to(outputs_dir)
            except ValueError:
                logger.warning("[Manager] artifact path escapes outputs dir: %s -> %s", virtual_path, actual)
                continue
            if not actual.is_file():
                logger.warning("[Manager] artifact not found on disk: %s -> %s", virtual_path, actual)
                continue
            mime, _ = mimetypes.guess_type(str(actual))
            mime = mime or "application/octet-stream"
            attachments.append(
                ResolvedAttachment(
                    virtual_path=virtual_path,
                    actual_path=actual,
                    filename=actual.name,
                    mime_type=mime,
                    size=actual.stat().st_size,
                    is_image=mime.startswith("image/"),
                )
            )
        except (ValueError, OSError) as exc:
            logger.warning("[Manager] failed to resolve artifact %s: %s", virtual_path, exc)
    return attachments


def _prepare_artifact_delivery(
    thread_id: str,
    response_text: str,
    artifacts: list[str],
    *,
    user_id: str | None = None,
) -> tuple[str, list[ResolvedAttachment]]:
    """解析产物附件，并在文本中保留可发现的文件名后备提示。"""
    attachments: list[ResolvedAttachment] = []
    if not artifacts:
        return response_text, attachments

    attachments = _resolve_attachments(thread_id, artifacts, user_id=user_id)
    resolved_virtuals = {attachment.virtual_path for attachment in attachments}
    unresolved = [path for path in artifacts if path not in resolved_virtuals]

    if unresolved:
        artifact_text = _format_artifact_text(unresolved)
        response_text = (response_text + "\n\n" + artifact_text) if response_text else artifact_text

    # 即使平台跳过或上传失败，文本中的文件名仍让用户知道本轮产生了哪些文件。
    if attachments:
        resolved_text = _format_artifact_text([attachment.virtual_path for attachment in attachments])
        response_text = (response_text + "\n\n" + resolved_text) if response_text else resolved_text

    return response_text, attachments


async def _ingest_inbound_files(thread_id: str, msg: InboundMessage, *, user_id: str | None = None) -> list[dict[str, Any]]:
    """读取并安全写入本轮入站附件，返回供模型注入的文件描述。"""
    if not msg.files:
        return []

    from deerflow.uploads.manager import (
        UnsafeUploadPathError,
        claim_unique_filename,
        ensure_uploads_dir,
        normalize_filename,
        write_upload_file_no_symlink,
    )

    def _prepare_uploads_dir() -> tuple[Path, set[str]]:
        """在线程池中创建上传目录，并取得用于冲突消解的已有文件名。"""
        # mkdir 与目录枚举都是阻塞文件系统操作，不能占用 ChannelManager 事件循环。
        target = ensure_uploads_dir(thread_id, user_id=user_id)
        existing = {entry.name for entry in target.iterdir() if entry.is_file()}
        return target, existing

    uploads_dir, seen_names = await asyncio.to_thread(_prepare_uploads_dir)

    created: list[dict[str, Any]] = []
    file_reader = INBOUND_FILE_READERS.get(msg.channel_name, _read_http_inbound_file)
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
        for idx, f in enumerate(msg.files):
            if not isinstance(f, dict):
                continue

            ftype = f.get("type") if isinstance(f.get("type"), str) else "file"
            filename = f.get("filename") if isinstance(f.get("filename"), str) else ""

            try:
                data = await file_reader(f, client)
            except Exception:
                logger.exception(
                    "[Manager] failed to read inbound file: channel=%s, file=%s",
                    msg.channel_name,
                    f.get("url") or filename or idx,
                )
                continue

            if data is None:
                logger.warning(
                    "[Manager] inbound file reader returned no data: channel=%s, file=%s",
                    msg.channel_name,
                    f.get("url") or filename or idx,
                )
                continue

            if not filename:
                ext = ".bin"
                if ftype == "image":
                    ext = ".png"
                filename = f"{msg.thread_ts or 'msg'}_{idx}{ext}"

            try:
                safe_name = claim_unique_filename(normalize_filename(filename), seen_names)
            except ValueError:
                logger.warning(
                    "[Manager] skipping inbound file with unsafe filename: channel=%s, file=%r",
                    msg.channel_name,
                    filename,
                )
                continue

            dest = uploads_dir / safe_name
            try:
                dest = await asyncio.to_thread(write_upload_file_no_symlink, uploads_dir, safe_name, data)
            except UnsafeUploadPathError:
                logger.warning("[Manager] skipping inbound file with unsafe destination: %s", safe_name)
                continue
            except Exception:
                logger.exception("[Manager] failed to write inbound file: %s", dest)
                continue

            created.append(
                {
                    "filename": safe_name,
                    "size": len(data),
                    "path": f"/mnt/user-data/uploads/{safe_name}",
                    "is_image": ftype == "image",
                }
            )

    return created


def _format_uploaded_files_block(files: list[dict[str, Any]]) -> str:
    """生成受信任的上传文件上下文块，指导模型选择对应读取工具。"""
    lines = [
        "<uploaded_files>",
        "The following files were uploaded in this message:",
        "",
    ]
    if not files:
        lines.append("(empty)")
    else:
        for f in files:
            filename = f.get("filename", "")
            size = int(f.get("size") or 0)
            size_kb = size / 1024 if size else 0
            size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
            path = f.get("path", "")
            is_image = bool(f.get("is_image"))
            file_kind = "image" if is_image else "file"
            lines.append(f"- {filename} ({size_str})")
            lines.append(f"  Type: {file_kind}")
            lines.append(f"  Path: {path}")
            lines.append("")
    lines.append("Use `read_file` for text-based files and documents.")
    lines.append("Use `view_image` for image files (jpg, jpeg, png, webp) so the model can inspect the image content.")
    lines.append("</uploaded_files>")
    return "\n".join(lines)


class ChannelManager:
    """在即时通讯通道和 DeerFlow Agent 之间执行统一调度。

    管理器消费 ``MessageBus`` 入站队列，通过 Gateway 的 LangGraph-compatible API
    创建或复用线程，并依据通道能力选择 ``runs.wait``、``runs.stream`` 或
    ``runs.create``，最后把标准化回复发布回消息总线。
    """

    def __init__(
        self,
        bus: MessageBus,
        store: ChannelStore,
        *,
        max_concurrency: int = 5,
        langgraph_url: str = DEFAULT_LANGGRAPH_URL,
        gateway_url: str = DEFAULT_GATEWAY_URL,
        assistant_id: str = DEFAULT_ASSISTANT_ID,
        default_session: dict[str, Any] | None = None,
        channel_sessions: dict[str, Any] | None = None,
        connection_repo: Any | None = None,
        require_bound_identity: bool = False,
    ) -> None:
        """初始化调度依赖、并发边界、身份策略与惰性客户端状态。"""
        self.bus = bus
        self.store = store
        self._max_concurrency = max_concurrency
        self._langgraph_url = langgraph_url
        self._gateway_url = gateway_url
        self._assistant_id = assistant_id
        self._default_session = _as_dict(default_session)
        self._channel_sessions = dict(channel_sessions or {})
        self._connection_repo = connection_repo
        self._require_bound_identity = require_bound_identity
        self._client = None  # langgraph_sdk 异步客户端仅在首次运行时创建。
        self._channel_metadata_synced: set[str] = set()
        # 创建锁按平台会话划分，防止同一会话的并发首条消息各自创建线程。
        self._thread_create_locks: dict[tuple[str, str, str | None], asyncio.Lock] = {}
        # 运行锁按 DeerFlow 线程划分，只为明确要求排队的通道串行化回合。
        self._serialized_thread_runs: dict[tuple[str, str], _SerializedThreadRunState] = {}
        self._skill_storage: SkillStorage | None = None
        self._csrf_token = generate_csrf_token()
        self._semaphore: asyncio.Semaphore | None = None
        self._running = False
        self._task: asyncio.Task | None = None
        # 键不会重新插入，因此 OrderedDict 的顺序即时间顺序，可从头部 O(k) 淘汰
        # 过期项，无需每条入站消息都扫描整个去重窗口。
        self._recent_inbound_events: OrderedDict[tuple[str, str, str, str], float] = OrderedDict()

    @staticmethod
    def _channel_supports_streaming(channel_name: str) -> bool:
        """优先读取运行中通道的动态能力，否则使用静态能力表。"""
        from .service import get_channel_service

        service = get_channel_service()
        if service:
            channel = service.get_channel(channel_name)
            if channel is not None:
                return channel.supports_streaming
        return CHANNEL_CAPABILITIES.get(channel_name, {}).get("supports_streaming", False)

    def _resolve_session_layer(self, msg: InboundMessage) -> tuple[dict[str, Any], dict[str, Any]]:
        """解析通道级和平台用户级会话覆盖层。"""
        channel_layer = _as_dict(self._channel_sessions.get(msg.channel_name))
        users_layer = _as_dict(channel_layer.get("users"))
        user_layer = _as_dict(users_layer.get(msg.user_id))
        return channel_layer, user_layer

    def _begin_serialized_thread_run(
        self,
        *,
        channel_name: str,
        thread_id: str,
    ) -> tuple[_SerializedThreadRunState | None, bool]:
        """为要求同线程排队的通道登记等待者，并返回是否已存在运行。"""
        policy = CHANNEL_RUN_POLICY.get(channel_name)
        if policy is None or not policy.serialize_thread_runs:
            return None, False

        key = (channel_name, thread_id)
        state = self._serialized_thread_runs.get(key)
        if state is None:
            state = _SerializedThreadRunState(lock=asyncio.Lock())
            self._serialized_thread_runs[key] = state
        queued = state.lock.locked()
        state.waiters += 1
        return state, queued

    def _finish_serialized_thread_run(
        self,
        *,
        channel_name: str,
        thread_id: str,
        state: _SerializedThreadRunState | None,
        lock_acquired: bool,
    ) -> None:
        """释放已获取的线程锁，并在无等待者时清理锁注册项。"""
        if state is None:
            return

        if lock_acquired:
            state.lock.release()
        state.waiters -= 1
        if state.waiters == 0 and not state.lock.locked():
            self._serialized_thread_runs.pop((channel_name, thread_id), None)

    async def _publish_progress_update(self, msg: InboundMessage, thread_id: str, text: str) -> None:
        """发布绑定到原始平台消息的非最终进度更新。"""
        await self.bus.publish_outbound(
            OutboundMessage(
                channel_name=msg.channel_name,
                chat_id=msg.chat_id,
                thread_id=thread_id,
                text=text,
                is_final=False,
                thread_ts=msg.thread_ts,
                connection_id=msg.connection_id,
                owner_user_id=msg.owner_user_id,
                metadata=_response_metadata(msg.metadata),
            )
        )

    def _resolve_run_params(self, msg: InboundMessage, thread_id: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
        """按默认、通道、用户和单消息优先级构造 Agent 运行参数。"""
        channel_layer, user_layer = self._resolve_session_layer(msg)

        # 单消息 Agent 覆盖支持 GitHub 等场景把同一事件分发给多个 Agent，并保持与
        # 通道级、用户级 assistant_id 相同的解析语义。
        message_assistant_id: str | None = None
        msg_metadata = msg.metadata if isinstance(msg.metadata, dict) else {}
        meta_assistant_id = msg_metadata.get("assistant_id") or msg_metadata.get("agent_name")
        if isinstance(meta_assistant_id, str) and meta_assistant_id.strip():
            message_assistant_id = meta_assistant_id

        assistant_id = message_assistant_id or user_layer.get("assistant_id") or channel_layer.get("assistant_id") or self._default_session.get("assistant_id") or self._assistant_id
        if not isinstance(assistant_id, str) or not assistant_id.strip():
            assistant_id = self._assistant_id

        run_config = _merge_dicts(
            DEFAULT_RUN_CONFIG,
            self._default_session.get("config"),
            channel_layer.get("config"),
            user_layer.get("config"),
        )

        configurable = run_config.get("configurable")
        if isinstance(configurable, Mapping):
            configurable = dict(configurable)
        else:
            configurable = {}
        run_config["configurable"] = configurable
        # 通道回合固定在根图命名空间，后续消息才能从同一会话 checkpoint 延续。
        configurable["checkpoint_ns"] = ""
        configurable["thread_id"] = thread_id

        # ``user_id`` 控制 DeerFlow 记忆、文件和线程桶；原始平台用户另存为
        # ``channel_user_id``，仅用于平台查询和审计。
        run_context_identity: dict[str, Any] = {"thread_id": thread_id}
        # 图内根据 ``channel_name`` 收窄工具暴露范围；Webhook 等外部输入不能获得
        # ``update_agent`` 一类管理能力。
        run_context_identity["channel_name"] = msg.channel_name
        # 运行与文件共用同一身份解析函数，防止 Agent 所见目录和通道暂存目录分离。
        run_user_id = _channel_storage_user_id(msg)
        if run_user_id:
            run_context_identity["user_id"] = run_user_id
        if msg.user_id:
            run_context_identity["channel_user_id"] = msg.user_id

        run_context = _merge_dicts(
            DEFAULT_RUN_CONTEXT,
            self._default_session.get("context"),
            channel_layer.get("context"),
            user_layer.get("context"),
            run_context_identity,
        )

        # 自定义 Agent 实际由 lead_agent 配合 agent_name 上下文实现；这里兼容旧的
        # ``assistant_id: <custom-agent-name>`` 通道配置。
        if assistant_id != DEFAULT_ASSISTANT_ID:
            run_context.setdefault("agent_name", _normalize_custom_agent_name(assistant_id))
            assistant_id = DEFAULT_ASSISTANT_ID

        # 通道差异由注册表驱动，避免为每个 Webhook 平台新增硬编码分支。
        policy = CHANNEL_RUN_POLICY.get(msg.channel_name)
        if policy is not None and policy.default_recursion_limit is not None:
            # 单消息显式上限代表操作者的安全选择，即使低于通道默认值也必须原样采用；
            # 只有未显式覆盖时，通道默认值才作为会话配置的下限。
            channel_meta = (msg.metadata or {}).get(msg.channel_name, {})
            override = channel_meta.get("recursion_limit") if isinstance(channel_meta, dict) else None
            if isinstance(override, int) and override > 0:
                run_config["recursion_limit"] = override
            else:
                run_config["recursion_limit"] = max(run_config.get("recursion_limit", 100), policy.default_recursion_limit)

        return assistant_id, run_config, run_context

    async def _apply_channel_policy(self, msg: InboundMessage, run_context: dict[str, Any]) -> ChannelRunPolicy | None:
        """在 Agent 启动前应用需要访问 ``run_context`` 的通道策略。

        非交互通道会禁止同步澄清，避免 Webhook 运行等待只能由下一次独立投递提供的
        回复；凭据提供器则可注入按需签发的平台令牌。递归上限属于 ``run_config``，
        已由 ``_resolve_run_params`` 处理。返回策略供后续直接判断
        ``fire_and_forget``，避免重复查表。
        """
        policy = CHANNEL_RUN_POLICY.get(msg.channel_name)
        if policy is None:
            return None
        if not policy.is_interactive:
            run_context["disable_clarification"] = True
        if policy.credentials_provider is not None:
            try:
                await policy.credentials_provider(msg, run_context)
            except Exception:
                # 凭据失败不能丢弃整次投递；保留只读运行通常优于完全不回复。
                logger.warning(
                    "[Manager] channel=%s credentials_provider raised; run proceeds without injected credentials",
                    msg.channel_name,
                    exc_info=True,
                )
        return policy

    def _resolve_available_skill_names(self, msg: InboundMessage) -> set[str] | None:
        """解析当前通道回合允许通过斜杠激活的技能集合。"""
        thread_id = self.store.get_thread_id(msg.channel_name, msg.chat_id, topic_id=msg.topic_id) or ""
        _, _, run_context = self._resolve_run_params(msg, thread_id)
        if run_context.get("is_bootstrap"):
            return {"bootstrap"}

        agent_name = run_context.get("agent_name")
        if not isinstance(agent_name, str) or not agent_name.strip():
            return None

        # 必须从运行所属用户桶读取 Agent 配置，否则调度循环未绑定的 ContextVar 会
        # 回退到 ``default``，错误读取其他用户的自定义 Agent。
        agent_config = load_agent_config(_normalize_custom_agent_name(agent_name), user_id=run_context.get("user_id"))
        if agent_config and agent_config.skills is not None:
            return set(agent_config.skills)
        return None

    # -- LangGraph SDK 惰性客户端 ------------------------------------------

    def _get_client(self):
        """返回共享的 ``langgraph_sdk`` 异步客户端，并在首次使用时创建。"""
        if self._client is None:
            from langgraph_sdk import get_client

            self._client = get_client(
                url=self._langgraph_url,
                headers={
                    **create_internal_auth_headers(),
                    CSRF_HEADER_NAME: self._csrf_token,
                    "Cookie": f"{CSRF_COOKIE_NAME}={self._csrf_token}",
                },
            )
        return self._client

    def _get_skill_storage(self) -> SkillStorage:
        """惰性获取共享技能存储，避免仅启动通道时加载技能目录。"""
        if self._skill_storage is None:
            self._skill_storage = get_or_new_skill_storage()
        return self._skill_storage

    # -- 生命周期 ----------------------------------------------------------

    async def start(self) -> None:
        """启动带全局并发上限的入站分发循环。"""
        if self._running:
            return
        self._running = True
        self._semaphore = asyncio.Semaphore(self._max_concurrency)
        self._task = asyncio.create_task(self._dispatch_loop())
        logger.info("ChannelManager started (max_concurrency=%d)", self._max_concurrency)

    async def stop(self) -> None:
        """取消并等待分发循环退出。"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("ChannelManager stopped")

    # -- 分发循环 ----------------------------------------------------------

    async def _dispatch_loop(self) -> None:
        """持续消费入站队列，去重后为每条消息创建独立处理任务。"""
        logger.info("[Manager] dispatch loop started, waiting for inbound messages")
        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.get_inbound(), timeout=1.0)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            # 在“已接收”日志前去重，避免平台重投制造多条成功接收记录。适配器在
            # publish_inbound 前产生的确认反应不属于此层职责，可能仍会重复。
            if self._is_duplicate_inbound(msg):
                continue
            logger.info(
                "[Manager] received inbound: channel=%s, chat_id=%s, type=%s, text_len=%d, files=%d",
                msg.channel_name,
                msg.chat_id,
                msg.msg_type.value,
                len(msg.text or ""),
                len(msg.files),
            )
            task = asyncio.create_task(self._handle_message(msg))
            task.add_done_callback(self._log_task_error)

    @staticmethod
    def _inbound_dedupe_key(msg: InboundMessage) -> tuple[str, str, str, str] | None:
        """构造包含平台工作区的稳定去重键；信息不足时放弃去重。"""
        metadata = msg.metadata or {}
        message_id = None
        for key in INBOUND_DEDUPE_METADATA_KEYS:
            value = metadata.get(key)
            if value:
                message_id = str(value)
                break
        if message_id is None:
            raw_message = metadata.get("raw_message")
            if isinstance(raw_message, Mapping):
                for key in INBOUND_DEDUPE_METADATA_KEYS:
                    value = raw_message.get(key)
                    if value:
                        message_id = str(value)
                        break
        if message_id is None:
            return None

        # 缺少工作区时无法区分不同租户中的同名会话，宁可不去重也不能合并跨租户消息。
        workspace_id = msg.workspace_id or metadata.get("workspace_id") or metadata.get("team_id") or metadata.get("guild_id") or metadata.get("aibotid")
        if not workspace_id:
            return None
        return (msg.channel_name, str(workspace_id), msg.chat_id, message_id)

    def _is_duplicate_inbound(self, msg: InboundMessage) -> bool:
        """在有界 TTL 窗口内识别平台重复投递，并维护去重缓存。"""
        key = self._inbound_dedupe_key(msg)
        if key is None:
            return False

        now = time.monotonic()
        # 插入顺序即时间顺序，只需从头部弹出，遇到仍有效项即可停止。
        while self._recent_inbound_events:
            _, oldest_at = next(iter(self._recent_inbound_events.items()))
            if now - oldest_at > INBOUND_DEDUPE_TTL_SECONDS:
                self._recent_inbound_events.popitem(last=False)
            else:
                break
        while len(self._recent_inbound_events) > INBOUND_DEDUPE_MAX_ENTRIES:
            self._recent_inbound_events.popitem(last=False)

        if key in self._recent_inbound_events:
            logger.info(
                "[Manager] duplicate inbound ignored: channel=%s, chat_id=%s, message_id=%s",
                msg.channel_name,
                msg.chat_id,
                key[-1],
            )
            return True

        self._recent_inbound_events[key] = now
        return False

    def _release_inbound_dedupe_key(self, msg: InboundMessage) -> None:
        """删除已记录的去重键，使平台重投能够再次进入处理流程。

        消息刚进入队列时仍需登记去重键，以吸收处理期间的并发重投；只有暂时性或
        未预期失败才释放它，避免可恢复错误让相同 ``message_id`` 在整个 TTL 内
        进入黑洞。
        """
        key = self._inbound_dedupe_key(msg)
        if key is not None:
            self._recent_inbound_events.pop(key, None)

    @staticmethod
    def _log_task_error(task: asyncio.Task) -> None:
        """记录消息后台任务中未被业务分支处理的异常。"""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("[Manager] unhandled error in message task: %s", exc, exc_info=exc)

    async def _handle_message(self, msg: InboundMessage) -> None:
        """执行身份准入和全局并发控制，再分派命令或普通聊天。"""
        msg = _apply_effective_owner(msg)
        try:
            # 普通聊天可在占用并发槽前拒绝；管理器命令有独立准入入口，而平台绑定命令
            # 已由适配器提前消费。
            bound_identity_rejection = None
            if msg.msg_type != InboundMessageType.COMMAND:
                bound_identity_rejection = await self._get_bound_identity_rejection(msg)
            if bound_identity_rejection is not None:
                await self._reject_unbound_channel_message(msg, bound_identity_rejection=bound_identity_rejection)
                return

            async with self._semaphore:
                if msg.msg_type == InboundMessageType.COMMAND:
                    await self._handle_command(msg)
                else:
                    await self._handle_chat(msg, bound_identity_checked=True)
        except InvalidChannelSessionConfigError as exc:
            logger.warning(
                "Invalid channel session config for %s (chat=%s): %s",
                msg.channel_name,
                msg.chat_id,
                exc,
            )
            await self._send_error(msg, str(exc))
        except SlashSkillCommandResolutionError as exc:
            logger.warning(
                "Slash skill command resolution failed for %s (chat=%s): %s",
                msg.channel_name,
                msg.chat_id,
                exc,
            )
            await self._send_error(msg, str(exc))
        except Exception:
            logger.exception(
                "Error handling message from %s (chat=%s)",
                msg.channel_name,
                msg.chat_id,
            )
            # 未预期失败后释放去重键，让平台重投能够恢复，而非在整个 TTL 内被吞掉。
            self._release_inbound_dedupe_key(msg)
            await self._send_error(msg, "An internal error occurred. Please try again.")

    # -- 聊天处理 ----------------------------------------------------------

    async def _get_bound_identity_rejection(self, msg: InboundMessage) -> _BoundIdentityRejection | None:
        """验证持久化连接身份，允许时返回 ``None``，否则返回拒绝路由提示。

        拒绝对象只携带从服务端连接仓库重新读取的字段，确保回复拒绝消息时不会信任
        入站消息自行声明的连接身份。
        """
        if not self._require_bound_identity:
            return None
        # GitHub 等 Webhook 通道已在路由层完成 HMAC 验证，且所有权来自 Agent 配置，
        # 不存在逐发送者的 ``/connect`` 流程，因此可由策略显式跳过此门禁。
        policy = CHANNEL_RUN_POLICY.get(msg.channel_name)
        if policy is not None and not policy.requires_bound_identity:
            return None
        if _auth_disabled_owner_user_id():
            return None

        has_connection = bool(msg.connection_id)
        has_owner = bool(msg.owner_user_id)
        if not (has_connection and has_owner):
            return _BoundIdentityRejection()
        if self._connection_repo is None:
            return _BoundIdentityRejection(message=BOUND_IDENTITY_UNAVAILABLE_MESSAGE)

        # 管理器是创建线程和运行的安全边界，必须按平台身份重新查询绑定，不能只相信
        # 可变的 InboundMessage 字段。
        connection = await self._connection_repo.find_connection_by_external_identity(
            provider=msg.channel_name,
            external_account_id=msg.user_id,
            workspace_id=msg.workspace_id or None,
        )
        if connection is None:
            return _BoundIdentityRejection()

        connection_id = connection.get("id")
        owner_user_id = connection.get("owner_user_id")
        if connection_id == msg.connection_id and owner_user_id == msg.owner_user_id:
            return None
        return _BoundIdentityRejection(outbound_connection_id=connection_id, outbound_owner_user_id=owner_user_id)

    async def _reject_unbound_channel_message(
        self,
        msg: InboundMessage,
        *,
        bound_identity_rejection: _BoundIdentityRejection,
    ) -> None:
        """使用服务端可信路由提示发送身份拒绝消息。"""
        logger.info(
            "[Manager] rejecting unbound channel message: channel=%s, chat_id=%s",
            msg.channel_name,
            msg.chat_id,
        )
        outbound = OutboundMessage(
            channel_name=msg.channel_name,
            chat_id=msg.chat_id,
            thread_id="",
            text=bound_identity_rejection.message,
            thread_ts=msg.thread_ts,
            connection_id=bound_identity_rejection.outbound_connection_id,
            owner_user_id=bound_identity_rejection.outbound_owner_user_id,
            metadata=_slim_metadata(msg.metadata),
        )
        await self.bus.publish_outbound(outbound)

    async def _lookup_thread_id(self, msg: InboundMessage) -> str | None:
        """优先从用户连接仓库查询线程，否则回退到旧版本地映射。"""
        if msg.connection_id and self._connection_repo is not None:
            return await self._connection_repo.get_thread_id(
                msg.connection_id,
                msg.chat_id,
                msg.topic_id,
            )
        return self.store.get_thread_id(msg.channel_name, msg.chat_id, topic_id=msg.topic_id)

    async def _store_thread_id(self, msg: InboundMessage, thread_id: str) -> None:
        """按消息身份选择用户连接仓库或旧版本地存储保存线程映射。"""
        if msg.connection_id and msg.owner_user_id and self._connection_repo is not None:
            await self._connection_repo.set_thread_id(
                connection_id=msg.connection_id,
                owner_user_id=msg.owner_user_id,
                provider=msg.channel_name,
                external_conversation_id=msg.chat_id,
                external_topic_id=msg.topic_id,
                thread_id=thread_id,
            )
            return

        self.store.set_thread_id(
            msg.channel_name,
            msg.chat_id,
            thread_id,
            topic_id=msg.topic_id,
            user_id=msg.user_id,
        )

    async def _create_thread(self, client, msg: InboundMessage) -> str:
        """通过 Gateway 创建线程，并在确认存在后保存平台映射。"""
        metadata = _thread_channel_metadata(msg)
        owner_headers = _owner_headers(msg)
        # GitHub 等通道可提供确定性 thread_id，使仓库存储丢失后同一 PR/Issue 仍回到
        # 相同 LangGraph 线程；未提供时由 Gateway 生成随机 ID。
        meta = msg.metadata if isinstance(msg.metadata, dict) else {}
        preferred_thread_id = meta.get("preferred_thread_id")
        create_kwargs: dict[str, Any] = {"metadata": metadata}
        if isinstance(preferred_thread_id, str) and preferred_thread_id:
            create_kwargs["thread_id"] = preferred_thread_id
        if owner_headers:
            create_kwargs["headers"] = owner_headers
        try:
            thread = await client.threads.create(**create_kwargs)
        except ConflictError as exc:
            # 顺序创建本身是幂等的，因此 409 只代表相同确定性 ID 的真实并发竞争。
            # 恢复范围必须严格限定为 ConflictError；数据库、网络或 5xx 异常若被当作
            # 成功缓存，会让后续消息永久映射到实际不存在的线程。
            if not (isinstance(preferred_thread_id, str) and preferred_thread_id):
                # 没有确定性 ID 就无法确认冲突目标，只能让异常继续向上传播。
                raise
            # 缓存映射前重新读取竞争目标；读取也失败说明底层状态不一致，不能污染该
            # Issue/PR 的所有后续投递。
            try:
                get_kwargs: dict[str, Any] = {}
                if owner_headers:
                    get_kwargs["headers"] = owner_headers
                await client.threads.get(preferred_thread_id, **get_kwargs)
            except Exception as verify_exc:
                logger.warning(
                    "[Manager] threads.create raced on preferred_thread_id=%s (%s) but follow-up threads.get failed (%s); not caching the mapping",
                    preferred_thread_id,
                    exc.__class__.__name__,
                    verify_exc.__class__.__name__,
                )
                raise
            logger.info(
                "[Manager] threads.create raced on preferred_thread_id=%s (%s); reusing the deterministic id",
                preferred_thread_id,
                exc.__class__.__name__,
            )
            await self._store_thread_id(msg, preferred_thread_id)
            return preferred_thread_id
        thread_id = thread["thread_id"]
        await self._store_thread_id(msg, thread_id)
        logger.info("[Manager] new thread created through Gateway: thread_id=%s for chat_id=%s topic_id=%s", thread_id, msg.chat_id, msg.topic_id)
        return thread_id

    async def _get_or_create_thread(self, client, msg: InboundMessage) -> tuple[str, bool]:
        """返回 ``(thread_id, created)``，仅在映射不存在时创建线程。

        每条入站消息由独立任务处理，并发首条消息可能同时观察到空映射。创建路径按
        平台会话加锁并在锁内二次检查，确保只有一个任务创建线程，避免后写覆盖映射、
        遗留孤儿线程并分裂对话历史。
        """
        thread_id = await self._lookup_thread_id(msg)
        if thread_id:
            return thread_id, False

        key = (msg.channel_name, msg.chat_id, msg.topic_id)
        lock = self._thread_create_locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                # 等锁期间其他消息可能已完成创建，因此锁内必须再次查询。
                thread_id = await self._lookup_thread_id(msg)
                if thread_id:
                    return thread_id, False
                return await self._create_thread(client, msg), True
        finally:
            # 映射落盘后后续消息会在首次查询处返回，删除锁项可将注册表限制在进行中的
            # 首次创建会话。
            self._thread_create_locks.pop(key, None)

    async def _update_thread_channel_metadata(self, client, msg: InboundMessage, thread_id: str) -> None:
        """尽力为已有即时通讯线程回填稳定的来源元数据。"""
        # 平台、会话和话题在线程生命周期内不变，每个管理器进程成功回填一次即可。
        if thread_id in self._channel_metadata_synced:
            return
        update_kwargs: dict[str, Any] = {"metadata": _thread_channel_metadata(msg)}
        if owner_headers := _owner_headers(msg):
            update_kwargs["headers"] = owner_headers
        try:
            await client.threads.update(thread_id, **update_kwargs)
        except Exception:
            logger.debug("[Manager] failed to update channel metadata for thread_id=%s", thread_id, exc_info=True)
            return
        if len(self._channel_metadata_synced) > 4096:
            self._channel_metadata_synced.clear()
        self._channel_metadata_synced.add(thread_id)

    async def _handle_chat(
        self,
        msg: InboundMessage,
        extra_context: dict[str, Any] | None = None,
        *,
        bound_identity_checked: bool = False,
    ) -> None:
        """解析或创建线程，并按通道策略串行化同线程回合。"""
        # 正常入口已经完成身份检查；默认仍设为 False，使直接调用和未来内部路径保持
        # fail-closed，而不是意外绕过准入。
        bound_identity_rejection = None if bound_identity_checked else await self._get_bound_identity_rejection(msg)
        if bound_identity_rejection is not None:
            await self._reject_unbound_channel_message(msg, bound_identity_rejection=bound_identity_rejection)
            return

        client = self._get_client()
        storage_user_id = _channel_storage_user_id(msg)

        # topic_id 缺失时映射退化为 ``channel:chat_id``，让 Telegram 私聊等场景在
        # 会话级复用同一 DeerFlow 线程。
        thread_id, created = await self._get_or_create_thread(client, msg)
        if not created:
            logger.info("[Manager] reusing thread: thread_id=%s for topic_id=%s", thread_id, msg.topic_id)
            await self._update_thread_channel_metadata(client, msg, thread_id)

        serial_state, queued = self._begin_serialized_thread_run(
            channel_name=msg.channel_name,
            thread_id=thread_id,
        )
        serial_lock_acquired = False
        try:
            if queued:
                await self._publish_progress_update(
                    msg,
                    thread_id,
                    "Queued behind another request in this conversation. I’ll start working on this as soon as it finishes.",
                )
            if serial_state is not None:
                await serial_state.lock.acquire()
                serial_lock_acquired = True
            if queued:
                await self._publish_progress_update(msg, thread_id, "thinking...")
            await self._handle_chat_on_thread(
                client,
                msg,
                thread_id,
                extra_context=extra_context,
                storage_user_id=storage_user_id,
            )
        finally:
            self._finish_serialized_thread_run(
                channel_name=msg.channel_name,
                thread_id=thread_id,
                state=serial_state,
                lock_acquired=serial_lock_acquired,
            )

    async def _handle_chat_on_thread(
        self,
        client,
        msg: InboundMessage,
        thread_id: str,
        *,
        extra_context: dict[str, Any] | None = None,
        storage_user_id: str | None = None,
    ) -> None:
        """在确定的 DeerFlow 线程上准备附件、运行参数并执行 Agent 回合。"""
        if storage_user_id is None:
            storage_user_id = _channel_storage_user_id(msg)

        assistant_id, run_config, run_context = self._resolve_run_params(msg, thread_id)

        # 凭据注入与非交互标记由策略注册表驱动，新增 Webhook 通道无需修改主流程。
        policy = await self._apply_channel_policy(msg, run_context)

        # 平台适配器先把远端附件实体化，再由通用上传流程写入用户线程目录；不支持
        # 下载的通道按基类契约原样返回消息。
        if msg.files:
            from .service import get_channel_service

            service = get_channel_service()
            channel = service.get_channel(msg.channel_name) if service else None
            logger.info("[Manager] preparing receive file context for %d attachments", len(msg.files))
            msg = await channel.receive_file(msg, thread_id, user_id=storage_user_id) if channel else msg
        if extra_context:
            run_context.update(extra_context)

        original_text = msg.text
        uploaded = await _ingest_inbound_files(thread_id, msg, user_id=storage_user_id)
        if uploaded:
            msg.text = f"{_format_uploaded_files_block(uploaded)}\n\n{msg.text}".strip()
        human_message = _human_input_message(msg.text, original_content=original_text)

        if self._channel_supports_streaming(msg.channel_name):
            await self._handle_streaming_chat(
                client,
                msg,
                thread_id,
                assistant_id,
                run_config,
                run_context,
                human_message,
                storage_user_id=storage_user_id,
            )
            return

        run_kwargs: dict[str, Any] = {
            "input": {"messages": [human_message]},
            "config": run_config,
            "context": run_context,
            "multitask_strategy": "reject",
        }
        if owner_headers := _owner_headers(msg):
            run_kwargs["headers"] = owner_headers

        if policy is not None and policy.fire_and_forget:
            # 自行回写平台的通道无需管理器转发最终状态。``runs.create`` 在 pending
            # 后即返回，可避免长时间自治任务触发 SDK 读取超时；线程冲突仍会同步抛出。
            logger.info(
                "[Manager] invoking runs.create(thread_id=%s, text_len=%d) [fire_and_forget]",
                thread_id,
                len(msg.text or ""),
            )
            try:
                await client.runs.create(thread_id, assistant_id, **run_kwargs)
            except Exception as exc:
                if _is_thread_busy_error(exc):
                    logger.warning("[Manager] thread busy (concurrent run rejected): thread_id=%s", thread_id)
                    await self._send_error(msg, THREAD_BUSY_MESSAGE)
                    return
                raise
            return

        logger.info("[Manager] invoking runs.wait(thread_id=%s, text_len=%d)", thread_id, len(msg.text or ""))
        try:
            result = await client.runs.wait(
                thread_id,
                assistant_id,
                **run_kwargs,
            )
        except Exception as exc:
            if _is_thread_busy_error(exc):
                logger.warning("[Manager] thread busy (concurrent run rejected): thread_id=%s", thread_id)
                await self._send_error(msg, THREAD_BUSY_MESSAGE)
                return
            else:
                raise

        response_text = _extract_response_text(result)
        pending_clarification = _has_current_turn_clarification(result)
        artifacts = _extract_artifacts(result)

        logger.info(
            "[Manager] agent response received: thread_id=%s, response_len=%d, artifacts=%d",
            thread_id,
            len(response_text) if response_text else 0,
            len(artifacts),
        )

        # 复用回合开始时解析的存储所有者，即使 receive_file 返回新消息对象，上传与
        # 产物仍位于同一用户桶。
        response_text, attachments = _prepare_artifact_delivery(thread_id, response_text, artifacts, user_id=storage_user_id)

        if not response_text:
            if attachments:
                response_text = _format_artifact_text([a.virtual_path for a in attachments])
            else:
                response_text = "(No response from agent)"

        outbound = OutboundMessage(
            channel_name=msg.channel_name,
            chat_id=msg.chat_id,
            thread_id=thread_id,
            text=response_text,
            artifacts=artifacts,
            attachments=attachments,
            thread_ts=msg.thread_ts,
            connection_id=msg.connection_id,
            owner_user_id=msg.owner_user_id,
            metadata=_response_metadata(msg.metadata, pending_clarification=pending_clarification),
        )
        logger.info("[Manager] publishing outbound message to bus: channel=%s, chat_id=%s", msg.channel_name, msg.chat_id)
        await self.bus.publish_outbound(outbound)

    async def _handle_streaming_chat(
        self,
        client,
        msg: InboundMessage,
        thread_id: str,
        assistant_id: str,
        run_config: dict[str, Any],
        run_context: dict[str, Any],
        human_message: dict[str, Any],
        storage_user_id: str | None = None,
    ) -> None:
        """消费 Agent SSE 流，节流发布中间文本，并保证最终消息必定落地。"""
        logger.info("[Manager] invoking runs.stream(thread_id=%s, text_len=%d)", thread_id, len(msg.text or ""))

        last_values: dict[str, Any] | list | None = None
        streamed_buffers: dict[str, str] = {}
        current_message_id: str | None = None
        latest_text = ""
        last_published_text = ""
        last_published_len = 0
        last_publish_at = 0.0
        stream_error: BaseException | None = None
        stream_kwargs: dict[str, Any] = {
            "input": {"messages": [human_message]},
            "config": run_config,
            "context": run_context,
            "stream_mode": list(STREAM_MODES),
            "multitask_strategy": "reject",
        }
        if owner_headers := _owner_headers(msg):
            stream_kwargs["headers"] = owner_headers

        try:
            async for chunk in client.runs.stream(
                thread_id,
                assistant_id,
                **stream_kwargs,
            ):
                event = getattr(chunk, "event", "")
                data = getattr(chunk, "data", None)

                if event in MESSAGE_STREAM_EVENTS:
                    accumulated_text, current_message_id = _accumulate_stream_text(streamed_buffers, current_message_id, data)
                    if accumulated_text:
                        latest_text = accumulated_text
                elif event == "values" and isinstance(data, (dict, list)):
                    last_values = data
                    # 澄清问题只存在于 values 快照，也必须在流中及时展示给用户。
                    if _has_current_turn_clarification(data):
                        clarification_text = _extract_response_text(data)
                        if clarification_text and clarification_text != latest_text:
                            latest_text = clarification_text

                if not latest_text or latest_text == last_published_text:
                    continue

                now = time.monotonic()
                new_chars = len(latest_text) - last_published_len
                # 时间窗口或字符阈值任一满足即可刷新，兼顾响应感和平台限流。
                if last_published_text:
                    if now - last_publish_at < STREAM_UPDATE_MIN_INTERVAL_SECONDS and new_chars < STREAM_UPDATE_MIN_CHARS:
                        continue

                display_text = latest_text + " ▉"
                await self.bus.publish_outbound(
                    OutboundMessage(
                        channel_name=msg.channel_name,
                        chat_id=msg.chat_id,
                        thread_id=thread_id,
                        text=display_text,
                        is_final=False,
                        thread_ts=msg.thread_ts,
                        connection_id=msg.connection_id,
                        owner_user_id=msg.owner_user_id,
                        metadata=_response_metadata(msg.metadata),
                    )
                )
                last_published_text = latest_text
                last_published_len = len(latest_text)
                last_publish_at = now
        except Exception as exc:
            stream_error = exc
            if _is_thread_busy_error(exc):
                logger.warning("[Manager] thread busy (concurrent run rejected): thread_id=%s", thread_id)
            else:
                logger.exception("[Manager] streaming error: thread_id=%s", thread_id)
        finally:
            result = last_values if last_values is not None else {"messages": [{"type": "ai", "content": latest_text}]}
            response_text = _extract_response_text(result)
            pending_clarification = _has_current_turn_clarification(result)
            artifacts = _extract_artifacts(result)
            # 复用已解析的存储身份，使错误收尾路径也不会切换产物桶或再次触碰文件系统。
            response_text, attachments = _prepare_artifact_delivery(thread_id, response_text, artifacts, user_id=storage_user_id)

            if not response_text:
                if attachments:
                    response_text = _format_artifact_text([attachment.virtual_path for attachment in attachments])
                elif stream_error:
                    if _is_thread_busy_error(stream_error):
                        response_text = THREAD_BUSY_MESSAGE
                    else:
                        response_text = "An error occurred while processing your request. Please try again."
                else:
                    response_text = latest_text or "(No response from agent)"

            logger.info(
                "[Manager] streaming response completed: thread_id=%s, response_len=%d, artifacts=%d, error=%s",
                thread_id,
                len(response_text),
                len(artifacts),
                stream_error,
            )
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel_name=msg.channel_name,
                    chat_id=msg.chat_id,
                    thread_id=thread_id,
                    text=response_text,
                    artifacts=artifacts,
                    attachments=attachments,
                    is_final=True,
                    thread_ts=msg.thread_ts,
                    connection_id=msg.connection_id,
                    owner_user_id=msg.owner_user_id,
                    metadata=_response_metadata(msg.metadata, pending_clarification=pending_clarification),
                )
            )

    # -- 命令处理 ----------------------------------------------------------

    async def _handle_command(self, msg: InboundMessage) -> None:
        """解析管理器级命令，并在需要时转入普通聊天流程。"""
        # 命令同样可以创建线程或查询 Gateway，必须执行与聊天一致的身份门禁。平台级
        # ``/connect``、``/start`` 已在适配器中消费，不受此处影响。
        bound_identity_rejection = await self._get_bound_identity_rejection(msg)
        if bound_identity_rejection is not None:
            await self._reject_unbound_channel_message(msg, bound_identity_rejection=bound_identity_rejection)
            return

        raw_text = msg.text
        text = raw_text.strip()
        parts = text.split(maxsplit=1)
        reply: str | None = None
        if not parts:
            command = None
            reply = _unknown_command_reply()
        else:
            command = parts[0].lower().removeprefix("/")

        if reply is None and not raw_text.startswith("/"):
            reply = _unknown_command_reply(command)

        if reply is None and command == "bootstrap":
            from dataclasses import replace as _dc_replace

            chat_text = parts[1] if len(parts) > 1 else "Initialize workspace"
            chat_msg = _dc_replace(msg, text=chat_text, msg_type=InboundMessageType.CHAT)
            await self._handle_chat(chat_msg, extra_context={"is_bootstrap": True}, bound_identity_checked=True)
            return

        if reply is None and command == "new":
            # /new 明确要求切换会话，因此不复用当前映射。
            client = self._get_client()
            await self._create_thread(client, msg)
            reply = "New conversation started."
        elif reply is None and command == "status":
            thread_id = await self._lookup_thread_id(msg)
            reply = f"Active thread: {thread_id}" if thread_id else "No active conversation."
        elif reply is None and command == "models":
            reply = await self._fetch_gateway("/api/models", "models", msg=msg)
        elif reply is None and command == "memory":
            reply = await self._fetch_gateway("/api/memory", "memory", msg=msg)
        elif reply is None and command == "goal":
            reply = await self._handle_goal_command(msg, parts[1] if len(parts) > 1 else "")
            if reply is None:
                return
        elif reply is None and command == "help":
            reply = (
                "Available commands:\n"
                "/bootstrap — Start a bootstrap session (enables agent setup)\n"
                "/goal [condition|clear] — Set, show, or clear an active goal\n"
                "/new — Start a new conversation\n"
                "/status — Show current thread info\n"
                "/models — List available models\n"
                "/memory — Show memory status\n"
                "/<skill-name> <task> — Activate an enabled skill for one turn\n"
                "/help — Show this help"
            )
        elif reply is None:
            slash_resolution = await asyncio.to_thread(
                lambda: _resolve_slash_skill_command(
                    raw_text,
                    self._resolve_available_skill_names(msg),
                    self._get_skill_storage,
                )
            )
            if slash_resolution and slash_resolution.failure_message:
                reply = slash_resolution.failure_message
            elif slash_resolution and slash_resolution.route_to_chat:
                from dataclasses import replace as _dc_replace

                chat_msg = _dc_replace(msg, msg_type=InboundMessageType.CHAT)
                await self._handle_chat(chat_msg, bound_identity_checked=True)
                return
            else:
                reply = _unknown_command_reply(command)

        outbound = OutboundMessage(
            channel_name=msg.channel_name,
            chat_id=msg.chat_id,
            thread_id=await self._lookup_thread_id(msg) or "",
            text=reply,
            thread_ts=msg.thread_ts,
            connection_id=msg.connection_id,
            owner_user_id=msg.owner_user_id,
            metadata=_slim_metadata(msg.metadata),
        )
        await self.bus.publish_outbound(outbound)

    async def _goal_request(
        self,
        method: str,
        thread_id: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """向线程目标 API 发起带所有者身份的 goal 请求。"""
        async with httpx.AsyncClient() as http:
            request = getattr(http, method.lower())
            kwargs: dict[str, Any] = {"timeout": 10, "headers": headers}
            if json is not None:
                kwargs["json"] = json
            response = await request(f"{self._gateway_url}/api/threads/{quote(thread_id, safe='')}/goal", **kwargs)
            response.raise_for_status()
            return response.json() or {}

    async def _handle_goal_command(self, msg: InboundMessage, args: str) -> str | None:
        """执行 goal 查询、清除或设置，并在设置后启动首个目标回合。"""
        command = parse_goal_command(args)
        thread_id = await self._lookup_thread_id(msg)
        headers = _owner_headers(msg) or create_internal_auth_headers()

        if command.kind == "status":
            if not thread_id:
                return "No active goal."
            try:
                goal = (await self._goal_request("get", thread_id, headers=headers)).get("goal")
            except Exception:
                logger.exception("Failed to fetch goal from gateway")
                return "Failed to fetch goal information."
            return f"Goal: {goal.get('objective')}" if goal else "No active goal."

        if command.kind == "clear":
            if not thread_id:
                return "Goal cleared."
            try:
                await self._goal_request("delete", thread_id, headers=headers)
            except Exception:
                logger.exception("Failed to clear goal through gateway")
                return "Failed to clear goal."
            return "Goal cleared."

        if not thread_id:
            thread_id = await self._create_thread(self._get_client(), msg)

        try:
            await self._goal_request("put", thread_id, headers=headers, json={"objective": command.objective})
        except Exception:
            logger.exception("Failed to set goal through gateway")
            return "Failed to set goal."

        from dataclasses import replace as _dc_replace

        chat_msg = _dc_replace(msg, text=command.objective, msg_type=InboundMessageType.CHAT)
        await self._handle_chat(chat_msg, bound_identity_checked=True)
        return None

    async def _fetch_gateway(self, path: str, kind: str, *, msg: InboundMessage | None = None) -> str:
        """为通道命令读取 Gateway 数据并转换为简短文本。"""
        import httpx

        try:
            headers = _owner_headers(msg) if msg is not None else None
            async with httpx.AsyncClient() as http:
                resp = await http.get(
                    f"{self._gateway_url}{path}",
                    timeout=10,
                    headers=headers or create_internal_auth_headers(),
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            logger.exception("Failed to fetch %s from gateway", kind)
            return f"Failed to fetch {kind} information."

        if kind == "models":
            names = [m["name"] for m in data.get("models", [])]
            return ("Available models:\n" + "\n".join(f"• {n}" for n in names)) if names else "No models configured."
        elif kind == "memory":
            facts = data.get("facts", [])
            return f"Memory contains {len(facts)} fact(s)."
        return str(data)

    # -- 错误回复 ----------------------------------------------------------

    async def _send_error(self, msg: InboundMessage, error_text: str) -> None:
        """把处理错误回复到原平台消息，同时保留安全精简后的路由元数据。"""
        outbound = OutboundMessage(
            channel_name=msg.channel_name,
            chat_id=msg.chat_id,
            thread_id=await self._lookup_thread_id(msg) or "",
            text=error_text,
            thread_ts=msg.thread_ts,
            connection_id=msg.connection_id,
            owner_user_id=msg.owner_user_id,
            metadata=_slim_metadata(msg.metadata),
        )
        await self.bus.publish_outbound(outbound)
