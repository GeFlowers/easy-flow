'''定义定时任务轮询频率、租约时长及并发运行上限。'''

from pydantic import BaseModel, Field


class SchedulerConfig(BaseModel):
    '''控制定时任务调度器是否启动以及每轮调度的资源边界。'''

    enabled: bool = Field(default=False)
    poll_interval_seconds: int = Field(default=5, ge=1, le=300)
    lease_seconds: int = Field(default=120, ge=5, le=3600)
    max_concurrent_runs: int = Field(default=3, ge=1, le=32)
    min_once_delay_seconds: int = Field(default=60, ge=1, le=86400)
