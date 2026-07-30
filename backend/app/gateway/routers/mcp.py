"""提供 MCP 配置读取、更新与敏感字段掩码处理的受控路由。"""

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

# Serializes the read-modify-write of extensions_config.json within this worker
# process. Offloading the RMW to a thread removed the implicit serialization the
# single-threaded event loop used to provide, so two concurrent
# PUT /api/mcp/config calls could otherwise interleave and clobber each other.
# (Cross-process writers remain a separate, pre-existing concern.)
_mcp_config_write_lock = asyncio.Lock()
_ADMIN_REQUIRED_DETAIL = "Admin privileges required to manage MCP configuration."


_MCP_STDIO_COMMAND_ALLOWLIST_ENV = "DEER_FLOW_MCP_STDIO_COMMAND_ALLOWLIST"
_DEFAULT_MCP_STDIO_COMMAND_ALLOWLIST = frozenset({"npx", "uvx"})
_SHELL_METACHARS = frozenset(";|&`$<>\n\r")


class McpOAuthConfigResponse(BaseModel):
    '封装 McpOAuthConfigResponse 的状态、协作关系与公开操作。\n\nOAuth configuration for an MCP server.'

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
    '封装 McpServerConfigResponse 的状态、协作关系与公开操作。\n\nResponse model for MCP server configuration.'

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
    '封装 McpConfigResponse 的状态、协作关系与公开操作。\n\nResponse model for MCP configuration.'

    mcp_servers: dict[str, McpServerConfigResponse] = Field(
        default_factory=dict,
        description="Map of MCP server name to configuration",
    )


class McpConfigUpdateRequest(BaseModel):
    '封装 McpConfigUpdateRequest 的状态、协作关系与公开操作。\n\nRequest model for updating MCP configuration.'

    mcp_servers: dict[str, McpServerConfigResponse] = Field(
        ...,
        description="Map of MCP server name to configuration",
    )


class McpCacheResetResponse(BaseModel):
    '封装 McpCacheResetResponse 的状态、协作关系与公开操作。\n\nResponse model for resetting the MCP tools cache.'

    success: bool = Field(description="Whether the MCP tools cache was reset")
    message: str = Field(description="Human-readable reset status")


_MASKED_VALUE = "***"
_SENSITIVE_EXTRA_KEY_RE = re.compile(
    r"(^|_)(api_key|apikey|access_key|private_key|client_secret|secret|token|password|passwd|credential|credentials|authorization|bearer)(_|$)",
    re.IGNORECASE,
)


def _normalize_config_key(key: str) -> str:
    """将驼峰或连字符配置键规范化为小写下划线形式。"""
    with_boundaries = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", key)
    with_boundaries = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", with_boundaries)
    return re.sub(r"[^a-z0-9]+", "_", with_boundaries.lower()).strip("_")


def _is_sensitive_extra_key(key: str) -> bool:
    """判断扩展配置键是否可能携带令牌、密钥等敏感值。"""
    return bool(_SENSITIVE_EXTRA_KEY_RE.search(_normalize_config_key(key)))


def _mask_sensitive_extra_value(value: Any) -> Any:
    """递归掩盖敏感扩展配置值，以免 API 读取响应泄露凭据。"""
    if isinstance(value, dict):
        return {key: _MASKED_VALUE if _is_sensitive_extra_key(str(key)) else _mask_sensitive_extra_value(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_mask_sensitive_extra_value(item) for item in value]
    return value


def _merge_extra_value_preserving_masked(key: str, incoming_value: Any, existing_value: Any, *, existing_present: bool) -> Any:
    """合并扩展配置时保留掩码字段原值，避免掩码覆盖已存凭据。"""
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
    '执行 _allowed_stdio_commands 的明确职责，并返回与调用约定一致的结果。\n\nReturn executable names allowed for API-managed stdio MCP servers.'
    raw = os.environ.get(_MCP_STDIO_COMMAND_ALLOWLIST_ENV)
    base = set(_DEFAULT_MCP_STDIO_COMMAND_ALLOWLIST)
    if raw is None:
        return base
    extra = {item.strip() for item in raw.split(",") if item.strip()}
    return base | extra


def _stdio_command_name(command: str | None, *, server_name: str) -> str:
    '执行 _stdio_command_name 的明确职责，并返回与调用约定一致的结果。\n\nNormalize and validate a stdio command field from the API boundary.'
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
    '执行 _validate_mcp_update_request 的明确职责，并返回与调用约定一致的结果。\n\nValidate API-submitted MCP config before it is persisted.\n\n    Local config files can still express arbitrary advanced setups, but the\n    HTTP API is an untrusted boundary. Restricting stdio commands here reduces\n    the blast radius of a compromised authenticated browser session.\n    '
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
    '执行 _mask_server_config 的明确职责，并返回与调用约定一致的结果。\n\nReturn a copy of server config with sensitive fields masked.\n\n    Masks env values, header values, and removes OAuth secrets so they\n    are not exposed through the GET API endpoint.\n    '
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
    '执行 _merge_preserving_secrets 的明确职责，并返回与调用约定一致的结果。\n\nMerge incoming config with existing, preserving secrets masked by GET.\n\n    When the frontend toggles ``enabled`` it round-trips the full config:\n    GET (masked) → modify enabled → PUT (masked values sent back).\n    This function ensures masked values (``***``) are replaced with the\n    real secrets from the current on-disk config.\n\n    ``***`` is only accepted for keys that already exist in *existing*.\n    New keys must provide a real value.\n\n    For OAuth secrets, ``None`` means "preserve the existing stored value"\n    so masked GET responses can be safely round-tripped. To explicitly clear\n    a stored secret, clients may send an empty string, which is converted\n    to ``None`` before persisting.\n    '
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
        # None = preserve (masked round-trip), "" = explicitly clear, else = new value
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
    '读取并返回，并遵守 get_mcp_configuration 所表达的接口约束。\n\nGet the current MCP configuration.\n\n    Returns:\n        The current MCP configuration with all servers.\n\n    Example:\n        ```json\n        {\n            "mcp_servers": {\n                "github": {\n                    "enabled": true,\n                    "command": "npx",\n                    "args": ["-y", "@modelcontextprotocol/server-github"],\n                    "env": {"GITHUB_TOKEN": "***"},\n                    "description": "GitHub MCP server for repository operations"\n                }\n            }\n        }\n        ```\n    '
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)

    config = get_extensions_config()

    servers = {name: _mask_server_config(McpServerConfigResponse(**server.model_dump())) for name, server in config.mcp_servers.items()}
    return McpConfigResponse(mcp_servers=servers)


