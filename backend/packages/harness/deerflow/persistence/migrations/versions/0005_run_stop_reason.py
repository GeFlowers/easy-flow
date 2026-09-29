"""提供持久化层的模型、仓储、迁移与数据库辅助实现。"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_run_stop_reason"
down_revision: str | Sequence[str] | None = "0004_run_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为运行记录增加区分取消、超时等结束路径的停止原因字段。"""
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("runs", sa.Column("stop_reason", sa.String(50), nullable=True))


def downgrade() -> None:
    """移除运行记录的停止原因字段。"""
    op.drop_column("runs", "stop_reason")
