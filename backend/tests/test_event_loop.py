'''验证删除自动启动补丁后，显式异步入口仍使用兼容的事件循环。'''

import asyncio
from pathlib import Path
import sys
import unittest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


class EventLoopTests(unittest.TestCase):
    '''覆盖普通协程、异常、同步工具桥接和子代理后台循环。'''

    def test_no_automatic_startup_module(self):
        '''后端不再携带自动导入的全局补丁。'''
        self.assertFalse((BACKEND / 'sitecustomize.py').exists())

    def test_explicit_runner_preserves_global_policy(self):
        '''显式运行器应选择兼容循环，但不修改进程全局策略。'''
        from deerflow.utils.event_loop import run_async

        policy = asyncio.get_event_loop_policy()

        async def inspect_loop():
            '''返回当前循环类型，避免触发外部调用。'''
            loop = asyncio.get_running_loop()
            return isinstance(loop, asyncio.SelectorEventLoop) if sys.platform == 'win32' else True

        self.assertTrue(run_async(inspect_loop()))
        self.assertIs(asyncio.get_event_loop_policy(), policy)

    def test_runner_propagates_errors(self):
        '''业务异常必须返回给调用方，不能被兼容层吞掉。'''
        from deerflow.utils.event_loop import run_async

        async def fail():
            '''生成可验证的业务错误。'''
            raise ValueError('测试异常')

        with self.assertRaisesRegex(ValueError, '测试异常'):
            run_async(fail())

    def test_sync_tool_inside_and_outside_running_loop(self):
        '''同步工具在普通线程和已有循环内均应使用兼容循环。'''
        from deerflow.utils.event_loop import run_async
        from deerflow.tools.sync import make_sync_tool_wrapper

        async def operation():
            '''检查工具实际运行的循环，而不是调用方的循环。'''
            loop = asyncio.get_running_loop()
            return isinstance(loop, asyncio.SelectorEventLoop) if sys.platform == 'win32' else True

        wrapped = make_sync_tool_wrapper(operation, 'event_loop_test')
        self.assertTrue(wrapped())

        async def invoke_wrapper():
            '''模拟异步主流程调用同步工具。'''
            return wrapped()

        self.assertTrue(run_async(invoke_wrapper()))

    def test_subagent_loop_uses_explicit_factory(self):
        '''子代理线程自建循环时不依赖全局补丁。'''
        from deerflow.subagents.executor import _get_isolated_subagent_loop, _shutdown_isolated_subagent_loop

        try:
            loop = _get_isolated_subagent_loop()
            self.assertTrue(loop.is_running())
            if sys.platform == 'win32':
                self.assertIsInstance(loop, asyncio.SelectorEventLoop)
        finally:
            _shutdown_isolated_subagent_loop()


if __name__ == '__main__':
    unittest.main()
