'''为入站消息附加持久化通道连接的所有权信息。'''

from __future__ import annotations

from typing import Any

from app.channels.message_bus import InboundMessage


async def attach_connection_identity(
    inbound: InboundMessage,
    *,
    repo: Any,
    provider: str,
    workspace_id: str | None,
    fallback_without_workspace: bool = False,
) -> InboundMessage:
    '''在存在可信持久化绑定时补充连接 ID 与 DeerFlow 所有者。

    优先按工作区精确查找；只有调用方明确允许时才回退到无工作区绑定，避免相同平台
    用户在多个工作区之间错误继承连接所有权。
    '''
    if repo is None:
        return inbound

    workspace_candidates: list[str | None] = []
    if workspace_id:
        workspace_candidates.append(workspace_id)
    if fallback_without_workspace:
        # 无工作区绑定是兼容旧数据的后备路径，必须排在精确工作区之后。
        workspace_candidates.append(None)
    if not workspace_candidates:
        return inbound

    for candidate in workspace_candidates:
        connection = await repo.find_connection_by_external_identity(
            provider=provider,
            external_account_id=inbound.user_id,
            workspace_id=candidate,
        )
        if connection is None:
            continue

        inbound.connection_id = connection["id"]
        inbound.owner_user_id = connection["owner_user_id"]
        inbound.workspace_id = connection.get("workspace_id")
        return inbound

    return inbound
