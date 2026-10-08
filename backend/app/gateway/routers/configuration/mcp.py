'''提供 MCP 配置读取、更新与敏感字段掩码处理的受控路由。'''

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.gateway.deps import require_admin_user
from deerflow.config.extensions_config import ExtensionsConfig, McpRoutingConfig, McpToolOverride, get_extensions_config, reload_extensions_config
from deerflow.mcp.cache import reset_mcp_tools_cache

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["mcp"])

# 串行化当前工作进程内对 extensions_config.json 的读取、修改和写入。将操作移到工作线程后，
# 不再由单线程事件循环隐式保证串行；否则两个并发的 PUT /api/mcp/config 请求可能交错执行并互相覆盖。
# 跨进程写入仍是另一项既有问题，不由此锁处理。
_mcp_config_write_lock = asyncio.Lock()
_ADMIN_REQUIRED_DETAIL = "Admin privileges required to manage MCP configuration."


_MCP_STDIO_COMMAND_ALLOWLIST_ENV = "DEER_FLOW_MCP_STDIO_COMMAND_ALLOWLIST"
_DEFAULT_MCP_STDIO_COMMAND_ALLOWLIST = frozenset({"npx", "uvx"})
_SHELL_METACHARS = frozenset(";|&`$<>\n\r")


class McpOAuthConfigResponse(BaseModel):
    '''描述 MCP 服务器的令牌获取方式及刷新参数。'''

    enabled: bool = Field(default=True, description="Whether OAuth token injection is enabled")
    token_url: str = Field(default="", description="OAuth token endpoint URL")
    grant_type: Literal["client_credentials", "refresh_token"] = Field(default="client_credentials", description="OAuth grant type")
    client_id: str | None = Field(default=None, description="OAuth client ID")
    client_secret: str | None = Field(default=None, description="OAuth client secret")
    refresh_token: str | None = Field(default=None, description="OAuth refresh token")
    scope: str | None = Field(default=None, description="OAuth scope")
    audience: str | None = Field(default=None, description="OAuth audience")
    token_field: str = Field(default="access_token", description="Token response field containing access token")
    token_type_field: str = Field(default="token_type", description="Token response field containing token type")
    expires_in_field: str = Field(default="expires_in", description="Token response field containing expires-in seconds")
    default_token_type: str = Field(default="Bearer", description="Default token type when response omits token_type")
    refresh_skew_seconds: int = Field(default=60, description="Refresh this many seconds before expiry")
    extra_token_params: dict[str, str] = Field(default_factory=dict, description="Additional form params sent to token endpoint")


class McpServerConfigResponse(BaseModel):
    '''定义单个 MCP 服务器的传输、认证、工具和路由配置结构。'''

    enabled: bool = Field(default=True, description="Whether this MCP server is enabled")
    type: str = Field(default="stdio", description="Transport type: 'stdio', 'sse', or 'http'")
    command: str | None = Field(default=None, description="Command to execute to start the MCP server (for stdio type)")
    args: list[str] = Field(default_factory=list, description="Arguments to pass to the command (for stdio type)")
    env: dict[str, str] = Field(default_factory=dict, description="Environment variables for the MCP server")
    url: str | None = Field(default=None, description="URL of the MCP server (for sse or http type)")
    headers: dict[str, str] = Field(default_factory=dict, description="HTTP headers to send (for sse or http type)")
    oauth: McpOAuthConfigResponse | None = Field(default=None, description="OAuth configuration for MCP HTTP/SSE servers")
    description: str = Field(default="", description="Human-readable description of what this MCP server provides")
    routing: McpRoutingConfig = Field(default_factory=McpRoutingConfig, description="Soft routing hints for tools from this MCP server")
    tools: dict[str, McpToolOverride] = Field(default_factory=dict, description="Per-original-tool MCP configuration overrides")
    tool_call_timeout: float | None = Field(default=None, description="Timeout in seconds for individual stdio MCP tool calls")
    model_config = ConfigDict(extra="allow")


class McpConfigResponse(BaseModel):
    '''返回按服务器名称索引的 MCP 配置。'''

    mcp_servers: dict[str, McpServerConfigResponse] = Field(
        default_factory=dict,
        description="Map of MCP server name to configuration",
    )


class McpConfigUpdateRequest(BaseModel):
    '''接收完整 MCP 服务器配置，用于管理员更新配置文件。'''

    mcp_servers: dict[str, McpServerConfigResponse] = Field(
        ...,
        description="Map of MCP server name to configuration",
    )


