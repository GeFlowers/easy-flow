'''配置运行事件记录的持久化后端、保留策略与查询边界。'''

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RunEventsConfig(BaseModel):
    '''指定网关运行事件存储方式及事件保留参数。'''

    backend: Literal["memory", "db", "jsonl"] = Field(
        default="memory",
        description="Storage backend for run events. 'memory' for development (no persistence), 'db' for production (SQL queries), 'jsonl' for lightweight single-node persistence.",
    )
    max_trace_content: int = Field(
        default=10240,
        description="Maximum trace content size in bytes before truncation (db backend only).",
    )
    track_token_usage: bool = Field(
        default=True,
        description="Whether RunJournal should accumulate token counts to RunRow.",
    )
