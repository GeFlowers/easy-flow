"""本脚本负责版本修订。安全边界：仅处理显式指定的输入与路径，不作为常驻生产服务入口。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config

import deerflow.persistence.models  # noqa: F401  -- registers ORM models with Base.metadata
from deerflow.persistence.bootstrap import _escape_url_for_alembic

BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = BACKEND_DIR / "packages/harness/deerflow/persistence/migrations"


def _alembic_config(url: str) -> Config:
    '未说明'
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    # Shared with ``bootstrap._alembic_safe_url`` so the ConfigParser ``%``
    # interpolation rule lives in one place.
    cfg.set_main_option("sqlalchemy.url", _escape_url_for_alembic(url))
    return cfg


def _build_temp_db_at_head() -> str:
    '未说明'
    tmpdir = tempfile.mkdtemp(prefix="deerflow-autogen-")
    db_path = os.path.join(tmpdir, "autogen.db").replace(os.sep, "/")
    url = f"sqlite+aiosqlite:///{db_path}"
    command.upgrade(_alembic_config(url), "head")
    return url


def main() -> None:
    '未说明'
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print('usage: python scripts/_autogen_revision.py "describe the change"', file=sys.stderr)
        sys.exit(2)
    message = sys.argv[1]

    url = _build_temp_db_at_head()
    print(f"autogen: built temp DB at head: {url}", file=sys.stderr)

    command.revision(_alembic_config(url), message=message, autogenerate=True)


if __name__ == "__main__":
    main()
