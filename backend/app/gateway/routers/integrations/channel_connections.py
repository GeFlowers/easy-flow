'''面向浏览器的用户自有 IM 渠道绑定 API。'''

from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.channels.runtime_config_store import (
    ChannelRuntimeConfigStore,
    apply_runtime_connection_config,
    merge_runtime_channel_configs,
)
from app.gateway.deps import require_admin_user
from deerflow.config.channel_connections_config import ChannelConnectionsConfig
from deerflow.persistence.channel_connections import ChannelConnectionRepository
from deerflow.persistence.engine import get_session_factory

router = APIRouter(prefix="/api/channels", tags=["channel-connections"])
logger = logging.getLogger(__name__)

_STATE_TTL_SECONDS = 600
_MAX_PENDING_CONNECT_CODES_PER_PROVIDER = 5
_MASKED_CREDENTIAL_VALUE = "********"
_ADMIN_REQUIRED_DETAIL = "Admin privileges required to manage channel runtime credentials."


class ChannelCredentialFieldResponse(BaseModel):
    '''渠道凭据字段的 API 响应模型。'''

    name: str
    label: str
    type: str = "text"
    required: bool = True


class ChannelProviderResponse(BaseModel):
    '''渠道提供商状态的 API 响应模型。'''

    provider: str
    display_name: str
    enabled: bool
    configured: bool
    connectable: bool
    unavailable_reason: str | None = None
    auth_mode: str
    connection_status: str
    credential_fields: list[ChannelCredentialFieldResponse] = Field(default_factory=list)
    credential_values: dict[str, str] = Field(default_factory=dict)


class ChannelProvidersResponse(BaseModel):
    '''渠道提供商列表的 API 响应模型。'''

    enabled: bool
    providers: list[ChannelProviderResponse]


class ChannelConnectionResponse(BaseModel):
    '''用户渠道连接记录的 API 响应模型。'''

    id: str
    provider: str
    status: str
    external_account_id: str | None = None
    external_account_name: str | None = None
    workspace_id: str | None = None
    workspace_name: str | None = None
    scopes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChannelConnectionsResponse(BaseModel):
    '''用户渠道连接列表的 API 响应模型。'''

    connections: list[ChannelConnectionResponse]


class ChannelConnectResponse(BaseModel):
    '''发起渠道连接后的 API 响应模型。'''

    provider: str
    mode: str
    url: str | None = None
    code: str
    instruction: str
    expires_in: int


class ChannelRuntimeConfigRequest(BaseModel):
    '''更新渠道运行时配置的 API 请求模型。'''

    values: dict[str, str] = Field(default_factory=dict)


_PROVIDER_META: dict[str, dict[str, str]] = {
    "wechat": {"display_name": "WeChat", "auth_mode": "binding_code"},
    "wecom": {"display_name": "WeCom", "auth_mode": "binding_code"},
}

_CREDENTIAL_FIELDS: dict[str, tuple[dict[str, str], ...]] = {
    "wechat": ({"name": "bot_token", "label": "Bot token", "type": "password"},),
    "wecom": (
        {"name": "bot_id", "label": "Bot ID", "type": "text"},
        {"name": "bot_secret", "label": "Bot secret", "type": "password"},
    ),
}

_RUNTIME_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "wechat": ("bot_token",),
    "wecom": ("bot_id", "bot_secret"),
}


def _get_user_id(request: Request) -> str:
    '''获取当前已认证用户的 ID。'''
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return str(user.id)


def _get_app_config():
    '''延迟导入并获取应用配置。'''
    from deerflow.config.app_config import get_app_config

    return get_app_config()


async def _get_runtime_config_store(request: Request) -> ChannelRuntimeConfigStore:
    '''获取或创建请求应用状态中的运行时配置存储。'''
    store = getattr(request.app.state, "channel_runtime_config_store", None)
    if isinstance(store, ChannelRuntimeConfigStore):
        return store
    # 构造存储会从磁盘读取 JSON 文件，因此移出事件循环。
    store = await asyncio.to_thread(ChannelRuntimeConfigStore)
    request.app.state.channel_runtime_config_store = store
    return store


