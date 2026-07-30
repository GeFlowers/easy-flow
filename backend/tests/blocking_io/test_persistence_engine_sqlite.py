"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
import deerflow.persistence.models  # noqa: E402,F401
from deerflow.persistence import engine as engine_mod  # noqa: E402

pytestmark = pytest.mark.asyncio


def _noop_listens_for(*_args, **_kwargs):
    """准备可控测试资源与状态，供后续断言读取。"""

    def _decorator(fn):
        """返回不修改被装饰函数的替身装饰器，供引擎初始化测试替换事件监听注册。"""
        return fn

    return _decorator


async def test_init_engine_sqlite_dir_setup_does_not_block_event_loop(tmp_path: Path) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    data_dir = tmp_path / "newsubdir"  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    db_file = data_dir / "app.db"

    mock_conn = AsyncMock()
    begin_ctx = AsyncMock()
    begin_ctx.__aenter__.return_value = mock_conn
    begin_ctx.__aexit__.return_value = False
    mock_engine = MagicMock()
    mock_engine.begin.return_value = begin_ctx
    mock_engine.dispose = AsyncMock()

    async def _noop_bootstrap(*_args, **_kwargs):
        """准备可控测试资源与状态，供后续断言读取。"""
        return None

    with (
        patch.object(engine_mod, "create_async_engine", return_value=mock_engine),
        patch.object(engine_mod, "async_sessionmaker", return_value=MagicMock()),
        patch("sqlalchemy.event.listens_for", _noop_listens_for),
        patch(
            "deerflow.persistence.bootstrap.bootstrap_schema",
            new=_noop_bootstrap,
        ),
    ):
        await engine_mod.init_engine(
            backend="sqlite",
            url=f"sqlite+aiosqlite:///{db_file}",
            sqlite_dir=str(data_dir),
        )
        assert data_dir.exists()

    await engine_mod.close_engine()
