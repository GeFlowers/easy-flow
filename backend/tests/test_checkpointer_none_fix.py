'定义 test_checkpointer_none_fix 模块提供的职责与可复用接口。\n\nTest for issue #1016: checkpointer should not return None.'

from unittest.mock import MagicMock, patch

import pytest
from langgraph.checkpoint.memory import InMemorySaver


class TestCheckpointerNoneFix:
    '组织 TestCheckpointerNoneFix 场景的行为与边界验证。\n\nTests that checkpointer context managers return InMemorySaver instead of None.'

    @pytest.mark.anyio
    async def test_async_make_checkpointer_returns_in_memory_saver_when_not_configured(self):
        '验证 async、make、checkpointer、returns、in、memory、saver、when、not、configured 场景下的预期行为、边界条件与结果。\n\nmake_checkpointer should return InMemorySaver when config.checkpointer is None.'
        from deerflow.runtime.checkpointer.async_provider import make_checkpointer

        # 模拟 get_app_config 返回带有 checkpointer=None 和 database=None 的配置
        mock_config = MagicMock()
        mock_config.checkpointer = None
        mock_config.database = None

        with patch("deerflow.runtime.checkpointer.async_provider.get_app_config", return_value=mock_config):
            async with make_checkpointer() as checkpointer:
                # 应该返回 InMemorySaver，而不是 None
                assert checkpointer is not None
                assert isinstance(checkpointer, InMemorySaver)

                # 应该能够在没有 AttributeError 的情况下调用 alist()
                # 这就是 LangGraph 所做的事情以及问题 #1016 中失败的事情
                result = []
                async for item in checkpointer.alist(config={"configurable": {"thread_id": "test"}}):
                    result.append(item)

                # 新的检查指针预计为空列表
                assert result == []

    def test_sync_checkpointer_context_returns_in_memory_saver_when_not_configured(self):
        '验证 sync、checkpointer、context、returns、in、memory、saver、when、not、configured 场景下的预期行为、边界条件与结果。\n\ncheckpointer_context should return InMemorySaver when config.checkpointer is None.'
        from deerflow.runtime.checkpointer.provider import checkpointer_context

        # 模拟 get_app_config 返回带有 checkpointer=None 和 database=None 的配置
        mock_config = MagicMock()
        mock_config.checkpointer = None
        mock_config.database = None

        with patch("deerflow.runtime.checkpointer.provider.get_app_config", return_value=mock_config):
            with checkpointer_context() as checkpointer:
                # 应该返回 InMemorySaver，而不是 None
                assert checkpointer is not None
                assert isinstance(checkpointer, InMemorySaver)

                # 应该能够在没有 AttributeError 的情况下调用 list()
                result = list(checkpointer.list(config={"configurable": {"thread_id": "test"}}))

                # 新的检查指针预计为空列表
                assert result == []