async def _get_channel_connections_config(request: Request) -> ChannelConnectionsConfig:
    '''获取并应用运行时覆盖后的渠道连接配置。'''
    config = getattr(request.app.state, "channel_connections_config", None)
    if not isinstance(config, ChannelConnectionsConfig):
        config = _get_app_config().channel_connections
    config = apply_runtime_connection_config(config, store=await _get_runtime_config_store(request))
    request.app.state.channel_connections_config = config
    return config


async def _get_channels_config(request: Request) -> dict[str, Any]:
    '''获取应用状态中缓存的渠道运行时配置。'''
    state_config = getattr(request.app.state, "channels_config", None)
    if isinstance(state_config, dict):
        return state_config

    result = await _load_channels_config(request, await _get_channel_connections_config(request))
    request.app.state.channels_config = result
    return result


async def _load_channels_config(request: Request, config: ChannelConnectionsConfig) -> dict[str, Any]:
    '''从应用配置加载渠道配置，并合并运行时覆盖项。'''
    app_config = _get_app_config()
    extra = app_config.model_extra or {}
    channels_config = extra.get("channels")
    result = dict(channels_config) if isinstance(channels_config, dict) else {}
    merge_runtime_channel_configs(
        result,
        config,
        store=await _get_runtime_config_store(request),
    )
    return result


def _get_repository(request: Request, config: ChannelConnectionsConfig) -> ChannelConnectionRepository:
    '''获取或创建渠道连接仓储。'''
    repo = getattr(request.app.state, "channel_connection_repo", None)
    if isinstance(repo, ChannelConnectionRepository):
        return repo

    sf = get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="Channel connection persistence is not available")

    repo = ChannelConnectionRepository(sf)
    request.app.state.channel_connection_repo = repo
    return repo


def _provider_config(config: ChannelConnectionsConfig, provider: str):
    '''返回已知提供商的连接配置，不接受任意配置属性。'''
    # 仅解析已知提供商。任意 `getattr` 会让请求提供的名称命中其他配置属性（如
    # `enabled` / `require_bound_identity` 布尔值），绕过 404 并返回非提供商对象；
    # 调用方随后按提供商配置解引用时会触发 `AttributeError`，最终变为 HTTP 500。
    if provider not in _PROVIDER_META:
        raise HTTPException(status_code=404, detail="Unknown channel provider")
    provider_config = getattr(config, provider, None)
    if provider_config is None:
        raise HTTPException(status_code=404, detail="Unknown channel provider")
    return provider_config


def _runtime_channel_configured(provider: str, channels_config: dict[str, Any]) -> bool:
    '''判断渠道运行时配置是否已启用且具备全部必填凭据。'''
    runtime_config = channels_config.get(provider)
    if not isinstance(runtime_config, dict) or not runtime_config.get("enabled", False):
        return False
    return all(str(runtime_config.get(key) or "").strip() for key in _RUNTIME_REQUIREMENTS[provider])


def _runtime_unavailable_reason(provider: str) -> str:
    '''生成渠道运行时配置不可用的提示文本。'''
    meta = _PROVIDER_META.get(provider)
    display_name = meta["display_name"] if meta else provider
    return f"Enter the required {display_name} credentials to connect this channel."


def _runtime_not_running_reason(provider: str) -> str:
    '''生成渠道已配置但未运行的提示文本。'''
    meta = _PROVIDER_META.get(provider)
    display_name = meta["display_name"] if meta else provider
    return f"{display_name} channel is configured but is not running. Check the credentials and service logs."


def _runtime_channel_running(provider: str) -> bool | None:
    '''查询渠道运行状态；无法确定时返回 `None`。'''
    try:
        from app.channels.service import get_channel_service
    except Exception:
        logger.debug("Unable to inspect channel service status", exc_info=True)
        return None

    service = get_channel_service()
    if service is None:
        return None
    try:
        status = service.get_status()
    except Exception:
        logger.debug("Unable to read channel service status", exc_info=True)
        return None

    if not status.get("service_running"):
        return False
    channel_status = status.get("channels", {}).get(provider)
    if not isinstance(channel_status, dict):
        return None
    return bool(channel_status.get("running"))


