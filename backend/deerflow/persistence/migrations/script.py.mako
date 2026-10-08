'''${message}

迁移版本：${up_revision}
上一个版本：${down_revision | comma,n}
创建时间：${create_date}

'''

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

# 迁移框架根据这些标识组织版本之间的依赖关系。
revision: str = ${repr(up_revision)}
down_revision: str | Sequence[str] | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    '''将数据库结构升级到本次迁移版本。'''
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    '''将数据库结构回退到上一个迁移版本。'''
    ${downgrades if downgrades else "pass"}
