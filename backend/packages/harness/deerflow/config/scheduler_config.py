"""提供配置、scheduler、配置相关功能。"""
from pydantic import BaseModel, Field


class SchedulerConfig(BaseModel):
    """\u6267\u884c SchedulerConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    enabled: bool = Field(default=False)
    poll_interval_seconds: int = Field(default=5, ge=1, le=300)
    lease_seconds: int = Field(default=120, ge=5, le=3600)
    max_concurrent_runs: int = Field(default=3, ge=1, le=32)
    min_once_delay_seconds: int = Field(default=60, ge=1, le=86400)
