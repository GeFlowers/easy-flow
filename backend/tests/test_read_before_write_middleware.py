"""本模块覆盖读取 写入的行为、边界与回归场景，确保既有契约稳定。"""

import hashlib
import posixpath
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest


def _sha(text: str) -> str:
    """准备可控测试资源与状态，供后续断言读取。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_request(name, args, messages=()):
    """准备可控测试资源与状态，供后续断言读取。"""
    runtime = MagicMock()
    runtime.context = {"thread_id": "t-test"}
    return ToolCallRequest(
        tool_call={"name": name, "args": args, "id": "call-1"},
        tool=None,
        state={"messages": list(messages)},
        runtime=runtime,
    )


def _read_marked_message(path, content, tool_call_id="r1"):
    """准备可控测试资源与状态，供后续断言读取。"""
    msg = ToolMessage(content=content[:20], tool_call_id=tool_call_id, name="read_file")
    msg.additional_kwargs["deerflow_read_mark"] = {"path": path, "hash": _sha(content)}
    return msg


def _middleware(files: dict[str, str]):
    """准备可控测试资源与状态，供后续断言读取。"""
    from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware

    def reader(_runtime, path):
        """准备可控测试资源与状态，供后续断言读取。"""
        normalized = posixpath.normpath(path)
        if normalized not in files:
            raise FileNotFoundError(path)
        value = files[normalized]
        if isinstance(value, Exception):
            raise value
        return value

    return ReadBeforeWriteMiddleware(content_reader=reader)


class TestReadCurrentFileContent:
    """集中覆盖当前测试分支与回归边界。"""
    def test_reads_via_sandbox_with_resolution(self):
        """验证沙箱在预期条件及边界场景下的可观察行为，防止相关回归。"""
        from deerflow.sandbox import tools as sandbox_tools

        sandbox = MagicMock()
        sandbox.read_file.return_value = "hello"
        runtime = MagicMock()
        with (
            patch.object(sandbox_tools, "ensure_sandbox_initialized", return_value=sandbox),
            patch.object(sandbox_tools, "ensure_thread_directories_exist"),
            patch.object(sandbox_tools, "is_local_sandbox", return_value=False),
        ):
            assert sandbox_tools.read_current_file_content(runtime, "/mnt/user-data/outputs/report.md") == "hello"
        sandbox.read_file.assert_called_once_with("/mnt/user-data/outputs/report.md")

    def test_propagates_file_not_found(self):
        """验证文件在预期条件及边界场景下的可观察行为，防止相关回归。"""
        from deerflow.sandbox import tools as sandbox_tools

        sandbox = MagicMock()
        sandbox.read_file.side_effect = FileNotFoundError()
        with (
            patch.object(sandbox_tools, "ensure_sandbox_initialized", return_value=sandbox),
            patch.object(sandbox_tools, "ensure_thread_directories_exist"),
            patch.object(sandbox_tools, "is_local_sandbox", return_value=False),
        ):
            with pytest.raises(FileNotFoundError):
                sandbox_tools.read_current_file_content(MagicMock(), "/mnt/user-data/outputs/missing.md")


class TestReadMarkStamping:
    """集中覆盖当前测试分支与回归边界。"""
    def test_read_file_success_stamps_mark(self):
        """验证读取 文件在预期条件及边界场景下的可观察行为，防止相关回归。"""
        mw = _middleware({"/mnt/user-data/outputs/report.md": "v1"})
        request = _make_request("read_file", {"description": "d", "path": "/mnt/user-data/outputs/report.md"})
        handler = MagicMock(return_value=ToolMessage(content="v1", tool_call_id="call-1", name="read_file"))
        result = mw.wrap_tool_call(request, handler)
        mark = result.additional_kwargs["deerflow_read_mark"]
        assert mark == {"path": "/mnt/user-data/outputs/report.md", "hash": _sha("v1")}

    def test_ranged_read_stamps_full_file_hash(self):
        """验证读取 文件在预期条件及边界场景下的可观察行为，防止相关回归。"""
        mw = _middleware({"/mnt/user-data/outputs/report.md": "line1\nline2\nline3"})
        request = _make_request(
            "read_file",
            {"description": "d", "path": "/mnt/user-data/outputs/report.md", "start_line": 3, "end_line": 3},
        )
        handler = MagicMock(return_value=ToolMessage(content="line3", tool_call_id="call-1", name="read_file"))
        result = mw.wrap_tool_call(request, handler)
        assert result.additional_kwargs["deerflow_read_mark"]["hash"] == _sha("line1\nline2\nline3")

    def test_error_tool_message_gets_no_mark(self):
        """验证错误 工具 消息在预期条件及边界场景下的可观察行为，防止相关回归。"""
        mw = _middleware({"/mnt/user-data/outputs/report.md": "v1"})
        request = _make_request("read_file", {"description": "d", "path": "/mnt/user-data/outputs/report.md"})
        handler = MagicMock(return_value=ToolMessage(content="boom", tool_call_id="call-1", name="read_file", status="error"))
        result = mw.wrap_tool_call(request, handler)
        assert "deerflow_read_mark" not in result.additional_kwargs

    def test_reader_failure_means_no_mark(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        mw = _middleware({"/mnt/user-data/outputs/report.md": RuntimeError("sandbox down")})
        request = _make_request("read_file", {"description": "d", "path": "/mnt/user-data/outputs/report.md"})
        handler = MagicMock(return_value=ToolMessage(content="v1", tool_call_id="call-1", name="read_file"))
        result = mw.wrap_tool_call(request, handler)
        assert "deerflow_read_mark" not in result.additional_kwargs

    def test_non_file_tools_untouched(self):
        """验证文件在预期条件及边界场景下的可观察行为，防止相关回归。"""
        mw = _middleware({})
        request = _make_request("bash", {"description": "d", "command": "ls"})
        sentinel = ToolMessage(content="ok", tool_call_id="call-1", name="bash")
        handler = MagicMock(return_value=sentinel)
        assert mw.wrap_tool_call(request, handler) is sentinel


class TestWriteGate:
    """集中覆盖当前测试分支与回归边界。"""
    PATH = "/mnt/user-data/outputs/report.md"

    def test_new_file_write_allowed(self):
        """验证文件 写入在预期条件及边界场景下的可观察行为，防止相关回归。"""
        mw = _middleware({})  # file does not exist
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v1"})
        handler = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))
        result = mw.wrap_tool_call(request, handler)
        handler.assert_called_once()
        assert result.status != "error"

    def test_overwrite_existing_without_read_blocked(self):
        """验证已有 读取在预期条件及边界场景下的可观察行为，防止相关回归。"""
        mw = _middleware({self.PATH: "v1"})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"})
        handler = MagicMock()
        result = mw.wrap_tool_call(request, handler)
        handler.assert_not_called()
        assert isinstance(result, ToolMessage)
        assert result.status == "error"
        assert result.tool_call_id == "call-1"
        assert "read" in result.content.lower()

    def test_append_without_read_blocked(self):
        """验证读取在预期条件及边界场景下的可观察行为，防止相关回归。"""
        mw = _middleware({self.PATH: "v1"})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "more", "append": True})
        handler = MagicMock()
        result = mw.wrap_tool_call(request, handler)
        handler.assert_not_called()
        assert result.status == "error"

    def test_str_replace_without_read_blocked(self):
        """验证替换 读取在预期条件及边界场景下的可观察行为，防止相关回归。"""
        mw = _middleware({self.PATH: "v1"})
        request = _make_request("str_replace", {"description": "d", "path": self.PATH, "old_str": "v1", "new_str": "v2"})
        handler = MagicMock()
        result = mw.wrap_tool_call(request, handler)
        handler.assert_not_called()
        assert result.status == "error"

    def test_str_replace_missing_file_passes_through(self):
        """验证替换 文件在预期条件及边界场景下的可观察行为，防止相关回归。"""
        mw = _middleware({})
        request = _make_request("str_replace", {"description": "d", "path": self.PATH, "old_str": "a", "new_str": "b"})
        native_error = ToolMessage(content="Error: File not found", tool_call_id="call-1", name="str_replace", status="error")
        handler = MagicMock(return_value=native_error)
        assert mw.wrap_tool_call(request, handler) is native_error

    def test_fresh_mark_allows_write(self):
        """验证写入在预期条件及边界场景下的可观察行为，防止相关回归。"""
        mw = _middleware({self.PATH: "v1"})
        messages = [HumanMessage("hi"), AIMessage(""), _read_marked_message(self.PATH, "v1")]
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"}, messages)
        handler = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))
        result = mw.wrap_tool_call(request, handler)
        handler.assert_called_once()
        assert result.status != "error"

    def test_stale_mark_after_modification_blocked(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        mw = _middleware({self.PATH: "v2"})  # file changed since the read of v1
        messages = [_read_marked_message(self.PATH, "v1")]
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v3", "append": True}, messages)
        handler = MagicMock()
        result = mw.wrap_tool_call(request, handler)
        handler.assert_not_called()
        assert result.status == "error"

    def test_newest_mark_wins(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        mw = _middleware({self.PATH: "v2"})
        messages = [_read_marked_message(self.PATH, "v1", "r1"), _read_marked_message(self.PATH, "v2", "r2")]
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v3"}, messages)
        handler = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))
        result = mw.wrap_tool_call(request, handler)
        handler.assert_called_once()
        assert result.status != "error"

    def test_mark_removed_by_summarization_blocks(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        mw = _middleware({self.PATH: "v1"})
        messages = [HumanMessage("Here is a summary of the conversation to date: ...", name="summary")]
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"}, messages)
        handler = MagicMock()
        result = mw.wrap_tool_call(request, handler)
        handler.assert_not_called()
        assert result.status == "error"

    def test_gate_read_failure_fails_open(self):
        """验证读取在预期条件及边界场景下的可观察行为，防止相关回归。"""
        mw = _middleware({self.PATH: RuntimeError("sandbox hiccup")})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"})
        handler = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))
        result = mw.wrap_tool_call(request, handler)
        handler.assert_called_once()
        assert result.status != "error"

    def test_normalized_path_matching(self):
        """验证规范化 路径在预期条件及边界场景下的可观察行为，防止相关回归。"""
        mw = _middleware({self.PATH: "v1"})
        messages = [_read_marked_message(self.PATH, "v1")]
        request = _make_request("write_file", {"description": "d", "path": "/mnt/user-data/outputs/../outputs/report.md", "content": "v2"}, messages)
        handler = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))
        result = mw.wrap_tool_call(request, handler)
        handler.assert_called_once()
        assert result.status != "error"

    def test_blocked_write_has_deerflow_tool_meta(self):
        """验证写入 工具在预期条件及边界场景下的可观察行为，防止相关回归。"""
        from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY

        mw = _middleware({self.PATH: "v1"})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"})
        result = mw.wrap_tool_call(request, MagicMock())
        meta = (result.additional_kwargs or {}).get(TOOL_META_KEY)
        assert meta is not None, "blocked write must carry deerflow_tool_meta"
        assert meta["recoverable_by_model"] is True


class TestAsyncPaths:
    """集中覆盖当前测试分支与回归边界。"""
    PATH = "/mnt/user-data/outputs/report.md"

    def test_async_block(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        import asyncio

        mw = _middleware({self.PATH: "v1"})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"})

        async def handler(_request):
            """准备可控测试资源与状态，供后续断言读取。"""
            raise AssertionError("handler must not run when blocked")

        result = asyncio.run(mw.awrap_tool_call(request, handler))
        assert result.status == "error"

    def test_async_blocked_write_has_deerflow_tool_meta(self):
        """验证写入 工具在预期条件及边界场景下的可观察行为，防止相关回归。"""
        import asyncio

        from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY

        mw = _middleware({self.PATH: "v1"})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"})

        async def handler(_request):
            """准备可控测试资源与状态，供后续断言读取。"""
            raise AssertionError("handler must not run when blocked")

        result = asyncio.run(mw.awrap_tool_call(request, handler))
        meta = (result.additional_kwargs or {}).get(TOOL_META_KEY)
        assert meta is not None, "async blocked write must carry deerflow_tool_meta"
        assert meta["recoverable_by_model"] is True

    def test_async_read_stamps_mark(self):
        """验证读取在预期条件及边界场景下的可观察行为，防止相关回归。"""
        import asyncio

        mw = _middleware({self.PATH: "v1"})
        request = _make_request("read_file", {"description": "d", "path": self.PATH})

        async def handler(_request):
            """准备可控测试资源与状态，供后续断言读取。"""
            return ToolMessage(content="v1", tool_call_id="call-1", name="read_file")

        result = asyncio.run(mw.awrap_tool_call(request, handler))
        assert result.additional_kwargs["deerflow_read_mark"]["hash"] == _sha("v1")

    def test_async_allowed_write_calls_handler(self):
        """验证写入在预期条件及边界场景下的可观察行为，防止相关回归。"""
        import asyncio

        mw = _middleware({self.PATH: "v1"})
        messages = [_read_marked_message(self.PATH, "v1")]
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"}, messages)

        async def handler(_request):
            """准备可控测试资源与状态，供后续断言读取。"""
            return ToolMessage(content="OK", tool_call_id="call-1", name="write_file")

        result = asyncio.run(mw.awrap_tool_call(request, handler))
        assert result.status != "error"


def _wiring_app_config(**overrides):
    """准备可控测试资源与状态，供后续断言读取。"""
    from deerflow.config.app_config import AppConfig
    from deerflow.config.sandbox_config import SandboxConfig

    return AppConfig(sandbox=SandboxConfig(use="test"), **overrides)


class TestChainWiring:
    """集中覆盖当前测试分支与回归边界。"""
    def test_enabled_by_default_in_runtime_chain(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware
        from deerflow.agents.middlewares.sandbox_audit_middleware import SandboxAuditMiddleware
        from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware, build_lead_runtime_middlewares

        middlewares = build_lead_runtime_middlewares(app_config=_wiring_app_config())
        types = [type(m) for m in middlewares]
        assert ReadBeforeWriteMiddleware in types
        assert types.index(SandboxAuditMiddleware) < types.index(ReadBeforeWriteMiddleware) < types.index(ToolErrorHandlingMiddleware)

    def test_disabled_removes_middleware(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware
        from deerflow.agents.middlewares.tool_error_handling_middleware import build_lead_runtime_middlewares
        from deerflow.config.read_before_write_config import ReadBeforeWriteConfig

        app_config = _wiring_app_config(read_before_write=ReadBeforeWriteConfig(enabled=False))
        middlewares = build_lead_runtime_middlewares(app_config=app_config)
        assert ReadBeforeWriteMiddleware not in [type(m) for m in middlewares]

    def test_subagents_get_the_gate_too(self):
        """验证获取在预期条件及边界场景下的可观察行为，防止相关回归。"""
        from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware
        from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares

        middlewares = build_subagent_runtime_middlewares(app_config=_wiring_app_config())
        assert ReadBeforeWriteMiddleware in [type(m) for m in middlewares]


class TestErrorStringSandboxes:
    """集中覆盖当前测试分支与回归边界。"""

    PATH = "/mnt/user-data/outputs/report.md"

    def _error_string_middleware(self, files):
        """准备可控测试资源与状态，供后续断言读取。"""
        from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware

        def reader(_runtime, path):
            """准备可控测试资源与状态，供后续断言读取。"""
            normalized = posixpath.normpath(path)
            if normalized not in files:
                return f"Error: can't read file {path}: file not found"
            return files[normalized]

        return ReadBeforeWriteMiddleware(content_reader=reader)

    def test_new_file_creation_not_blocked(self):
        """验证文件在预期条件及边界场景下的可观察行为，防止相关回归。"""
        mw = self._error_string_middleware({})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v1"})
        handler = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))
        result = mw.wrap_tool_call(request, handler)
        handler.assert_called_once()
        assert result.status != "error"

    def test_no_mark_when_reread_returns_error_string(self):
        """验证错误在预期条件及边界场景下的可观察行为，防止相关回归。"""
        mw = self._error_string_middleware({})
        request = _make_request("read_file", {"description": "d", "path": self.PATH})
        handler = MagicMock(return_value=ToolMessage(content="v1", tool_call_id="call-1", name="read_file"))
        result = mw.wrap_tool_call(request, handler)
        assert "deerflow_read_mark" not in result.additional_kwargs

    def test_existing_file_still_gated(self):
        """验证已有 文件在预期条件及边界场景下的可观察行为，防止相关回归。"""
        mw = self._error_string_middleware({self.PATH: "v1"})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"})
        handler = MagicMock()
        result = mw.wrap_tool_call(request, handler)
        handler.assert_not_called()
        assert result.status == "error"

    def test_existing_file_read_still_marked_and_write_allowed(self):
        """验证已有 文件 读取 写入在预期条件及边界场景下的可观察行为，防止相关回归。"""
        mw = self._error_string_middleware({self.PATH: "v1"})
        read_request = _make_request("read_file", {"description": "d", "path": self.PATH})
        read_handler = MagicMock(return_value=ToolMessage(content="v1", tool_call_id="r1", name="read_file"))
        read_result = mw.wrap_tool_call(read_request, read_handler)
        assert read_result.additional_kwargs["deerflow_read_mark"]["hash"] == _sha("v1")

        write_request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"}, [read_result])
        write_handler = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))
        result = mw.wrap_tool_call(write_request, write_handler)
        write_handler.assert_called_once()
        assert result.status != "error"


class TestSamePathSerialization:
    """集中覆盖当前测试分支与回归边界。"""

    PATH = "/mnt/user-data/outputs/report.md"

    def test_parallel_appends_exactly_one_lands(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        import asyncio

        files = {self.PATH: "v1"}
        mw = _middleware(files)
        messages = [_read_marked_message(self.PATH, "v1")]

        def make_handler(suffix):
            """准备可控测试资源与状态，供后续断言读取。"""
            async def handler(_request):
                """准备可控测试资源与状态，供后续断言读取。"""
                await asyncio.sleep(0.02)
                files[self.PATH] = files[self.PATH] + suffix
                return ToolMessage(content="OK", tool_call_id="call-1", name="write_file")

            return handler

        async def run():
            """处理运行相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
            return await asyncio.gather(
                mw.awrap_tool_call(
                    _make_request("write_file", {"description": "d", "path": self.PATH, "content": "A", "append": True}, messages),
                    make_handler("A"),
                ),
                mw.awrap_tool_call(
                    _make_request("write_file", {"description": "d", "path": self.PATH, "content": "B", "append": True}, messages),
                    make_handler("B"),
                ),
            )

        results = asyncio.run(run())
        assert sorted(r.status for r in results) == ["error", "success"]
        assert files[self.PATH] in ("v1A", "v1B")

    def test_read_mark_matches_content_shown_to_model(self):
        """验证读取 模型在预期条件及边界场景下的可观察行为，防止相关回归。"""
        import asyncio

        files = {self.PATH: "v1"}
        mw = _middleware(files)
        write_messages = [_read_marked_message(self.PATH, "v1")]

        async def read_handler(_request):
            """处理读取相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
            snapshot = files[self.PATH]
            await asyncio.sleep(0.03)
            return ToolMessage(content=snapshot, tool_call_id="r-call", name="read_file")

        async def write_handler(_request):
            """处理写入相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
            files[self.PATH] = "v2"
            return ToolMessage(content="OK", tool_call_id="w-call", name="write_file")

        async def run():
            """处理运行相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
            read_task = asyncio.create_task(mw.awrap_tool_call(_make_request("read_file", {"description": "d", "path": self.PATH}), read_handler))
            await asyncio.sleep(0.01)
            write_task = asyncio.create_task(
                mw.awrap_tool_call(
                    _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"}, write_messages),
                    write_handler,
                )
            )
            return await asyncio.gather(read_task, write_task)

        read_result, _write_result = asyncio.run(run())
        mark = read_result.additional_kwargs.get("deerflow_read_mark")
        assert mark is not None
        assert mark["hash"] == _sha(read_result.content)
