"""覆盖内置代理通信调用工具的配置转换、执行边界与工具注册行为。"""

import sys
from types import SimpleNamespace

import pytest

from deerflow.config.acp_config import ACPAgentConfig
from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig, set_extensions_config
from deerflow.tools.builtins.invoke_acp_agent_tool import (
    _build_acp_mcp_servers,
    _build_mcp_servers,
    _build_permission_response,
    _get_work_dir,
    build_invoke_acp_agent_tool,
)
from deerflow.tools.tools import get_available_tools


def test_build_mcp_servers_filters_disabled_and_maps_transports():
    """验证仅启用的服务配置会按标准输入输出与网络传输格式导出。"""
    set_extensions_config(ExtensionsConfig(mcp_servers={"stale": McpServerConfig(enabled=True, type="stdio", command="echo")}, skills={}))
    fresh_config = ExtensionsConfig(
        mcp_servers={
            "stdio": McpServerConfig(enabled=True, type="stdio", command="npx", args=["srv"]),
            "http": McpServerConfig(enabled=True, type="http", url="https://example.com/mcp"),
            "disabled": McpServerConfig(enabled=False, type="stdio", command="echo"),
        },
        skills={},
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: fresh_config),
    )

    try:
        assert _build_mcp_servers() == {
            "stdio": {"transport": "stdio", "command": "npx", "args": ["srv"]},
            "http": {"transport": "http", "url": "https://example.com/mcp"},
        }
    finally:
        monkeypatch.undo()
        set_extensions_config(ExtensionsConfig(mcp_servers={}, skills={}))


def test_build_acp_mcp_servers_formats_list_payload():
    """验证代理通信会话使用的服务列表保留环境变量和请求头键值对。"""
    set_extensions_config(ExtensionsConfig(mcp_servers={"stale": McpServerConfig(enabled=True, type="stdio", command="echo")}, skills={}))
    fresh_config = ExtensionsConfig(
        mcp_servers={
            "stdio": McpServerConfig(enabled=True, type="stdio", command="npx", args=["srv"], env={"FOO": "bar"}),
            "http": McpServerConfig(enabled=True, type="http", url="https://example.com/mcp", headers={"Authorization": "Bearer token"}),
            "disabled": McpServerConfig(enabled=False, type="stdio", command="echo"),
        },
        skills={},
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: fresh_config),
    )

    try:
        assert _build_acp_mcp_servers() == [
            {
                "name": "stdio",
                "type": "stdio",
                "command": "npx",
                "args": ["srv"],
                "env": [{"name": "FOO", "value": "bar"}],
            },
            {
                "name": "http",
                "type": "http",
                "url": "https://example.com/mcp",
                "headers": [{"name": "Authorization", "value": "Bearer token"}],
            },
        ]
    finally:
        monkeypatch.undo()
        set_extensions_config(ExtensionsConfig(mcp_servers={}, skills={}))


def test_build_permission_response_prefers_allow_once():
    """验证自动批准时优先选择一次性允许选项而非永久允许。"""
    response = _build_permission_response(
        [
            SimpleNamespace(kind="reject_once", optionId="deny"),
            SimpleNamespace(kind="allow_always", optionId="always"),
            SimpleNamespace(kind="allow_once", optionId="once"),
        ],
        auto_approve=True,
    )

    assert response.outcome.outcome == "selected"
    assert response.outcome.option_id == "once"


def test_build_permission_response_denies_when_no_allow_option():
    """验证选项中没有允许项时自动批准仍返回取消结果。"""
    response = _build_permission_response(
        [
            SimpleNamespace(kind="reject_once", optionId="deny"),
            SimpleNamespace(kind="reject_always", optionId="deny-forever"),
        ],
        auto_approve=True,
    )

    assert response.outcome.outcome == "cancelled"


def test_build_permission_response_denies_when_auto_approve_false():
    """验证关闭自动批准后，即使存在允许选项也始终拒绝权限请求。"""
    response = _build_permission_response(
        [
            SimpleNamespace(kind="allow_once", optionId="once"),
            SimpleNamespace(kind="allow_always", optionId="always"),
        ],
        auto_approve=False,
    )

    assert response.outcome.outcome == "cancelled"