class McpCacheResetResponse(BaseModel):
    '''返回 MCP 工具缓存重置操作的结果。'''

    success: bool = Field(description="Whether the MCP tools cache was reset")
    message: str = Field(description="Human-readable reset status")


_MASKED_VALUE = "***"
_SENSITIVE_EXTRA_KEY_RE = re.compile(
    r"(^|_)(api_key|apikey|access_key|private_key|client_secret|secret|token|password|passwd|credential|credentials|authorization|bearer)(_|$)",
    re.IGNORECASE,
)


def _normalize_config_key(key: str) -> str:
    '''将驼峰或连字符配置键规范化为小写下划线形式。'''
    with_boundaries = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", key)
    with_boundaries = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", with_boundaries)
    return re.sub(r"[^a-z0-9]+", "_", with_boundaries.lower()).strip("_")


def _is_sensitive_extra_key(key: str) -> bool:
    '''判断扩展配置键是否可能携带令牌、密钥等敏感值。'''
    return bool(_SENSITIVE_EXTRA_KEY_RE.search(_normalize_config_key(key)))


def _mask_sensitive_extra_value(value: Any) -> Any:
    '''递归掩盖敏感扩展配置值，以免 API 读取响应泄露凭据。'''
    if isinstance(value, dict):
        return {key: _MASKED_VALUE if _is_sensitive_extra_key(str(key)) else _mask_sensitive_extra_value(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_mask_sensitive_extra_value(item) for item in value]
    return value


def _merge_extra_value_preserving_masked(key: str, incoming_value: Any, existing_value: Any, *, existing_present: bool) -> Any:
    '''合并扩展配置时保留掩码字段原值，避免掩码覆盖已存凭据。'''
    if incoming_value == _MASKED_VALUE and _is_sensitive_extra_key(key):
        if existing_present:
            return existing_value
        raise HTTPException(
            status_code=400,
            detail=f"Cannot set extra config key '{key}' to masked value '***'; provide a real value.",
        )

    if isinstance(incoming_value, dict) and isinstance(existing_value, dict):
        merged: dict[str, Any] = {}
        for nested_key, nested_value in incoming_value.items():
            nested_present = nested_key in existing_value
            merged[nested_key] = _merge_extra_value_preserving_masked(
                str(nested_key),
                nested_value,
                existing_value.get(nested_key),
                existing_present=nested_present,
            )
        return merged

    if isinstance(incoming_value, list) and isinstance(existing_value, list) and len(incoming_value) == len(existing_value):
        return [_merge_extra_value_preserving_masked(key, nested_value, existing_value[index], existing_present=True) for index, nested_value in enumerate(incoming_value)]

    return incoming_value


def _allowed_stdio_commands() -> set[str]:
    '''读取受信任的 stdio MCP 可执行程序白名单及环境变量扩展项。'''
    raw = os.environ.get(_MCP_STDIO_COMMAND_ALLOWLIST_ENV)
    base = set(_DEFAULT_MCP_STDIO_COMMAND_ALLOWLIST)
    if raw is None:
        return base
    extra = {item.strip() for item in raw.split(",") if item.strip()}
    return base | extra


def _stdio_command_name(command: str | None, *, server_name: str) -> str:
    '''校验 stdio 命令是单个可执行文件名，参数需另行放入 args 字段。'''
    if command is None or not command.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"MCP server '{server_name}' with stdio transport requires a command.",
        )

    stripped = command.strip()
    has_path_separator = "/" in stripped or "\\" in stripped
    if stripped != command or has_path_separator or any(ch.isspace() for ch in stripped) or any(ch in stripped for ch in _SHELL_METACHARS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"MCP server '{server_name}' command must be a single executable name; put parameters in args instead."),
        )

    return stripped


def _validate_mcp_update_request(request: McpConfigUpdateRequest) -> None:
    '''限制 API 提交的 stdio MCP 命令，阻止未授权程序从网关启动。'''
    allowed_commands = _allowed_stdio_commands()
    for name, server in request.mcp_servers.items():
        transport_type = (server.type or "stdio").lower()
        if transport_type != "stdio":
            continue

        command_name = _stdio_command_name(server.command, server_name=name)
        if command_name not in allowed_commands:
            allowed = ", ".join(sorted(allowed_commands)) or "<none>"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(f"MCP server '{name}' uses disallowed stdio command '{command_name}'. Allowed commands: {allowed}. Configure {_MCP_STDIO_COMMAND_ALLOWLIST_ENV} to extend this list."),
            )


