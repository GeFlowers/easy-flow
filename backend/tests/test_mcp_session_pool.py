"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

import asyncio
import logging
import stat
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.mcp.session_pool import MCPSessionPool, get_session_pool, reset_session_pool


@pytest.fixture(autouse=True)
def _reset_pool():
    """提供隔离的测试夹具：创建调用用例所需依赖，并保持既定资源回收边界。"""
    reset_session_pool()
    yield
    reset_session_pool()


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_session_creates_new():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    pool = MCPSessionPool()

    mock_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm):
        session = await pool.get_session("server", "thread-1", {"transport": "stdio", "command": "x", "args": []})

    assert session is mock_session
    mock_session.initialize.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_session_reuses_existing():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    pool = MCPSessionPool()

    mock_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm):
        s1 = await pool.get_session("server", "thread-1", {"transport": "stdio", "command": "x", "args": []})
        s2 = await pool.get_session("server", "thread-1", {"transport": "stdio", "command": "x", "args": []})

    assert s1 is s2
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert mock_cm.__aenter__.await_count == 1


@pytest.mark.asyncio
async def test_different_scope_creates_different_session():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    pool = MCPSessionPool()

    sessions = [AsyncMock(), AsyncMock()]
    idx = 0

    class CmFactory:
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            self.enter_count = 0

        async def __aenter__(self):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            nonlocal idx
            s = sessions[idx]
            idx += 1
            self.enter_count += 1
            return s

        async def __aexit__(self, *args):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            return False

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=lambda *a, **kw: CmFactory()):
        s1 = await pool.get_session("server", "thread-1", {"transport": "stdio", "command": "x", "args": []})
        s2 = await pool.get_session("server", "thread-2", {"transport": "stdio", "command": "x", "args": []})

    assert s1 is not s2
    assert s1 is sessions[0]
    assert s2 is sessions[1]


@pytest.mark.asyncio
async def test_lru_eviction():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    pool = MCPSessionPool()
    pool.MAX_SESSIONS = 2

    class CmFactory:
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            self.closed = False

        async def __aenter__(self):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            return AsyncMock()

        async def __aexit__(self, *args):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            self.closed = True
            return False

    cms: list[CmFactory] = []

    def make_cm(*a, **kw):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        cm = CmFactory()
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        await pool.get_session("s", "t1", {"transport": "stdio", "command": "x", "args": []})
        await pool.get_session("s", "t2", {"transport": "stdio", "command": "x", "args": []})
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        await pool.get_session("s", "t3", {"transport": "stdio", "command": "x", "args": []})

    assert cms[0].closed is True
    assert cms[1].closed is False
    assert cms[2].closed is False


@pytest.mark.asyncio
async def test_close_scope():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    pool = MCPSessionPool()

    class CmFactory:
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            self.closed = False

        async def __aenter__(self):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            return AsyncMock()

        async def __aexit__(self, *args):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            self.closed = True
            return False

    cms: list[CmFactory] = []

    def make_cm(*a, **kw):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        cm = CmFactory()
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        await pool.get_session("s", "t1", {"transport": "stdio", "command": "x", "args": []})
        await pool.get_session("s", "t2", {"transport": "stdio", "command": "x", "args": []})

    await pool.close_scope("t1")

    assert cms[0].closed is True
    assert cms[1].closed is False

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert ("s", "t2") in pool._entries


@pytest.mark.asyncio
async def test_close_all():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    pool = MCPSessionPool()

    class CmFactory:
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            self.closed = False

        async def __aenter__(self):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            return AsyncMock()

        async def __aexit__(self, *args):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            self.closed = True
            return False

    cms: list[CmFactory] = []

    def make_cm(*a, **kw):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        cm = CmFactory()
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        await pool.get_session("s1", "t1", {"transport": "stdio", "command": "x", "args": []})
        await pool.get_session("s2", "t2", {"transport": "stdio", "command": "x", "args": []})

    await pool.close_all()

    assert all(cm.closed for cm in cms)
    assert len(pool._entries) == 0


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


def test_get_session_pool_singleton():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    p1 = get_session_pool()
    p2 = get_session_pool()
    assert p1 is p2


def test_reset_session_pool():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    p1 = get_session_pool()
    reset_session_pool()
    p2 = get_session_pool()
    assert p1 is not p2


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_pool_tool_wrapping():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        url: str = Field(..., description="url")

    original_tool = StructuredTool(
        name="playwright_navigate",
        description="Navigate browser",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    connection = {"transport": "stdio", "command": "pw", "args": []}

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm):
        wrapped = _make_session_pool_tool(original_tool, "playwright", connection)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        mock_runtime = MagicMock()
        mock_runtime.context = {"thread_id": "thread-42"}
        mock_runtime.config = {}

        await wrapped.coroutine(runtime=mock_runtime, url="https://example.com")

    mock_session.call_tool.assert_awaited_once_with("navigate", {"url": "https://example.com"})