@pytest.mark.anyio
async def test_build_invoke_tool_description_and_unknown_agent_error():
    """验证工具描述列出已配置代理，并向未知代理返回可用名称。"""
    tool = build_invoke_acp_agent_tool(
        {
            "codex": ACPAgentConfig(command="codex-acp", description="Codex CLI"),
            "claude_code": ACPAgentConfig(command="claude-code-acp", description="Claude Code"),
        }
    )

    assert "Available agents:" in tool.description
    assert "- codex: Codex CLI" in tool.description
    assert "- claude_code: Claude Code" in tool.description
    assert "Do NOT include /mnt/user-data paths" in tool.description
    assert "/mnt/acp-workspace/" in tool.description

    result = await tool.coroutine(agent="missing", prompt="do work")
    assert result == "Error: Unknown agent 'missing'. Available: codex, claude_code"


def test_get_work_dir_uses_base_dir_when_no_thread_id(monkeypatch, tmp_path):
    """验证缺少线程标识时工作目录回退到基础目录的共享代理通信目录。"""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    result = _get_work_dir(None)
    expected = tmp_path / "acp-workspace"
    assert result == str(expected)
    assert expected.exists()


def test_get_work_dir_uses_per_thread_path_when_thread_id_given(monkeypatch, tmp_path):
    """验证合法线程标识生成隔离的线程专属代理通信工作目录。"""
    from deerflow.config import paths as paths_module
    from deerflow.runtime import user_context as uc_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(uc_module, "get_effective_user_id", lambda: None)
    result = _get_work_dir("thread-abc-123")
    expected = tmp_path / "threads" / "thread-abc-123" / "acp-workspace"
    assert result == str(expected)
    assert expected.exists()


def test_get_work_dir_falls_back_to_global_for_invalid_thread_id(monkeypatch, tmp_path):
    """验证含路径穿越字符的线程标识不会影响目录，而是回退共享目录。"""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    result = _get_work_dir("../../evil")
    expected = tmp_path / "acp-workspace"
    assert result == str(expected)
    assert expected.exists()