def _mask_server_config(server: McpServerConfigResponse) -> McpServerConfigResponse:
    '''复制 MCP 服务配置并遮蔽环境变量、请求头和 OAuth 凭据。'''
    masked_env = {k: _MASKED_VALUE for k in server.env}
    masked_headers = {k: _MASKED_VALUE for k in server.headers}
    masked_oauth = None
    if server.oauth is not None:
        masked_oauth = server.oauth.model_copy(
            update={
                "client_secret": None,
                "refresh_token": None,
            }
        )
    masked_extra = {key: _MASKED_VALUE if _is_sensitive_extra_key(key) else _mask_sensitive_extra_value(value) for key, value in (server.model_extra or {}).items()}
    return server.model_copy(
        update={
            "env": masked_env,
            "headers": masked_headers,
            "oauth": masked_oauth,
            **masked_extra,
        }
    )


def _merge_preserving_secrets(
    incoming: McpServerConfigResponse,
    existing: McpServerConfigResponse,
) -> McpServerConfigResponse:
    '''合并客户端提交的配置，同时恢复读取接口掩码隐藏的已有密钥。

    只有旧配置中已经存在的环境变量或请求头才能用 ``***`` 表示保留原值；新增项
    必须提供真实值。OAuth 密钥字段为 ``None`` 时保留旧值，空字符串则清除旧值。
    未提交的路由和工具覆写项沿用当前配置，避免局部编辑意外丢失设置。
    '''
    merged_env = {}
    for k, v in incoming.env.items():
        if v == _MASKED_VALUE:
            if k in existing.env:
                merged_env[k] = existing.env[k]
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot set env key '{k}' to masked value '***'; provide a real value.",
                )
        else:
            merged_env[k] = v

    merged_headers = {}
    for k, v in incoming.headers.items():
        if v == _MASKED_VALUE:
            if k in existing.headers:
                merged_headers[k] = existing.headers[k]
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot set header '{k}' to masked value '***'; provide a real value.",
                )
        else:
            merged_headers[k] = v

    merged_oauth = incoming.oauth
    if incoming.oauth is not None and existing.oauth is not None:
        # None 表示保留掩码对应的旧值，空字符串表示明确清除，其余内容作为新值。
        merged_client_secret = existing.oauth.client_secret if incoming.oauth.client_secret is None else (None if incoming.oauth.client_secret == "" else incoming.oauth.client_secret)
        merged_refresh_token = existing.oauth.refresh_token if incoming.oauth.refresh_token is None else (None if incoming.oauth.refresh_token == "" else incoming.oauth.refresh_token)
        merged_oauth = incoming.oauth.model_copy(
            update={
                "client_secret": merged_client_secret,
                "refresh_token": merged_refresh_token,
            }
        )
    update = {
        "env": merged_env,
        "headers": merged_headers,
        "oauth": merged_oauth,
    }
    if "routing" not in incoming.model_fields_set:
        update["routing"] = existing.routing
    if "tools" not in incoming.model_fields_set:
        update["tools"] = existing.tools
    incoming_extra = incoming.model_extra or {}
    existing_extra = existing.model_extra or {}
    for key, value in incoming_extra.items():
        update[key] = _merge_extra_value_preserving_masked(
            key,
            value,
            existing_extra.get(key),
            existing_present=key in existing_extra,
        )
    for key, value in (existing.model_extra or {}).items():
        if key not in (incoming.model_extra or {}):
            update[key] = value
    return incoming.model_copy(update=update)


@router.get(
    "/mcp/config",
    response_model=McpConfigResponse,
    summary="Get MCP Configuration",
    description="Retrieve the current Model Context Protocol (MCP) server configurations.",
)
async def get_mcp_configuration(request: Request) -> McpConfigResponse:
    '''读取当前 MCP 服务器及工具配置。

        返回：
            包含所有服务器的当前 MCP 配置。

        示例：
            ```json
            {
                "mcp_servers": {
                    "github": {
                        "enabled": true,
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-github"],
                        "env": {"GITHUB_TOKEN": "***"},
                        "description": "用于仓库操作的 GitHub 工具服务"
                    }
                }
            }
            ```
    '''
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)

    config = get_extensions_config()

    servers = {name: _mask_server_config(McpServerConfigResponse(**server.model_dump())) for name, server in config.mcp_servers.items()}
    return McpConfigResponse(mcp_servers=servers)


