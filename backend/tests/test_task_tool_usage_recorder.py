'未说明'

from types import SimpleNamespace

from langchain_core.callbacks import AsyncCallbackManager, CallbackManager

from deerflow.tools.builtins.task_tool import _find_usage_recorder


class _RecorderHandler:
    '未说明'
    def record_external_llm_usage_records(self, records):
        """处理录制相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        self.records = records


class _OtherHandler:
    '未说明'
    pass


def _make_runtime(callbacks):
    '未说明'
    return SimpleNamespace(config={"callbacks": callbacks})


def test_find_usage_recorder_with_plain_list():
    '未说明'
    recorder = _RecorderHandler()
    runtime = _make_runtime([_OtherHandler(), recorder])
    assert _find_usage_recorder(runtime) is recorder


def test_find_usage_recorder_with_async_callback_manager():
    '未说明'
    recorder = _RecorderHandler()
    manager = AsyncCallbackManager(handlers=[_OtherHandler(), recorder])
    runtime = _make_runtime(manager)
    assert _find_usage_recorder(runtime) is recorder


def test_find_usage_recorder_with_sync_callback_manager():
    '未说明'
    recorder = _RecorderHandler()
    manager = CallbackManager(handlers=[recorder])
    runtime = _make_runtime(manager)
    assert _find_usage_recorder(runtime) is recorder


def test_find_usage_recorder_returns_none_when_no_recorder():
    '未说明'
    manager = AsyncCallbackManager(handlers=[_OtherHandler()])
    runtime = _make_runtime(manager)
    assert _find_usage_recorder(runtime) is None


def test_find_usage_recorder_handles_empty_manager():
    '未说明'
    manager = AsyncCallbackManager(handlers=[])
    runtime = _make_runtime(manager)
    assert _find_usage_recorder(runtime) is None


def test_find_usage_recorder_returns_none_for_none_runtime():
    '未说明'
    assert _find_usage_recorder(None) is None


def test_find_usage_recorder_returns_none_when_callbacks_is_none():
    '未说明'
    runtime = _make_runtime(None)
    assert _find_usage_recorder(runtime) is None


def test_find_usage_recorder_returns_none_for_single_handler_object():
    '未说明'
    runtime = _make_runtime(_RecorderHandler())
    assert _find_usage_recorder(runtime) is None


def test_find_usage_recorder_returns_none_when_config_not_dict():
    '未说明'
    runtime = SimpleNamespace(config="not-a-dict")
    assert _find_usage_recorder(runtime) is None
