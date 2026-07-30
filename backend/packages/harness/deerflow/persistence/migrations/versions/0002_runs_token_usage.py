"""提供持久化层的模型、仓储、迁移与数据库辅助实现。"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

# revision identifiers, used by Alembic.
revision: str = "0002_runs_token_usage"
down_revision: str | Sequence[str] | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """执行本迁移版本定义的数据库架构升级操作。"""
    safe_add_column(
        "runs",
        sa.Column(
            "token_usage_by_model",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    """执行本迁移版本定义的数据库架构回退操作。"""
    safe_drop_column("runs", "token_usage_by_model")