def _apply_mcp_config_update(body: McpConfigUpdateRequest) -> dict:
    '执行 _apply_mcp_config_update 的明确职责，并返回与调用约定一致的结果。\n\nWorker-thread body for :func:`update_mcp_configuration`.\n\n    Resolving the config path, the existence probe, reading the raw JSON,\n    writing the merged config, and reloading it are all blocking filesystem IO\n    that must stay off the event loop. The merge is pure in-memory work but\n    lives here too so the whole read-modify-write is a single worker hop.\n    Returns the reloaded MCP server configs for the response.\n    '
    # Get the current config path (or determine where to save it)
    config_path = ExtensionsConfig.resolve_config_path()

    # If no config file exists, create one in the parent directory (project root)
    if config_path is None:
        config_path = Path.cwd().parent / "extensions_config.json"
        logger.info(f"No existing extensions config found. Creating new config at: {config_path}")

    # Load current config to preserve skills
    current_config = get_extensions_config()

    # Load raw (un-resolved) JSON from disk to use as the merge source.
    # This preserves $VAR placeholders in env values and top-level keys
    # like mcpInterceptors that would otherwise be lost.
    raw_servers: dict[str, dict] = {}
    raw_other_keys: dict = {}
    if config_path is not None and config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            raw_data = json.load(f)
        raw_servers = raw_data.get("mcpServers", {})
        # Preserve any top-level keys beyond mcpServers/skills
        for key, value in raw_data.items():
            if key not in ("mcpServers", "skills"):
                raw_other_keys[key] = value

    # Merge incoming server configs with raw on-disk secrets
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

    # Build config data preserving all top-level keys from the original file
    config_data = dict(raw_other_keys)
    config_data["mcpServers"] = {name: server.model_dump() for name, server in merged_servers.items()}
    config_data["skills"] = {name: {"enabled": skill.enabled} for name, skill in current_config.skills.items()}

    # Write the configuration to file
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)

    logger.info(f"MCP configuration updated and saved to: {config_path}")

    # Reload the Gateway configuration and update the global cache. The
    # agent runtime lives in Gateway, so this keeps API reads and tool
    # execution aligned after extensions_config.json changes.
    reloaded_config = reload_extensions_config()
    return reloaded_config.mcp_servers


@router.post(
    "/mcp/cache/reset",
    response_model=McpCacheResetResponse,
    summary="Reset MCP Tools Cache",
    description=("Reset cached MCP tools and pooled sessions process-wide so tools are reloaded on next use. This affects all threads and users in the current Gateway process."),
)
async def reset_mcp_tools_cache_endpoint(request: Request) -> McpCacheResetResponse:
    '执行 reset_mcp_tools_cache_endpoint 的明确职责，并返回与调用约定一致的结果。\n\nReset cached MCP tools and persistent sessions process-wide.\n\n    The next agent run or tool lookup will reload tools from the configured MCP\n    servers. This affects all threads and users in the current Gateway process,\n    and avoids relying on extensions_config.json mtime changes.\n    '
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
    '更新目标状态并返回最新结果，并遵守 update_mcp_configuration 所表达的接口约束。\n\nUpdate the MCP configuration.\n\n    This will:\n    1. Save the new configuration to the mcp_config.json file\n    2. Reload the configuration cache\n    3. Reset MCP tools cache to trigger reinitialization\n\n    Args:\n        request: The new MCP configuration to save.\n\n    Returns:\n        The updated MCP configuration.\n\n    Raises:\n        HTTPException: 500 if the configuration file cannot be written.\n\n    Example Request:\n        ```json\n        {\n            "mcp_servers": {\n                "github": {\n                    "enabled": true,\n                    "command": "npx",\n                    "args": ["-y", "@modelcontextprotocol/server-github"],\n                    "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"},\n                    "description": "GitHub MCP server for repository operations"\n                }\n            }\n        }\n        ```\n    '
    try:
        await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
        _validate_mcp_update_request(body)

        # Offload the blocking read-modify-write of extensions_config.json
        # (path resolve, existence probe, raw read, merged write, reload). The
        # lock serializes concurrent updates within this process so the RMW stays
        # atomic now that it no longer runs inline on the event loop.
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