@pytest.mark.anyio
async def test_invoke_acp_agent_uses_fixed_acp_workspace(monkeypatch, tmp_path):
    """验证运行配置缺少线程标识时，代理进程与会话均使用共享代理通信目录。"""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))

    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(
            lambda cls: ExtensionsConfig(
                mcp_servers={"github": McpServerConfig(enabled=True, type="stdio", command="npx", args=["github-mcp"])},
                skills={},
            )
        ),
    )

    captured: dict[str, object] = {}

    class DummyClient:
        """模拟接收代理通信流式文本更新并汇总结果的客户端。"""

        def __init__(self) -> None:
            """初始化用于收集会话文本分片的空列表。"""
            self._chunks: list[str] = []

        @property
        def collected_text(self) -> str:
            """返回已按到达顺序拼接的模拟代理输出。"""
            return "".join(self._chunks)

        async def session_update(self, session_id: str, update, **kwargs) -> None:
            """仅在更新包含文本块时记录其内容，以模拟结果流。"""
            if hasattr(update, "content") and hasattr(update.content, "text"):
                self._chunks.append(update.content.text)

        async def request_permission(self, options, session_id: str, tool_call, **kwargs):
            """断言本用例的自动流程不应向模拟客户端请求权限。"""
            raise AssertionError("request_permission should not be called in this test")

    class DummyConn:
        """模拟代理通信连接，捕获初始化、会话创建与提示词参数。"""

        async def initialize(self, **kwargs):
            """记录初始化参数，供用例验证协议协商输入。"""
            captured["initialize"] = kwargs

        async def new_session(self, **kwargs):
            """记录新会话参数并返回固定会话标识。"""
            captured["new_session"] = kwargs
            return SimpleNamespace(session_id="session-1")

        async def prompt(self, **kwargs):
            """记录提示词并向模拟客户端推送固定文本结果。"""
            captured["prompt"] = kwargs
            client = captured["client"]
            await client.session_update(
                "session-1",
                SimpleNamespace(content=text_content_block("ACP result")),
            )

    class DummyProcessContext:
        """模拟代理通信子进程上下文，保存启动命令与工作目录。"""

        def __init__(self, client, cmd, *args, cwd):
            """保存模拟子进程创建时传入的客户端、命令和目录。"""
            captured["client"] = client
            captured["spawn"] = {"cmd": cmd, "args": list(args), "cwd": cwd}

        async def __aenter__(self):
            """进入上下文时提供模拟连接与未使用的进程对象。"""
            return DummyConn(), object()

        async def __aexit__(self, exc_type, exc, tb):
            """退出模拟上下文且不吞掉可能发生的异常。"""
            return False

    class DummyRequestError(Exception):
        """提供代理通信所需的未找到方法错误工厂的模拟异常类型。"""

        @staticmethod
        def method_not_found(method: str):
            """根据缺失的方法名构造模拟请求错误。"""
            return DummyRequestError(method)

    monkeypatch.setitem(
        sys.modules,
        "acp",
        SimpleNamespace(
            PROTOCOL_VERSION="2026-03-24",
            Client=DummyClient,
            RequestError=DummyRequestError,
            spawn_agent_process=lambda client, cmd, *args, env=None, cwd: DummyProcessContext(client, cmd, *args, cwd=cwd),
            text_block=lambda text: {"type": "text", "text": text},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "acp.schema",
        SimpleNamespace(
            ClientCapabilities=lambda: {"supports": []},
            Implementation=lambda **kwargs: kwargs,
            TextContentBlock=type(
                "TextContentBlock",
                (),
                {"__init__": lambda self, text: setattr(self, "text", text)},
            ),
        ),
    )
    text_content_block = sys.modules["acp.schema"].TextContentBlock

    expected_cwd = str(tmp_path / "acp-workspace")

    tool = build_invoke_acp_agent_tool(
        {
            "codex": ACPAgentConfig(
                command="codex-acp",
                args=["--json"],
                description="Codex CLI",
                model="gpt-5-codex",
            )
        }
    )

    try:
        result = await tool.coroutine(
            agent="codex",
            prompt="Implement the fix",
        )
    finally:
        sys.modules.pop("acp", None)
        sys.modules.pop("acp.schema", None)

    assert result == "ACP result"
    assert captured["spawn"] == {"cmd": "codex-acp", "args": ["--json"], "cwd": expected_cwd}
    assert captured["new_session"] == {
        "cwd": expected_cwd,
        "mcp_servers": [
            {
                "name": "github",
                "type": "stdio",
                "command": "npx",
                "args": ["github-mcp"],
                "env": [],
            }
        ],
        "model": "gpt-5-codex",
    }
    assert captured["prompt"] == {
        "session_id": "session-1",
        "prompt": [{"type": "text", "text": "Implement the fix"}],
    }


@pytest.mark.anyio
async def test_invoke_acp_agent_uses_per_thread_workspace_when_thread_id_in_config(monkeypatch, tmp_path):
    """验证运行配置提供线程标识时，代理进程切换到该线程的隔离目录。"""
    from deerflow.config import paths as paths_module
    from deerflow.runtime import user_context as uc_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(uc_module, "get_effective_user_id", lambda: None)

    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )

    captured: dict[str, object] = {}

    class DummyClient:
        """模拟不产生文本但禁止权限回调的代理通信客户端。"""

        def __init__(self) -> None:
            """初始化未使用的文本分片容器以匹配真实客户端接口。"""
            self._chunks: list[str] = []

        @property
        def collected_text(self) -> str:
            """返回空结果，表示本用例不关心代理输出。"""
            return "".join(self._chunks)

        async def session_update(self, session_id, update, **kwargs):
            """忽略会话更新，因为本用例只验证工作目录。"""
            pass

        async def request_permission(self, options, session_id, tool_call, **kwargs):
            """断言线程目录测试不应触发权限请求。"""
            raise AssertionError("should not be called")

    class DummyConn:
        """模拟代理通信连接并只记录新会话参数。"""

        async def initialize(self, **kwargs):
            """忽略初始化参数，本用例不对其作断言。"""
            pass

        async def new_session(self, **kwargs):
            """保存会话创建参数并返回固定会话标识。"""
            captured["new_session"] = kwargs
            return SimpleNamespace(session_id="s1")

        async def prompt(self, **kwargs):
            """忽略提示词发送，本用例仅验证子进程目录。"""
            pass

    class DummyProcessContext:
        """模拟子进程上下文并捕获传入的当前工作目录。"""

        def __init__(self, client, cmd, *args, cwd):
            """将子进程工作目录写入捕获字典供断言使用。"""
            captured["cwd"] = cwd

        async def __aenter__(self):
            """进入时返回可完成调用链的模拟连接。"""
            return DummyConn(), object()

        async def __aexit__(self, exc_type, exc, tb):
            """退出时不抑制异常，保持真实上下文管理器语义。"""
            return False

    class DummyRequestError(Exception):
        """模拟代理通信的请求错误类型。"""

        @staticmethod
        def method_not_found(method):
            """按方法名生成模拟的未找到错误。"""
            return DummyRequestError(method)

    monkeypatch.setitem(
        sys.modules,
        "acp",
        SimpleNamespace(
            PROTOCOL_VERSION="2026-03-24",
            Client=DummyClient,
            RequestError=DummyRequestError,
            spawn_agent_process=lambda client, cmd, *args, env=None, cwd: DummyProcessContext(client, cmd, *args, cwd=cwd),
            text_block=lambda text: {"type": "text", "text": text},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "acp.schema",
        SimpleNamespace(
            ClientCapabilities=lambda: {},
            Implementation=lambda **kwargs: kwargs,
            TextContentBlock=type("TextContentBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)}),
        ),
    )

    thread_id = "thread-xyz-789"
    expected_cwd = str(tmp_path / "threads" / thread_id / "acp-workspace")

    tool = build_invoke_acp_agent_tool({"codex": ACPAgentConfig(command="codex-acp", description="Codex CLI")})

    try:
        await tool.coroutine(
            agent="codex",
            prompt="Do something",
            config={"configurable": {"thread_id": thread_id}},
        )
    finally:
        sys.modules.pop("acp", None)
        sys.modules.pop("acp.schema", None)

    assert captured["cwd"] == expected_cwd


@pytest.mark.anyio
async def test_invoke_acp_agent_passes_env_to_spawn(monkeypatch, tmp_path):
    """验证代理环境变量会解析引用后完整传给子进程启动函数。"""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )
    monkeypatch.setenv("TEST_OPENAI_KEY", "sk-from-env")

    captured: dict[str, object] = {}

    class DummyClient:
        """模拟无输出且不参与权限协商的代理通信客户端。"""

        def __init__(self) -> None:
            """初始化接口兼容的空分片列表。"""
            self._chunks: list[str] = []

        @property
        def collected_text(self) -> str:
            """返回空文本，因为环境变量测试不检验代理响应。"""
            return ""

        async def session_update(self, session_id, update, **kwargs):
            """忽略未参与断言的会话更新。"""
            pass

        async def request_permission(self, options, session_id, tool_call, **kwargs):
            """断言环境变量路径不会发生权限回调。"""
            raise AssertionError("should not be called")

    class DummyConn:
        """模拟完成代理通信调用所需的最小连接接口。"""

        async def initialize(self, **kwargs):
            """接受并忽略初始化参数。"""
            pass

        async def new_session(self, **kwargs):
            """返回固定会话标识以使提示词调用继续。"""
            return SimpleNamespace(session_id="s1")

        async def prompt(self, **kwargs):
            """接受提示词参数，不生成额外输出。"""
            pass

    class DummyProcessContext:
        """模拟子进程上下文并记录其解析后的环境变量。"""

        def __init__(self, client, cmd, *args, env=None, cwd):
            """捕获启动函数传入的环境变量映射。"""
            captured["env"] = env

        async def __aenter__(self):
            """提供模拟连接以完成代理调用。"""
            return DummyConn(), object()

        async def __aexit__(self, exc_type, exc, tb):
            """保留异常传播行为。"""
            return False

    class DummyRequestError(Exception):
        """模拟调用链所需的代理通信请求错误类。"""

        @staticmethod
        def method_not_found(method):
            """构造带有缺失方法名的模拟错误。"""
            return DummyRequestError(method)

    monkeypatch.setitem(
        sys.modules,
        "acp",
        SimpleNamespace(
            PROTOCOL_VERSION="2026-03-24",
            Client=DummyClient,
            RequestError=DummyRequestError,
            spawn_agent_process=lambda client, cmd, *args, env=None, cwd: DummyProcessContext(client, cmd, *args, env=env, cwd=cwd),
            text_block=lambda text: {"type": "text", "text": text},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "acp.schema",
        SimpleNamespace(
            ClientCapabilities=lambda: {},
            Implementation=lambda **kwargs: kwargs,
            TextContentBlock=type("TextContentBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)}),
        ),
    )

    tool = build_invoke_acp_agent_tool(
        {
            "codex": ACPAgentConfig(
                command="codex-acp",
                description="Codex CLI",
                env={"OPENAI_API_KEY": "$TEST_OPENAI_KEY", "FOO": "bar"},
            )
        }
    )

    try:
        await tool.coroutine(agent="codex", prompt="Do something")
    finally:
        sys.modules.pop("acp", None)
        sys.modules.pop("acp.schema", None)

    assert captured["env"] == {"OPENAI_API_KEY": "sk-from-env", "FOO": "bar"}


@pytest.mark.anyio
async def test_invoke_acp_agent_skips_invalid_mcp_servers(monkeypatch, tmp_path, caplog):
    """验证无效服务配置仅记录警告并以空服务器列表继续调用代理。"""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(
        "deerflow.tools.builtins.invoke_acp_agent_tool._build_acp_mcp_servers",
        lambda: (_ for _ in ()).throw(ValueError("missing command")),
    )

    captured: dict[str, object] = {}

    class DummyClient:
        """模拟不产生输出且拒绝意外权限请求的代理通信客户端。"""

        def __init__(self) -> None:
            """初始化兼容真实客户端的空文本分片列表。"""
            self._chunks: list[str] = []

        @property
        def collected_text(self) -> str:
            """返回空文本，避免无关输出影响服务配置容错断言。"""
            return ""

        async def session_update(self, session_id, update, **kwargs):
            """忽略本用例不关注的会话文本更新。"""
            pass

        async def request_permission(self, options, session_id, tool_call, **kwargs):
            """断言服务配置降级路径不请求权限。"""
            raise AssertionError("should not be called")

    class DummyConn:
        """模拟可创建会话但不产生结果的代理通信连接。"""

        async def initialize(self, **kwargs):
            """接受初始化参数，保持调用链完整。"""
            pass

        async def new_session(self, **kwargs):
            """记录会话参数以断言服务列表被清空。"""
            captured["new_session"] = kwargs
            return SimpleNamespace(session_id="s1")

        async def prompt(self, **kwargs):
            """接受提示词，测试无需模拟代理响应。"""
            pass

    class DummyProcessContext:
        """模拟启动过程并捕获命令、环境和工作目录。"""

        def __init__(self, client, cmd, *args, env=None, cwd=None):
            """将启动参数保存到捕获字典。"""
            captured["spawn"] = {"cmd": cmd, "args": list(args), "env": env, "cwd": cwd}

        async def __aenter__(self):
            """返回用于执行会话调用的模拟连接。"""
            return DummyConn(), object()

        async def __aexit__(self, exc_type, exc, tb):
            """不吞掉异常，模拟普通异步上下文退出。"""
            return False

    class DummyRequestError(Exception):
        """提供接口兼容的代理通信请求错误模拟。"""

        @staticmethod
        def method_not_found(method):
            """构造表示指定方法不可用的模拟错误。"""
            return DummyRequestError(method)

    monkeypatch.setitem(
        sys.modules,
        "acp",
        SimpleNamespace(
            PROTOCOL_VERSION="2026-03-24",
            Client=DummyClient,
            RequestError=DummyRequestError,
            spawn_agent_process=lambda client, cmd, *args, env=None, cwd: DummyProcessContext(client, cmd, *args, env=env, cwd=cwd),
            text_block=lambda text: {"type": "text", "text": text},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "acp.schema",
        SimpleNamespace(
            ClientCapabilities=lambda: {},
            Implementation=lambda **kwargs: kwargs,
            TextContentBlock=type("TextContentBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)}),
        ),
    )

    tool = build_invoke_acp_agent_tool({"codex": ACPAgentConfig(command="codex-acp", description="Codex CLI")})
    caplog.set_level("WARNING")

    try:
        await tool.coroutine(agent="codex", prompt="Do something")
    finally:
        sys.modules.pop("acp", None)
        sys.modules.pop("acp.schema", None)

    assert captured["new_session"]["mcp_servers"] == []
    assert "continuing without MCP servers" in caplog.text
    assert "missing command" in caplog.text


@pytest.mark.anyio
async def test_invoke_acp_agent_passes_none_env_when_not_configured(monkeypatch, tmp_path):
    """验证未配置环境变量时向启动函数传递空值，以继承父进程环境。"""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )

    captured: dict[str, object] = {}

    class DummyClient:
        """模拟无输出且不发生权限协商的代理通信客户端。"""

        def __init__(self) -> None:
            """初始化与真实客户端一致的空分片存储。"""
            self._chunks: list[str] = []

        @property
        def collected_text(self) -> str:
            """返回空文本，因为本用例仅验证环境参数。"""
            return ""

        async def session_update(self, session_id, update, **kwargs):
            """忽略与环境参数无关的会话更新。"""
            pass

        async def request_permission(self, options, session_id, tool_call, **kwargs):
            """断言未配置环境变量不会触发权限请求。"""
            raise AssertionError("should not be called")

    class DummyConn:
        """模拟执行代理调用所需的最小代理通信连接。"""

        async def initialize(self, **kwargs):
            """接收初始化参数而不产生副作用。"""
            pass

        async def new_session(self, **kwargs):
            """返回固定会话标识以继续调用。"""
            return SimpleNamespace(session_id="s1")

        async def prompt(self, **kwargs):
            """接收提示词调用，本用例无需响应内容。"""
            pass

    class DummyProcessContext:
        """模拟子进程上下文并记录空配置对应的环境参数。"""

        def __init__(self, client, cmd, *args, env=None, cwd):
            """保存启动函数接收的环境变量值。"""
            captured["env"] = env

        async def __aenter__(self):
            """提供模拟连接使调用路径能够完成。"""
            return DummyConn(), object()

        async def __aexit__(self, exc_type, exc, tb):
            """按默认语义传播异常。"""
            return False

    class DummyRequestError(Exception):
        """模拟代理通信请求错误类型以满足导入接口。"""

        @staticmethod
        def method_not_found(method):
            """创建携带缺失方法名的模拟异常。"""
            return DummyRequestError(method)

    monkeypatch.setitem(
        sys.modules,
        "acp",
        SimpleNamespace(
            PROTOCOL_VERSION="2026-03-24",
            Client=DummyClient,
            RequestError=DummyRequestError,
            spawn_agent_process=lambda client, cmd, *args, env=None, cwd: DummyProcessContext(client, cmd, *args, env=env, cwd=cwd),
            text_block=lambda text: {"type": "text", "text": text},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "acp.schema",
        SimpleNamespace(
            ClientCapabilities=lambda: {},
            Implementation=lambda **kwargs: kwargs,
            TextContentBlock=type("TextContentBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)}),
        ),
    )

    tool = build_invoke_acp_agent_tool({"codex": ACPAgentConfig(command="codex-acp", description="Codex CLI")})

    try:
        await tool.coroutine(agent="codex", prompt="Do something")
    finally:
        sys.modules.pop("acp", None)
        sys.modules.pop("acp.schema", None)

    assert captured["env"] is None


def test_get_available_tools_includes_invoke_acp_agent_when_agents_configured(monkeypatch):
    """验证全局代理通信配置存在时，工具列表会注册调用工具。"""
    from deerflow.config.acp_config import load_acp_config_from_dict

    load_acp_config_from_dict(
        {
            "codex": {
                "command": "codex-acp",
                "args": [],
                "description": "Codex CLI",
            }
        }
    )

    fake_config = SimpleNamespace(
        tools=[],
        models=[],
        tool_search=SimpleNamespace(enabled=False),
        get_model_config=lambda name: None,
    )
    monkeypatch.setattr("deerflow.tools.tools.get_app_config", lambda: fake_config)
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )

    tools = get_available_tools(include_mcp=True, subagent_enabled=False)
    assert "invoke_acp_agent" in [tool.name for tool in tools]

    load_acp_config_from_dict({})


def test_get_available_tools_sync_invoke_acp_agent_preserves_thread_workspace(monkeypatch, tmp_path):
    """验证同步工具入口也会把线程标识传入隔离的代理通信工作目录。"""
    from deerflow.config import paths as paths_module
    from deerflow.runtime import user_context as uc_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(uc_module, "get_effective_user_id", lambda: None)
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )
    monkeypatch.setattr("deerflow.tools.tools.is_host_bash_allowed", lambda config=None: True)

    captured: dict[str, object] = {}

    class DummyClient:
        """模拟同步入口调用所需的最小代理通信客户端。"""

        @property
        def collected_text(self) -> str:
            """返回固定结果，表示客户端已完成输出收集。"""
            return "ok"

        async def session_update(self, session_id, update, **kwargs):
            """忽略同步入口测试不关注的流式更新。"""
            pass

        async def request_permission(self, options, session_id, tool_call, **kwargs):
            """断言同步路径不应请求人工权限。"""
            raise AssertionError("should not be called")

    class DummyConn:
        """模拟可完成初始化、建会话和提示词调用的代理通信连接。"""

        async def initialize(self, **kwargs):
            """接受初始化参数而不改变捕获状态。"""
            pass

        async def new_session(self, **kwargs):
            """返回固定会话标识以驱动同步入口。"""
            return SimpleNamespace(session_id="s1")

        async def prompt(self, **kwargs):
            """接受提示词参数，不生成额外响应。"""
            pass

    class DummyProcessContext:
        """模拟同步入口启动的代理通信子进程并捕获工作目录。"""

        def __init__(self, client, cmd, *args, env=None, cwd):
            """记录传给子进程的线程隔离目录。"""
            captured["cwd"] = cwd

        async def __aenter__(self):
            """进入后返回模拟连接与未使用进程对象。"""
            return DummyConn(), object()

        async def __aexit__(self, exc_type, exc, tb):
            """不抑制异常，保持上下文退出结果。"""
            return False

    monkeypatch.setitem(
        sys.modules,
        "acp",
        SimpleNamespace(
            PROTOCOL_VERSION="2026-03-24",
            Client=DummyClient,
            spawn_agent_process=lambda client, cmd, *args, env=None, cwd: DummyProcessContext(client, cmd, *args, env=env, cwd=cwd),
            text_block=lambda text: {"type": "text", "text": text},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "acp.schema",
        SimpleNamespace(
            ClientCapabilities=lambda: {},
            Implementation=lambda **kwargs: kwargs,
            TextContentBlock=type("TextContentBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)}),
        ),
    )

    explicit_config = SimpleNamespace(
        tools=[],
        models=[],
        tool_search=SimpleNamespace(enabled=False),
        skill_evolution=SimpleNamespace(enabled=False),
        sandbox=SimpleNamespace(),
        get_model_config=lambda name: None,
        acp_agents={"codex": ACPAgentConfig(command="codex-acp", description="Codex CLI")},
    )
    tools = get_available_tools(include_mcp=False, subagent_enabled=False, app_config=explicit_config)
    tool = next(tool for tool in tools if tool.name == "invoke_acp_agent")

    thread_id = "thread-sync-123"
    tool.invoke(
        {"agent": "codex", "prompt": "Do something"},
        config={"configurable": {"thread_id": thread_id}},
    )

    assert captured["cwd"] == str(tmp_path / "threads" / thread_id / "acp-workspace")


def test_get_available_tools_uses_explicit_app_config_for_acp_agents(monkeypatch):
    """验证显式应用配置优先于环境中的代理通信配置读取。"""
    explicit_agents = {"codex": ACPAgentConfig(command="codex-acp", description="Codex CLI")}
    explicit_config = SimpleNamespace(
        tools=[],
        models=[],
        tool_search=SimpleNamespace(enabled=False),
        skill_evolution=SimpleNamespace(enabled=False),
        get_model_config=lambda name: None,
        acp_agents=explicit_agents,
    )
    sentinel_tool = SimpleNamespace(name="invoke_acp_agent")
    captured: dict[str, object] = {}

    def fail_get_acp_agents():
        """在误读环境配置时立即失败，保护显式配置优先级。"""
        raise AssertionError("ambient get_acp_agents() must not be used when app_config is explicit")

    def fake_build_invoke_acp_agent_tool(agents):
        """记录工具工厂收到的代理映射并返回哨兵工具。"""
        captured["agents"] = agents
        return sentinel_tool

    monkeypatch.setattr("deerflow.tools.tools.is_host_bash_allowed", lambda config=None: True)
    monkeypatch.setattr("deerflow.config.acp_config.get_acp_agents", fail_get_acp_agents)
    monkeypatch.setattr("deerflow.tools.builtins.invoke_acp_agent_tool.build_invoke_acp_agent_tool", fake_build_invoke_acp_agent_tool)

    tools = get_available_tools(include_mcp=False, subagent_enabled=False, app_config=explicit_config)

    assert captured["agents"] is explicit_agents
    assert "invoke_acp_agent" in [tool.name for tool in tools]