async def _ensure_runtime_channel_ready_if_available(
    provider: str,
    channels_config: dict[str, Any],
) -> bool | None:
    '''在运行时服务可用时协调指定渠道的就绪状态。'''
    runtime_config = channels_config.get(provider)
    if not isinstance(runtime_config, dict) or not runtime_config.get("enabled", False):
        return None

    try:
        from app.channels.service import get_channel_service
    except Exception:
        logger.debug("Unable to import channel service for readiness reconciliation", exc_info=True)
        return None

    service = get_channel_service()
    if service is None:
        return None

    ensure_channel_ready = getattr(service, "ensure_channel_ready", None)
    if ensure_channel_ready is None:
        return None

    try:
        return await ensure_channel_ready(provider, runtime_config)
    except Exception:
        logger.exception("Failed to reconcile runtime channel readiness")
        return False


def _provider_unavailable_reason(
    config: ChannelConnectionsConfig,
    channels_config: dict[str, Any],
    provider: str,
) -> str | None:
    '''返回提供商当前不可用的原因；可用时返回 `None`。'''
    provider_config = _provider_config(config, provider)
    if not provider_config.enabled:
        return None
    if not provider_config.configured:
        return _runtime_unavailable_reason(provider)
    if not _runtime_channel_configured(provider, channels_config):
        return _runtime_unavailable_reason(provider)
    if _runtime_channel_running(provider) is False:
        return _runtime_not_running_reason(provider)
    return None


def _provider_status(
    config: ChannelConnectionsConfig,
    channels_config: dict[str, Any],
    provider: str,
) -> tuple[dict[str, bool], str | None]:
    '''汇总提供商的启用、配置和可用状态。'''
    declared = config.provider_status(provider)
    unavailable_reason = _provider_unavailable_reason(config, channels_config, provider)
    configured = declared["configured"] and _runtime_channel_configured(provider, channels_config)
    return {"enabled": declared["enabled"], "configured": configured}, unavailable_reason


def _new_binding_code() -> str:
    '''生成一次性渠道绑定码。'''
    return secrets.token_urlsafe(16)


async def _create_state(
    repo: ChannelConnectionRepository,
    *,
    owner_user_id: str,
    provider: str,
) -> str:
    '''在每个提供商的待绑定数量上限内创建绑定状态。'''
    now = datetime.now(UTC)
    state = _new_binding_code()
    # 原子执行过期清理、计数和插入，避免同一用户并发发起连接时都看到数量未达上限，
    # 从而共同插入并突破上限。
    inserted = await repo.create_oauth_state_within_cap(
        owner_user_id=owner_user_id,
        provider=provider,
        state=state,
        expires_at=now + timedelta(seconds=_STATE_TTL_SECONDS),
        max_pending=_MAX_PENDING_CONNECT_CODES_PER_PROVIDER,
        now=now,
    )
    if not inserted:
        raise HTTPException(
            status_code=429,
            detail="Too many pending channel connection codes. Wait for existing codes to expire or use one of them.",
        )
    return state


def _connect_instruction(provider: str, code: str) -> str:
    '''生成用户在渠道机器人中完成绑定的操作说明。'''
    meta = _PROVIDER_META.get(provider)
    if meta is None:
        raise HTTPException(status_code=404, detail="Unknown channel provider")
    return f"Send /connect {code} to the DeerFlow {meta['display_name']} bot."


def _connect_url(config: ChannelConnectionsConfig, provider: str, code: str) -> str | None:
    '''生成支持深链接的渠道绑定 URL。'''
    if _PROVIDER_META.get(provider, {}).get("auth_mode") == "binding_code":
        return None
    raise HTTPException(status_code=404, detail="Unknown channel provider")


def _connection_updated_at(connection: dict[str, Any]) -> datetime:
    '''将连接记录的 `updated_at` 规范化为带时区的时间。'''
    value = connection.get("updated_at")
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=UTC)