@pytest.mark.asyncio
async def test_session_pool_tool_pins_cwd_and_temp_env(tmp_path):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.config.paths import Paths
    from deerflow.mcp.tools import _MCP_TMP_SUBDIR, _make_session_pool_tool

    class Args(BaseModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        url: str = Field(..., description="url")

    original_tool = StructuredTool(
        name="playwright_navigate",
        description="Navigate browser",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    paths = Paths(tmp_path)
    connection = {"transport": "stdio", "command": "pw", "args": [], "env": {"KEEP": "1"}}
    mock_runtime = MagicMock()
    mock_runtime.context = {"thread_id": "thread-42", "user_id": "user-7"}
    mock_runtime.config = {}

    with (
        patch("deerflow.mcp.tools.get_paths", return_value=paths),
        patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm) as create_session,
    ):
        wrapped = _make_session_pool_tool(original_tool, "playwright", connection)
        await wrapped.coroutine(runtime=mock_runtime, url="https://example.com")

    session_connection = create_session.call_args.args[0]
    workspace = paths.sandbox_work_dir("thread-42", user_id="user-7")
    tmp_dir = workspace / _MCP_TMP_SUBDIR

    assert session_connection["cwd"] == str(workspace)
    assert session_connection["env"]["KEEP"] == "1"
    assert session_connection["env"]["TMPDIR"] == str(tmp_dir)
    assert session_connection["env"]["TMP"] == str(tmp_dir)
    assert session_connection["env"]["TEMP"] == str(tmp_dir)
    assert tmp_dir.is_dir()
    assert stat.S_IMODE(tmp_dir.stat().st_mode) == 0o700


@pytest.mark.asyncio
async def test_session_pool_tool_does_not_override_explicit_tmpdir(tmp_path):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.config.paths import Paths
    from deerflow.mcp.tools import _MCP_TMP_SUBDIR, _make_session_pool_tool

    class Args(BaseModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        url: str = Field(..., description="url")

    original_tool = StructuredTool(
        name="playwright_navigate",
        description="Navigate browser",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    paths = Paths(tmp_path)
    connection = {"transport": "stdio", "command": "pw", "args": [], "env": {"TMPDIR": "/operator/tmp"}}
    mock_runtime = MagicMock()
    mock_runtime.context = {"thread_id": "thread-42", "user_id": "user-7"}
    mock_runtime.config = {}

    with (
        patch("deerflow.mcp.tools.get_paths", return_value=paths),
        patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm) as create_session,
    ):
        wrapped = _make_session_pool_tool(original_tool, "playwright", connection)
        await wrapped.coroutine(runtime=mock_runtime, url="https://example.com")

    session_connection = create_session.call_args.args[0]
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert session_connection["env"]["TMPDIR"] == "/operator/tmp"
    assert session_connection["env"]["TMP"].endswith(_MCP_TMP_SUBDIR)


@pytest.mark.asyncio
async def test_session_pool_tool_does_not_override_explicit_cwd(tmp_path):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.config.paths import Paths
    from deerflow.mcp.tools import _MCP_TMP_SUBDIR, _make_session_pool_tool

    class Args(BaseModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        url: str = Field(..., description="url")

    original_tool = StructuredTool(
        name="playwright_navigate",
        description="Navigate browser",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    operator_cwd = str(tmp_path / "operator-cwd")
    paths = Paths(tmp_path)
    connection = {"transport": "stdio", "command": "pw", "args": [], "cwd": operator_cwd}
    mock_runtime = MagicMock()
    mock_runtime.context = {"thread_id": "thread-42", "user_id": "user-7"}
    mock_runtime.config = {}

    with (
        patch("deerflow.mcp.tools.get_paths", return_value=paths),
        patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm) as create_session,
    ):
        wrapped = _make_session_pool_tool(original_tool, "playwright", connection)
        await wrapped.coroutine(runtime=mock_runtime, url="https://example.com")

    session_connection = create_session.call_args.args[0]
    workspace = paths.sandbox_work_dir("thread-42", user_id="user-7")
    tmp_dir = workspace / _MCP_TMP_SUBDIR

    assert session_connection["cwd"] == operator_cwd
    assert session_connection["env"]["TMPDIR"] == str(tmp_dir)


@pytest.mark.asyncio
async def test_session_pool_tool_skips_fs_work_for_non_stdio_transport(tmp_path):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.config.paths import Paths
    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        url: str = Field(..., description="url")

    original_tool = StructuredTool(
        name="srv_act",
        description="test",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    paths = Paths(tmp_path)
    connection = {"transport": "sse", "url": "http://localhost:9000/sse", "env": {"KEEP": "1"}}
    mock_runtime = MagicMock()
    mock_runtime.context = {"thread_id": "thread-42", "user_id": "user-7"}
    mock_runtime.config = {}

    with (
        patch("deerflow.mcp.tools.get_paths", return_value=paths) as get_paths,
        patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm) as create_session,
    ):
        wrapped = _make_session_pool_tool(original_tool, "srv", connection)
        await wrapped.coroutine(runtime=mock_runtime, url="https://example.com")

    session_connection = create_session.call_args.args[0]
    assert "cwd" not in session_connection
    assert session_connection["env"] == {"KEEP": "1"}
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    get_paths.assert_not_called()
    assert not paths.sandbox_work_dir("thread-42", user_id="user-7").exists()


@pytest.mark.asyncio
async def test_session_pool_tool_skips_after_walk_when_no_text_content(tmp_path):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.config.paths import Paths
    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        url: str = Field(..., description="url")

    original_tool = StructuredTool(
        name="playwright_navigate",
        description="Navigate browser",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    from mcp.types import ImageContent

    image_result = MagicMock(content=[ImageContent(type="image", data="QUJD", mimeType="image/png")], isError=False, structuredContent=None)
    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=image_result)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    paths = Paths(tmp_path)
    connection = {"transport": "stdio", "command": "pw", "args": []}
    mock_runtime = MagicMock()
    mock_runtime.context = {"thread_id": "thread-42", "user_id": "user-7"}
    mock_runtime.config = {}

    with (
        patch("deerflow.mcp.tools.get_paths", return_value=paths),
        patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm),
        patch("deerflow.mcp.tools._changed_workspace_files") as changed_files,
    ):
        wrapped = _make_session_pool_tool(original_tool, "playwright", connection)
        await wrapped.coroutine(runtime=mock_runtime, url="https://example.com")

    changed_files.assert_not_called()


@pytest.mark.asyncio
async def test_session_pool_tool_runs_after_walk_when_text_content_present(tmp_path):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.config.paths import Paths
    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        url: str = Field(..., description="url")

    original_tool = StructuredTool(
        name="playwright_navigate",
        description="Navigate browser",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    from mcp.types import TextContent

    text_result = MagicMock(content=[TextContent(type="text", text="Saved as shot.png")], isError=False, structuredContent=None)
    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=text_result)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    paths = Paths(tmp_path)
    connection = {"transport": "stdio", "command": "pw", "args": []}
    mock_runtime = MagicMock()
    mock_runtime.context = {"thread_id": "thread-42", "user_id": "user-7"}
    mock_runtime.config = {}

    with (
        patch("deerflow.mcp.tools.get_paths", return_value=paths),
        patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm),
        patch("deerflow.mcp.tools._changed_workspace_files", return_value=[]) as changed_files,
    ):
        wrapped = _make_session_pool_tool(original_tool, "playwright", connection)
        await wrapped.coroutine(runtime=mock_runtime, url="https://example.com")

    changed_files.assert_called_once()


@pytest.mark.asyncio
async def test_session_pool_tool_forwards_interceptor_headers():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        x: int = Field(..., description="x")

    original_tool = StructuredTool(
        name="srv_act",
        description="test",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    async def header_interceptor(request, handler):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return await handler(request.override(headers={"X-User-Id": "u-42"}))

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm):
        wrapped = _make_session_pool_tool(
            original_tool,
            "srv",
            {"transport": "stdio", "command": "x", "args": []},
            tool_interceptors=[header_interceptor],
        )
        await wrapped.coroutine(runtime=None, x=1)

    mock_session.call_tool.assert_awaited_once_with("act", {"x": 1}, meta={"headers": {"X-User-Id": "u-42"}})


@pytest.mark.asyncio
async def test_session_pool_tool_no_headers_omits_meta():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        x: int = Field(..., description="x")

    original_tool = StructuredTool(
        name="srv_act",
        description="test",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    async def passthrough_interceptor(request, handler):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return await handler(request)

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm):
        wrapped = _make_session_pool_tool(
            original_tool,
            "srv",
            {"transport": "stdio", "command": "x", "args": []},
            tool_interceptors=[passthrough_interceptor],
        )
        await wrapped.coroutine(runtime=None, x=1)

    mock_session.call_tool.assert_awaited_once_with("act", {"x": 1})


@pytest.mark.asyncio
async def test_session_pool_tool_ignores_unsupported_header_type(caplog):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        x: int = Field(..., description="x")

    class TruthyHeaders:
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __bool__(self) -> bool:
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            return True

    original_tool = StructuredTool(
        name="srv_act",
        description="test",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    async def invalid_header_interceptor(request, handler):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return await handler(request.override(headers=TruthyHeaders()))

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm):
        wrapped = _make_session_pool_tool(
            original_tool,
            "srv",
            {"transport": "stdio", "command": "x", "args": []},
            tool_interceptors=[invalid_header_interceptor],
        )
        await wrapped.coroutine(runtime=None, x=1)

    mock_session.call_tool.assert_awaited_once_with("act", {"x": 1})
    assert "unsupported type" in caplog.text


@pytest.mark.asyncio
async def test_session_pool_tool_extracts_thread_id():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        x: int = Field(..., description="x")

    original_tool = StructuredTool(
        name="server_tool",
        description="test",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm):
        wrapped = _make_session_pool_tool(original_tool, "server", {"transport": "stdio", "command": "x", "args": []})

        mock_runtime = MagicMock()
        mock_runtime.context = {}
        mock_runtime.config = {"configurable": {"thread_id": "from-config"}}

        await wrapped.coroutine(runtime=mock_runtime, x=1)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    pool = get_session_pool()
    assert ("server", "test-user-autouse:from-config") in pool._entries


@pytest.mark.asyncio
async def test_session_pool_tool_default_scope():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        x: int = Field(..., description="x")

    original_tool = StructuredTool(
        name="server_tool",
        description="test",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm):
        wrapped = _make_session_pool_tool(original_tool, "server", {"transport": "stdio", "command": "x", "args": []})

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        await wrapped.coroutine(runtime=None, x=1)

    pool = get_session_pool()
    assert ("server", "test-user-autouse:default") in pool._entries


@pytest.mark.asyncio
async def test_session_pool_tool_get_config_fallback():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        x: int = Field(..., description="x")

    original_tool = StructuredTool(
        name="server_tool",
        description="test",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    fake_config = {"configurable": {"thread_id": "from-langgraph-config"}}

    with (
        patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm),
        patch("deerflow.mcp.tools.get_config", return_value=fake_config),
    ):
        wrapped = _make_session_pool_tool(original_tool, "server", {"transport": "stdio", "command": "x", "args": []})

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        await wrapped.coroutine(runtime=None, x=1)

    pool = get_session_pool()
    assert ("server", "test-user-autouse:from-langgraph-config") in pool._entries


def test_session_pool_tool_sync_wrapper_path_is_safe():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.mcp.tools import _make_session_pool_tool
    from deerflow.tools.sync import make_sync_tool_wrapper

    class Args(BaseModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        url: str = Field(..., description="url")

    original_tool = StructuredTool(
        name="playwright_navigate",
        description="Navigate browser",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    connection = {"transport": "stdio", "command": "pw", "args": []}

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm):
        wrapped = _make_session_pool_tool(original_tool, "playwright", connection)
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        wrapped.func = make_sync_tool_wrapper(wrapped.coroutine, wrapped.name)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        wrapped.func(url="https://example.com")

    mock_session.call_tool.assert_called_once_with("navigate", {"url": "https://example.com"})


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_transport_tools_not_pooled():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.mcp.tools import get_mcp_tools

    class Args(BaseModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        query: str = Field(..., description="query")

    http_tool = StructuredTool(
        name="myserver_search",
        description="Search tool",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    stdio_tool = StructuredTool(
        name="playwright_navigate",
        description="Navigate browser",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    extensions_config = MagicMock()
    extensions_config.get_enabled_mcp_servers.return_value = {
        "myserver": MagicMock(type="http", url="http://localhost:8000/mcp", headers=None, command=None, args=[], env=None),
        "playwright": MagicMock(type="stdio", command="npx", args=["-y", "@anthropic/mcp-server-playwright"], env=None, url=None, headers=None),
    }
    extensions_config.model_extra = {}

    servers_config = {
        "myserver": {"transport": "http", "url": "http://localhost:8000/mcp"},
        "playwright": {"transport": "stdio", "command": "npx", "args": ["-y", "@anthropic/mcp-server-playwright"]},
    }

    with (
        patch("deerflow.mcp.tools.ExtensionsConfig.from_file", return_value=extensions_config),
        patch("deerflow.mcp.tools.build_servers_config", return_value=servers_config),
        patch("deerflow.mcp.tools.get_initial_oauth_headers", return_value={}),
        patch("deerflow.mcp.tools.build_oauth_tool_interceptor", return_value=None),
        patch("langchain_mcp_adapters.client.MultiServerMCPClient") as MockClient,
        patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm),
    ):
        mock_client_instance = MockClient.return_value

        async def get_tools_for_server(*, server_name: str | None = None):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            if server_name == "myserver":
                return [http_tool]
            if server_name == "playwright":
                return [stdio_tool]
            raise AssertionError(f"unexpected server_name: {server_name}")

        mock_client_instance.get_tools = AsyncMock(side_effect=get_tools_for_server)

        tools = await get_mcp_tools()

    pool = get_session_pool()
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert list(pool._entries.keys()) == []

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    http_tools = [t for t in tools if t.name == "myserver_search"]
    assert len(http_tools) == 1
    assert http_tools[0].coroutine is http_tool.coroutine

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    stdio_tools = [t for t in tools if t.name == "playwright_navigate"]
    assert len(stdio_tools) == 1
    assert stdio_tools[0].coroutine is not stdio_tool.coroutine


@pytest.mark.asyncio
async def test_non_stdio_tool_call_timeout_warns_that_it_is_ignored(caplog):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.config.extensions_config import McpServerConfig
    from deerflow.mcp.tools import get_mcp_tools

    class Args(BaseModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        query: str = Field(..., description="query")

    http_tool = StructuredTool(
        name="remote_search",
        description="Search tool",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    server_cfg = McpServerConfig(
        type="http",
        url="https://example.com/mcp",
        tool_call_timeout=30.0,
    )
    extensions_config = MagicMock()
    extensions_config.get_enabled_mcp_servers.return_value = {"remote": server_cfg}
    extensions_config.mcp_servers = {"remote": server_cfg}
    extensions_config.model_extra = {}

    servers_config = {
        "remote": {"transport": "http", "url": "https://example.com/mcp"},
    }

    with (
        patch("deerflow.mcp.tools.ExtensionsConfig.from_file", return_value=extensions_config),
        patch("deerflow.mcp.tools.build_servers_config", return_value=servers_config),
        patch("deerflow.mcp.tools.get_initial_oauth_headers", return_value={}),
        patch("deerflow.mcp.tools.build_oauth_tool_interceptor", return_value=None),
        patch("langchain_mcp_adapters.client.MultiServerMCPClient") as MockClient,
        caplog.at_level(logging.WARNING, logger="deerflow.mcp.tools"),
    ):
        mock_client_instance = MockClient.return_value
        mock_client_instance.get_tools = AsyncMock(return_value=[http_tool])

        tools = await get_mcp_tools()

    assert tools == [http_tool]
    assert any(record.levelno == logging.WARNING and "remote" in record.getMessage() and "tool_call_timeout" in record.getMessage() and "stdio" in record.getMessage() for record in caplog.records)


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stdio_tool_call_timeout_does_not_raise_typeerror():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.config.extensions_config import McpServerConfig
    from deerflow.mcp.tools import get_mcp_tools

    class Args(BaseModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        query: str = Field(..., description="query")

    stdio_tool = StructuredTool(
        name="biomcp_search",
        description="Search biomedical data",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    server_cfg = McpServerConfig(
        type="stdio",
        command="biomcp",
        args=["serve"],
        tool_call_timeout=60.0,
    )

    extensions_config = MagicMock()
    extensions_config.get_enabled_mcp_servers.return_value = {"biomcp": server_cfg}
    extensions_config.mcp_servers = {"biomcp": server_cfg}
    extensions_config.model_extra = {}

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    servers_config = {
        "biomcp": {"transport": "stdio", "command": "biomcp", "args": ["serve"]},
    }

    with (
        patch("deerflow.mcp.tools.ExtensionsConfig.from_file", return_value=extensions_config),
        patch("deerflow.mcp.tools.build_servers_config", return_value=servers_config),
        patch("deerflow.mcp.tools.get_initial_oauth_headers", return_value={}),
        patch("deerflow.mcp.tools.build_oauth_tool_interceptor", return_value=None),
        patch("langchain_mcp_adapters.client.MultiServerMCPClient") as MockClient,
        patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm),
    ):
        mock_client_instance = MockClient.return_value
        mock_client_instance.get_tools = AsyncMock(return_value=[stdio_tool])

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        tools = await get_mcp_tools()

    assert len(tools) == 1
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert tools[0].coroutine is not stdio_tool.coroutine

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert "tool_call_timeout" not in servers_config["biomcp"]


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


class _CancelScopeCm:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""

    def __init__(self) -> None:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        self.enter_task: object | None = None
        self.closed = False

    async def __aenter__(self):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        self.enter_task = asyncio.current_task()
        return AsyncMock()

    async def __aexit__(self, *args):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        if asyncio.current_task() is not self.enter_task:
            raise RuntimeError("Attempted to exit cancel scope in a different task than it was entered in")
        self.closed = True
        return False


async def _get_session_in_own_task(pool, *args):
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    return await asyncio.create_task(pool.get_session(*args))


@pytest.mark.asyncio
async def test_close_all_does_not_cross_tasks():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    pool = MCPSessionPool()
    cms: list[_CancelScopeCm] = []

    def make_cm(*a, **kw):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        cm = _CancelScopeCm()
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        await _get_session_in_own_task(pool, "s1", "t1", {"transport": "stdio", "command": "x", "args": []})
        await _get_session_in_own_task(pool, "s2", "t2", {"transport": "stdio", "command": "x", "args": []})

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    await pool.close_all()

    assert all(cm.closed for cm in cms)
    assert len(pool._entries) == 0


@pytest.mark.asyncio
async def test_close_scope_does_not_cross_tasks():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    pool = MCPSessionPool()
    cms: list[_CancelScopeCm] = []

    def make_cm(*a, **kw):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        cm = _CancelScopeCm()
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        await _get_session_in_own_task(pool, "s", "t1", {"transport": "stdio", "command": "x", "args": []})
        await _get_session_in_own_task(pool, "s", "t2", {"transport": "stdio", "command": "x", "args": []})

    await pool.close_scope("t1")

    assert cms[0].closed is True
    assert cms[1].closed is False
    assert ("s", "t2") in pool._entries


@pytest.mark.asyncio
async def test_lru_eviction_does_not_cross_tasks():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    pool = MCPSessionPool()
    pool.MAX_SESSIONS = 2
    cms: list[_CancelScopeCm] = []

    def make_cm(*a, **kw):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        cm = _CancelScopeCm()
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        await _get_session_in_own_task(pool, "s", "t1", {"transport": "stdio", "command": "x", "args": []})
        await _get_session_in_own_task(pool, "s", "t2", {"transport": "stdio", "command": "x", "args": []})
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        await _get_session_in_own_task(pool, "s", "t3", {"transport": "stdio", "command": "x", "args": []})

    assert cms[0].closed is True
    assert cms[1].closed is False
    assert cms[2].closed is False


def test_close_all_sync_across_loops_does_not_cross_tasks():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    pool = MCPSessionPool()
    cms: list[_CancelScopeCm] = []

    def make_cm(*a, **kw):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        cm = _CancelScopeCm()
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        asyncio.run(pool.get_session("s", "t1", {"transport": "stdio", "command": "x", "args": []}))
        asyncio.run(pool.get_session("s", "t2", {"transport": "stdio", "command": "x", "args": []}))

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    pool.close_all_sync()

    assert len(pool._entries) == 0


def test_get_session_replaces_session_from_closed_loop():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    pool = MCPSessionPool()
    cms: list[_CancelScopeCm] = []

    def make_cm(*a, **kw):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        cm = _CancelScopeCm()
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        asyncio.run(pool.get_session("s", "t1", {"transport": "stdio", "command": "x", "args": []}))
        assert ("s", "t1") in pool._entries

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        session = asyncio.run(pool.get_session("s", "t1", {"transport": "stdio", "command": "x", "args": []}))

    assert session is not None
    assert len(cms) == 2
    assert pool._entries[("s", "t1")][0] is session


class _BlockingInitCm:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""

    def __init__(self, gate: asyncio.Event) -> None:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        self._gate = gate
        self.entered = False
        self.closed = False

    async def __aenter__(self):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        self.entered = True
        session = MagicMock()
        session.initialize = self._initialize
        return session

    async def _initialize(self):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        await self._gate.wait()

    async def __aexit__(self, *args):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        self.closed = True
        return False


@pytest.mark.asyncio
async def test_get_session_cancelled_while_initializing_does_not_leak():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    pool = MCPSessionPool()
    gate = asyncio.Event()
    cms: list[_BlockingInitCm] = []

    def make_cm(*a, **kw):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        cm = _BlockingInitCm(gate)
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        call = asyncio.create_task(pool.get_session("s", "t1", {"transport": "stdio", "command": "x", "args": []}))
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        await asyncio.sleep(0.01)
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        gate.set()
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        for _ in range(10):
            if cms and cms[0].closed:
                break
            await asyncio.sleep(0.01)

    assert len(cms) == 1
    assert cms[0].entered is True
    assert cms[0].closed is True, "owner task must run __aexit__ after cancellation"
    assert len(pool._entries) == 0

    current = asyncio.current_task()
    leaked = [t for t in asyncio.all_tasks() if t is not current and not t.done() and "_run_session" in str(t.get_coro())]
    assert not leaked, "owner task must not be left pending after cancellation"


class _InitFailCm:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""

    def __init__(self) -> None:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        self.entered = False
        self.exit_started = False
        self.closed = False

    async def __aenter__(self):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        self.entered = True
        session = MagicMock()
        session.initialize = self._initialize
        return session

    async def _initialize(self):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        raise RuntimeError("init boom")

    async def __aexit__(self, *args):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        self.exit_started = True
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        await asyncio.sleep(0.02)
        self.closed = True
        return False


@pytest.mark.asyncio
async def test_get_session_init_failure_runs_full_cleanup():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    pool = MCPSessionPool()
    cms: list[_InitFailCm] = []

    def make_cm(*a, **kw):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        cm = _InitFailCm()
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        with pytest.raises(RuntimeError, match="init boom"):
            await pool.get_session("s", "t1", {"transport": "stdio", "command": "x", "args": []})

    assert len(cms) == 1
    assert cms[0].entered is True
    assert cms[0].exit_started is True
    assert cms[0].closed is True, "__aexit__ must run to completion, not be interrupted"
    assert len(pool._entries) == 0
    assert len(pool._inflight) == 0


@pytest.mark.asyncio
async def test_concurrent_get_session_same_key_creates_single_session():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    pool = MCPSessionPool()
    gate = asyncio.Event()
    cms: list[_BlockingInitCm] = []

    def make_cm(*a, **kw):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        cm = _BlockingInitCm(gate)
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        conn = {"transport": "stdio", "command": "x", "args": []}
        t1 = asyncio.create_task(pool.get_session("s", "same", conn))
        t2 = asyncio.create_task(pool.get_session("s", "same", conn))
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        await asyncio.sleep(0.02)
        gate.set()
        s1, s2 = await asyncio.gather(t1, t2)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert len(cms) == 1, "concurrent same-key calls must not create duplicate sessions"
    assert s1 is s2
    assert len(pool._entries) == 1
    assert len(pool._inflight) == 0


@pytest.mark.asyncio
async def test_close_all_during_in_flight_creation_does_not_resurrect_session():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    pool = MCPSessionPool()
    gate = asyncio.Event()
    cms: list[_BlockingInitCm] = []

    def make_cm(*a, **kw):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        cm = _BlockingInitCm(gate)
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        conn = {"transport": "stdio", "command": "x", "args": []}
        call = asyncio.create_task(pool.get_session("s", "t1", conn))
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        await asyncio.sleep(0.01)
        assert ("s", "t1") in pool._inflight

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        await pool.close_all()

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert len(pool._inflight) == 0
        assert len(pool._entries) == 0

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        gate.set()
        with pytest.raises(asyncio.CancelledError):
            await call

    assert len(pool._entries) == 0
    assert len(pool._inflight) == 0
    assert cms[0].closed is True, "in-flight session's __aexit__ must run on teardown"

    current = asyncio.current_task()
    leaked = [t for t in asyncio.all_tasks() if t is not current and not t.done() and "_run_session" in str(t.get_coro())]
    assert not leaked, "in-flight owner task must not leak after close_all"


def test_get_session_cross_loop_in_flight_does_not_raise_assertion():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    pool = MCPSessionPool()
    cms: list[_CancelScopeCm] = []

    def make_cm(*a, **kw):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        cm = _CancelScopeCm()
        cms.append(cm)
        return cm

    conn = {"transport": "stdio", "command": "x", "args": []}
    results: list[object] = []
    errors: list[BaseException] = []

    def run_in_own_loop():
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        try:
            results.append(asyncio.run(pool.get_session("s", "t1", conn)))
        except BaseException as e:  # noqa: BLE001 - capture for assertion
            errors.append(e)

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        t1 = threading.Thread(target=run_in_own_loop)
        t1.start()
        t1.join()

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        t2 = threading.Thread(target=run_in_own_loop)
        t2.start()
        t2.join()

    assert not errors, f"cross-loop same-key request must not raise: {errors}"
    assert len(results) == 2
    assert all(r is not None for r in results)


def test_cross_loop_preempting_blocked_in_flight_does_not_hang_owner():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    pool = MCPSessionPool()
    conn = {"transport": "stdio", "command": "x", "args": []}
    first_gate = threading.Event()
    entered = threading.Event()
    results: list[tuple[str, object]] = []
    errors: list[tuple[str, BaseException]] = []
    closed: list[str] = []

    class _BlockingForeverCm:
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        async def __aenter__(self):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            session = MagicMock()
            session.initialize = self._initialize
            entered.set()
            return session

        async def _initialize(self):
            # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            while not first_gate.is_set():
                await asyncio.sleep(0.005)

        async def __aexit__(self, *args):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            closed.append("blocking")
            return False

    class _FastCm:
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        async def __aenter__(self):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            session = MagicMock()

            async def init():
                """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
                return None

            session.initialize = init
            return session

        async def __aexit__(self, *args):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            return False

    cms: list[object] = [_BlockingForeverCm(), _FastCm()]

    def make_cm(*a, **kw):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return cms.pop(0)

    def run_get(name):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        try:
            results.append((name, asyncio.run(pool.get_session("s", "t1", conn))))
        except BaseException as e:  # noqa: BLE001 - capture for assertion
            errors.append((name, e))

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        ta = threading.Thread(target=run_get, args=("A",))
        ta.start()
        assert entered.wait(2), "owner A must enter the CM and start initializing"

        tb = threading.Thread(target=run_get, args=("B",))
        tb.start()
        tb.join(3)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert not tb.is_alive(), "foreign-loop request B must not hang"
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        ta.join(3)
        assert not ta.is_alive(), "preempted owner A must not hang forever"

    assert [n for n, _ in results] == ["B"], "only B produces a usable session"
    assert any(isinstance(e, asyncio.CancelledError) for _, e in errors), "preempted A must unwind via CancelledError"
    assert "blocking" in closed, "preempted owner's __aexit__ must run on teardown"


@pytest.mark.asyncio
async def test_close_all_sync_from_running_loop_does_not_wait_on_itself():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    pool = MCPSessionPool()
    pool.SESSION_CLOSE_TIMEOUT = 0.2
    conn = {"transport": "stdio", "command": "x", "args": []}

    cm = _CloseTrackingCm()

    def make_cm(*a, **kw):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        await pool.get_session("s", "t1", conn)
        start = asyncio.get_running_loop().time()
        pool.close_all_sync()
        elapsed = asyncio.get_running_loop().time() - start

        assert elapsed < 0.1, "close_all_sync must not stall until timeout on the current loop"
        assert len(pool._entries) == 0
        assert len(pool._inflight) == 0
        assert cm.closed is False, "owner task has not run yet while close_all_sync is still executing"

        for _ in range(10):
            if cm.closed:
                break
            await asyncio.sleep(0.01)

    assert cm.closed is True, "owner task must close itself after the loop regains control"


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


class _CloseTrackingCm:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""

    def __init__(self) -> None:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        self.closed = False

    async def __aenter__(self):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        session = MagicMock()

        async def init():
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            return None

        session.initialize = init
        return session

    async def __aexit__(self, *args):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        self.closed = True
        return False


def test_reset_mcp_tools_cache_from_running_loop_is_bounded():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from deerflow.mcp.cache import reset_mcp_tools_cache
    from deerflow.mcp.session_pool import get_session_pool

    conn = {"transport": "stdio", "command": "x", "args": []}
    cm = _CloseTrackingCm()
    done = threading.Event()

    async def scenario():
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        pool = get_session_pool()
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        await pool.get_session("s", "t1", conn)
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        reset_mcp_tools_cache()
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        await asyncio.sleep(0.05)

    def run():
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        asyncio.run(scenario())
        done.set()

    t = threading.Thread(target=run, daemon=True)
    with patch("langchain_mcp_adapters.sessions.create_session", return_value=cm):
        t.start()
        t.join(timeout=5)

    assert done.is_set(), "reset_mcp_tools_cache() deadlocked inside a running loop"
    assert cm.closed is True, "owner task must run __aexit__ once the loop regains control"


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_tools_routed_to_source_server_with_prefix_overlap():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.mcp.tools import get_mcp_tools

    class Args(BaseModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        query: str = Field(..., description="query")

    web_tool = StructuredTool(
        name="web_open",
        description="d",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )
    scraper_tool = StructuredTool(
        name="web_scraper_search",
        description="d",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    extensions_config = MagicMock()
    extensions_config.model_extra = {}

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    servers_config = {
        "web": {"transport": "stdio", "command": "npx", "args": ["web"]},
        "web_scraper": {"transport": "stdio", "command": "npx", "args": ["scraper"]},
    }

    routed: list[tuple[str, str]] = []

    def fake_wrap(tool, server_name, connection, interceptors, tool_call_timeout=None):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        routed.append((tool.name, server_name))
        return tool

    async def get_tools_for_server(*, server_name: str | None = None):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        if server_name == "web":
            return [web_tool]
        if server_name == "web_scraper":
            return [scraper_tool]
        raise AssertionError(f"unexpected server_name: {server_name}")

    with (
        patch("deerflow.mcp.tools.ExtensionsConfig.from_file", return_value=extensions_config),
        patch("deerflow.mcp.tools.build_servers_config", return_value=servers_config),
        patch("deerflow.mcp.tools.get_initial_oauth_headers", return_value={}),
        patch("deerflow.mcp.tools.build_oauth_tool_interceptor", return_value=None),
        patch("langchain_mcp_adapters.client.MultiServerMCPClient") as MockClient,
        patch("deerflow.mcp.tools._make_session_pool_tool", side_effect=fake_wrap),
    ):
        MockClient.return_value.get_tools = AsyncMock(side_effect=get_tools_for_server)
        await get_mcp_tools()

    routing = dict(routed)
    assert routing["web_scraper_search"] == "web_scraper", f"tool mis-routed to {routing.get('web_scraper_search')!r}, expected 'web_scraper'"
    assert routing["web_open"] == "web"