def _apply_mcp_config_update(body: McpConfigUpdateRequest) -> dict:
    '''在线程池中完成 MCP 配置的读取、合并、落盘和重载，并返回更新后的服务器配置。'''
    # 获取现有配置文件位置；首次创建时写入项目根目录。
    config_path = ExtensionsConfig.resolve_config_path()

    # 尚无配置文件时，在项目根目录确定新文件路径。
    if config_path is None:
        config_path = Path.cwd().parent / "extensions_config.json"
        logger.info(f"No existing extensions config found. Creating new config at: {config_path}")

    # 保留扩展配置中的技能状态等非 MCP 配置。
    current_config = get_extensions_config()

    # 读取未展开环境变量的原始 JSON，以保留 ``$VAR`` 占位符和其他顶层字段。
    raw_servers: dict[str, dict] = {}
    raw_other_keys: dict = {}
    if config_path is not None and config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            raw_data = json.load(f)
        raw_servers = raw_data.get("mcpServers", {})
        # 合并并保留 MCP 服务器和技能配置之外的扩展字段。
        for key, value in raw_data.items():
            if key not in ("mcpServers", "skills"):
                raw_other_keys[key] = value

    # 合并请求中的服务器配置与磁盘上原有的密钥。
    merged_servers: dict[str, McpServerConfigResponse] = {}
    for name, incoming in body.mcp_servers.items():
        raw_server = raw_servers.get(name)
        if raw_server is not None:
            merged_servers[name] = _merge_preserving_secrets(
                incoming,
                McpServerConfigResponse(**raw_server),
            )
        else:
            merged_servers[name] = incoming

    # 构造配置数据，并保留原文件中的所有顶层字段。
    config_data = dict(raw_other_keys)
    config_data["mcpServers"] = {name: server.model_dump() for name, server in merged_servers.items()}
    config_data["skills"] = {name: {"enabled": skill.enabled} for name, skill in current_config.skills.items()}

    # 将配置写入文件。
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)

    logger.info(f"MCP configuration updated and saved to: {config_path}")

    # 重新加载 Gateway 配置并更新全局缓存。智能体运行时位于 Gateway 中，因此修改
    # extensions_config.json 后，接口读取到的配置与工具实际执行时使用的配置保持一致。
    reloaded_config = reload_extensions_config()
    return reloaded_config.mcp_servers


@router.post(
    "/mcp/cache/reset",
    response_model=McpCacheResetResponse,
    summary="Reset MCP Tools Cache",
    description=("Reset cached MCP tools and pooled sessions process-wide so tools are reloaded on next use. This affects all threads and users in the current Gateway process."),
)
async def reset_mcp_tools_cache_endpoint(request: Request) -> McpCacheResetResponse:
    '''清除当前 Gateway 进程的 MCP 工具和会话缓存，使后续调用重新加载配置。'''
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    reset_mcp_tools_cache()
    return McpCacheResetResponse(
        success=True,
        message="MCP tools cache reset. Tools will reload on next use.",
    )


@router.put(
    "/mcp/config",
    response_model=McpConfigResponse,
    summary="Update MCP Configuration",
    description="Update Model Context Protocol (MCP) server configurations and save to file.",
)
async def update_mcp_configuration(request: Request, body: McpConfigUpdateRequest) -> McpConfigResponse:
    '''校验并保存 MCP 配置，随后刷新相关工具配置缓存。

        操作流程：
        1. 将新配置保存到 mcp_config.json。
        2. 重新加载配置缓存。
        3. 清空工具缓存，以便下次调用时重新初始化。

        Args:
            request：要保存的新 MCP 配置。

        Returns:
            更新后的 MCP 配置。

        Raises:
            HTTPException：配置文件写入失败时返回 500。

        请求示例：
            ```json
            {
                "mcp_servers": {
                    "github": {
                        "enabled": true,
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-github"],
                        "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"},
                        "description": "用于仓库操作的 GitHub 工具服务"
                    }
                }
            }
            ```
    '''
    try:
        await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
        _validate_mcp_update_request(body)

        # 将 extensions_config.json 的阻塞式读改写操作（解析路径、检查文件、读取原始内容、合并写入、
        # 重新加载）移到工作线程。锁负责串行化当前进程内的并发更新，使操作移出事件循环后仍保持原子性。
        async with _mcp_config_write_lock:
            reloaded_servers = await asyncio.to_thread(_apply_mcp_config_update, body)

        servers = {name: _mask_server_config(McpServerConfigResponse(**server.model_dump())) for name, server in reloaded_servers.items()}
        reset_mcp_tools_cache()
        return McpConfigResponse(mcp_servers=servers)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update MCP configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update MCP configuration: {str(e)}")