def _newest_connection_by_provider(connections: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    '''按提供商保留最新的连接记录。'''
    by_provider: dict[str, dict[str, Any]] = {}
    for item in connections:
        existing = by_provider.get(item["provider"])
        if existing is None or _connection_updated_at(item) > _connection_updated_at(existing):
            by_provider[item["provider"]] = item
    return by_provider


def _credential_fields(provider: str) -> list[ChannelCredentialFieldResponse]:
    '''返回提供商所需凭据字段的响应模型列表。'''
    fields = _CREDENTIAL_FIELDS.get(provider)
    if fields is None:
        raise HTTPException(status_code=404, detail="Unknown channel provider")
    return [ChannelCredentialFieldResponse(**field) for field in fields]


def _credential_values(provider: str, channels_config: dict[str, Any]) -> dict[str, str]:
    '''读取提供商的已配置凭据，并掩码敏感字段。'''
    runtime_config = channels_config.get(provider)
    if not isinstance(runtime_config, dict):
        return {}

    values: dict[str, str] = {}
    for field in _credential_fields(provider):
        value = str(runtime_config.get(field.name) or "").strip()
        if not value:
            continue
        values[field.name] = _MASKED_CREDENTIAL_VALUE if field.type == "password" else value
    return values


def _provider_response(
    config: ChannelConnectionsConfig,
    channels_config: dict[str, Any],
    provider: str,
    meta: dict[str, str],
    connection: dict[str, Any] | None = None,
) -> ChannelProviderResponse:
    '''构建面向当前用户的渠道提供商状态响应。'''
    from app.gateway.auth_disabled import is_auth_disabled

    status, unavailable_reason = _provider_status(config, channels_config, provider)
    if unavailable_reason is not None:
        # 运行时提供商不可用时，不得将过期的 `connected` 记录仍报告为已连接；其余
        # 状态（如 `revoked`）需保留，使调用方仍可区分已撤销绑定与从未连接。
        if connection and connection["status"] != "connected":
            connection_status = connection["status"]
        else:
            connection_status = "not_connected"
    elif connection:
        connection_status = connection["status"]
    elif is_auth_disabled() and status["configured"] and unavailable_reason is None:
        # 认证禁用的本地模式会将所有渠道消息路由至默认用户，因此已配置且运行中的
        # 渠道无需用户级绑定。
        connection_status = "connected"
    else:
        connection_status = "not_connected"
    credential_values = _credential_values(provider, channels_config)
    return ChannelProviderResponse(
        provider=provider,
        display_name=meta["display_name"],
        enabled=status["enabled"],
        configured=status["configured"],
        connectable=status["enabled"] and status["configured"] and unavailable_reason is None,
        unavailable_reason=unavailable_reason,
        auth_mode=meta["auth_mode"],
        connection_status=connection_status,
        credential_fields=_credential_fields(provider),
        credential_values=credential_values,
    )


def _required_runtime_values(
    provider: str,
    values: dict[str, str],
    existing_config: dict[str, Any] | None = None,
) -> dict[str, str]:
    '''校验并清洗渠道运行时配置所需的凭据值。'''
    fields = _credential_fields(provider)
    cleaned: dict[str, str] = {}
    missing: list[str] = []
    existing_config = existing_config or {}
    for field in fields:
        raw_value = values.get(field.name, "")
        if field.type == "password" and raw_value == _MASKED_CREDENTIAL_VALUE:
            existing_value = str(existing_config.get(field.name) or "").strip()
            if existing_value:
                cleaned[field.name] = existing_value
                continue
        value = raw_value.strip() if isinstance(raw_value, str) else str(raw_value or "").strip()
        if field.required and not value:
            missing.append(field.label)
        cleaned[field.name] = value
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required channel configuration: {', '.join(missing)}")
    return cleaned


async def _restart_runtime_channel_if_available(provider: str, runtime_config: dict[str, Any]) -> bool | None:
    '''在渠道服务可用时应用配置并重启指定渠道。'''
    try:
        from app.channels.service import get_channel_service
    except Exception:
        logger.exception("Failed to import channel service while configuring a runtime channel")
        return None

    service = get_channel_service()
    if service is None:
        return None
    return await service.configure_channel(provider, runtime_config)


async def _sync_runtime_channel_after_removal(provider: str, channels_config: dict[str, Any]) -> bool | None:
    '''在移除配置后同步指定渠道的运行时状态。'''
    try:
        from app.channels.service import get_channel_service
    except Exception:
        logger.exception("Failed to import channel service while disconnecting a runtime channel")
        return None

    service = get_channel_service()
    if service is None:
        return None

    runtime_config = channels_config.get(provider)
    if isinstance(runtime_config, dict) and runtime_config.get("enabled", False):
        return await service.configure_channel(provider, runtime_config)
    return await service.remove_channel(provider)


@router.get("/providers", response_model=ChannelProvidersResponse)
async def get_channel_providers(request: Request) -> ChannelProvidersResponse:
    '''返回当前用户可见的渠道提供商状态。'''
    config = await _get_channel_connections_config(request)
    channels_config = await _get_channels_config(request)
    repo = None
    if config.enabled:
        try:
            repo = _get_repository(request, config)
        except HTTPException as exc:
            if exc.status_code != 503:
                raise
    owner_user_id = _get_user_id(request)
    connections = await repo.list_connections(owner_user_id) if repo is not None else []
    by_provider = _newest_connection_by_provider(connections)

    enabled_providers = [provider for provider in _PROVIDER_META if config.provider_status(provider)["enabled"]]
    # 各提供商的就绪协调相互独立，并发执行可避免单个渠道重启缓慢而串行阻塞整个
    # `/providers` 响应。
    await asyncio.gather(
        *(_ensure_runtime_channel_ready_if_available(provider, channels_config) for provider in enabled_providers if _runtime_channel_configured(provider, channels_config)),
    )

    providers: list[ChannelProviderResponse] = []
    for provider in enabled_providers:
        connection = by_provider.get(provider)
        providers.append(_provider_response(config, channels_config, provider, _PROVIDER_META[provider], connection))
    return ChannelProvidersResponse(enabled=config.enabled, providers=providers)


@router.get("/connections", response_model=ChannelConnectionsResponse)
async def get_channel_connections(request: Request) -> ChannelConnectionsResponse:
    '''返回当前用户的渠道连接列表。'''
    config = await _get_channel_connections_config(request)
    if not config.enabled:
        return ChannelConnectionsResponse(connections=[])
    repo = _get_repository(request, config)
    rows = await repo.list_connections(_get_user_id(request))
    return ChannelConnectionsResponse(connections=[ChannelConnectionResponse(**row) for row in rows])


@router.delete("/connections/{connection_id}", status_code=204)
async def disconnect_channel_connection(connection_id: str, request: Request) -> Response:
    '''断开当前用户拥有的指定渠道连接。'''
    config = await _get_channel_connections_config(request)
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Channel connections are disabled")

    repo = _get_repository(request, config)
    disconnected = await repo.disconnect_connection(
        connection_id=connection_id,
        owner_user_id=_get_user_id(request),
    )
    if not disconnected:
        raise HTTPException(status_code=404, detail="Channel connection not found")
    return Response(status_code=204)


@router.delete("/{provider}/runtime-config", response_model=ChannelProviderResponse)
async def disconnect_channel_provider_runtime(provider: str, request: Request) -> ChannelProviderResponse:
    '''移除管理员配置的渠道运行时凭据与配置。'''
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    config = await _get_channel_connections_config(request)
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Channel connections are disabled")

    provider_config = _provider_config(config, provider)
    if not provider_config.enabled:
        raise HTTPException(status_code=400, detail="Channel provider is not enabled")

    try:
        repo = _get_repository(request, config)
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        repo = None

    current_channels_config = await _get_channels_config(request)
    candidate_channels_config = dict(current_channels_config)
    candidate_channels_config.pop(provider, None)

    stopped = await _sync_runtime_channel_after_removal(provider, candidate_channels_config)
    if stopped is False:
        display_name = _PROVIDER_META[provider]["display_name"]
        raise HTTPException(status_code=400, detail=f"Failed to stop {display_name} channel. Try again.")

    # 在提交存储和缓存前撤销数据库连接记录，避免仓储操作失败导致存储和缓存显示
    # `disconnected`，而数据库仍保留 `connected` 记录，并在日后重新配置时被静默激活。
    if repo is not None:
        await repo.disconnect_provider_connections(provider=provider)

    store = await _get_runtime_config_store(request)
    await asyncio.to_thread(store.set_provider_disconnected, provider)

    # 重新读取实时缓存配置，仅移除当前提供商，避免覆盖其他提供商的并发修改。读取与
    # 重新赋值之间不得出现 `await`。
    live_channels_config = await _get_channels_config(request)
    live_channels_config.pop(provider, None)
    request.app.state.channels_config = live_channels_config

    return _provider_response(config, live_channels_config, provider, _PROVIDER_META[provider])


@router.post("/{provider}/connect", response_model=ChannelConnectResponse)
async def connect_channel_provider(provider: str, request: Request) -> ChannelConnectResponse:
    '''创建当前用户连接指定渠道所需的一次性绑定信息。'''
    config = await _get_channel_connections_config(request)
    channels_config = await _get_channels_config(request)
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Channel connections are disabled")

    provider_config = _provider_config(config, provider)
    if provider_config.enabled and _runtime_channel_configured(provider, channels_config):
        await _ensure_runtime_channel_ready_if_available(provider, channels_config)

    status, unavailable_reason = _provider_status(config, channels_config, provider)
    if not status["enabled"]:
        raise HTTPException(status_code=400, detail="Channel provider is not enabled")
    if unavailable_reason:
        raise HTTPException(status_code=400, detail=unavailable_reason)
    if not status["configured"]:
        raise HTTPException(status_code=400, detail="Channel provider is not configured")

    repo = _get_repository(request, config)
    code = await _create_state(
        repo,
        owner_user_id=_get_user_id(request),
        provider=provider,
    )
    return ChannelConnectResponse(
        provider=provider,
        mode=_PROVIDER_META[provider]["auth_mode"],
        url=_connect_url(config, provider, code),
        code=code,
        instruction=_connect_instruction(provider, code),
        expires_in=_STATE_TTL_SECONDS,
    )


@router.post("/{provider}/runtime-config", response_model=ChannelProviderResponse)
async def configure_channel_provider_runtime(
    provider: str,
    body: ChannelRuntimeConfigRequest,
    request: Request,
) -> ChannelProviderResponse:
    '''由管理员配置指定渠道的运行时凭据并启动渠道。'''
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    config = await _get_channel_connections_config(request)
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Channel connections are disabled")

    provider_config = _provider_config(config, provider)
    if not provider_config.enabled:
        raise HTTPException(status_code=400, detail="Channel provider is not enabled")

    channels_config = await _get_channels_config(request)
    existing = channels_config.get(provider)
    runtime_config = dict(existing) if isinstance(existing, dict) else {}
    values = _required_runtime_values(provider, body.values, runtime_config)
    runtime_config["enabled"] = True

    for key in _RUNTIME_REQUIREMENTS[provider]:
        runtime_config[key] = values[key]

    candidate_channels_config = dict(channels_config)
    candidate_channels_config[provider] = runtime_config

    started = await _restart_runtime_channel_if_available(provider, runtime_config)
    if started is False:
        display_name = _PROVIDER_META[provider]["display_name"]
        raise HTTPException(status_code=400, detail=f"Failed to start {display_name} channel. Check the values and try again.")

    store = await _get_runtime_config_store(request)
    await asyncio.to_thread(store.set_provider_config, provider, runtime_config)

    # 重新读取实时缓存配置，仅应用当前提供商的变更，避免覆盖其他提供商的并发修改。读取
    # 与重新赋值之间不得出现 `await`。
    live_channels_config = await _get_channels_config(request)
    live_channels_config[provider] = runtime_config
    request.app.state.channels_config = live_channels_config

    return _provider_response(config, live_channels_config, provider, _PROVIDER_META[provider])
