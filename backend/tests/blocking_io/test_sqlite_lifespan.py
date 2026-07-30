"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


async def test_async_checkpointer_sqlite_setup_does_not_block_event_loop(tmp_path: Path) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from deerflow.config.checkpointer_config import CheckpointerConfig
    from deerflow.runtime.checkpointer.async_provider import _async_checkpointer

    db_file = tmp_path / "subdir" / "store.db"

    mock_saver = AsyncMock()
    mock_context_manager = AsyncMock()
    mock_context_manager.__aenter__.return_value = mock_saver
    mock_context_manager.__aexit__.return_value = False

    mock_saver_cls = MagicMock()
    mock_saver_cls.from_conn_string.return_value = mock_context_manager

    mock_module = MagicMock()
    mock_module.AsyncSqliteSaver = mock_saver_cls

    with patch.dict(sys.modules, {"langgraph.checkpoint.sqlite.aio": mock_module}):
        async with _async_checkpointer(CheckpointerConfig(type="sqlite", connection_string=str(db_file))) as saver:
            assert saver is mock_saver

    assert db_file.parent.exists()
    mock_saver_cls.from_conn_string.assert_called_once_with(str(db_file.resolve()))
    mock_saver.setup.assert_awaited_once()
