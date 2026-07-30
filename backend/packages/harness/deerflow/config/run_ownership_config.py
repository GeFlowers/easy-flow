"""提供配置、run、ownership、配置相关功能。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RunOwnershipConfig(BaseModel):
    """\u6267\u884c RunOwnershipConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

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
