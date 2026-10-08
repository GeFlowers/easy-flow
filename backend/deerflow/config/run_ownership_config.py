'''控制运行事件与线程访问是否按当前用户身份隔离。'''

from __future__ import annotations

from pydantic import BaseModel, Field


class RunOwnershipConfig(BaseModel):
    '''为运行记录所有权校验提供启用开关和兼容模式选项。'''

    lease_seconds: int = Field(
        default=30,
        ge=5,
        description="Seconds before a run lease expires if not renewed. Heartbeat renews every lease_seconds / 3.",
    )
    grace_seconds: int = Field(
        default=10,
        ge=0,
        description=(
            "Extra seconds past lease expiry before an orphaned run is reclaimed. Also the clock-skew budget between workers — raise it if worker clocks are not tightly synced; cost is slower recovery of genuinely dead-worker runs."
        ),
    )
    heartbeat_enabled: bool = Field(
        default=False,
        description="When True, the worker periodically renews leases on its active runs. Enable for multi-worker deployments (GATEWAY_WORKERS > 1).",
    )
