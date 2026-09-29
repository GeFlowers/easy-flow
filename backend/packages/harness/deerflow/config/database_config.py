"""提供配置、database、配置相关功能。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DatabaseConfig(BaseModel):
    """\u6267\u884c DatabaseConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    backend: Literal["postgres"] = Field(
        default="postgres",
        description="PostgreSQL storage backend for checkpointer and application data.",
    )
    postgres_url: str = Field(
        default="",
        description=(
            "PostgreSQL connection URL, shared by checkpointer and app. "
            "Use $DATABASE_URL in config.yaml to reference .env. "
            "Example: postgresql://user:pass@host:5432/deerflow "
            "(the +asyncpg driver suffix is added automatically where needed)."
        ),
    )
    echo_sql: bool = Field(
        default=False,
        description="Echo all SQL statements to log (debug only).",
    )
    pool_size: int = Field(
        default=5,
        description="Connection pool size for the app ORM engine (postgres only).",
    )

    @property
    def app_sqlalchemy_url(self) -> str:
        """返回 SQLAlchemy 异步引擎使用的 PostgreSQL URL，并补充 asyncpg 驱动名。"""
        if not self.postgres_url:
            raise ValueError("database.postgres_url is required for the postgres backend")
        url = self.postgres_url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url
