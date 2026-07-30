"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from unittest.mock import MagicMock

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.updater import MemoryUpdater


def _updater(storage: MagicMock) -> MemoryUpdater:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    return MemoryUpdater(DeerMemConfig(), storage, None)


def test_get_memory_data_passes_user_id():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    mock_storage = MagicMock()
    mock_storage.load.return_value = {"version": "1.0"}
    updater = _updater(mock_storage)

    updater.get_memory_data(user_id="alice")

    mock_storage.load.assert_called_once_with(None, user_id="alice")


def test_save_memory_passes_user_id():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    mock_storage = MagicMock()
    mock_storage.save.return_value = True
    updater = _updater(mock_storage)

    updater._save_memory_to_file({"version": "1.0"}, user_id="bob")

    mock_storage.save.assert_called_once_with({"version": "1.0"}, None, user_id="bob")


def test_clear_memory_data_passes_user_id():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    mock_storage = MagicMock()
    mock_storage.save.return_value = True
    updater = _updater(mock_storage)

    updater.clear_memory_data(user_id="charlie")

    assert mock_storage.save.call_args.kwargs["user_id"] == "charlie"
