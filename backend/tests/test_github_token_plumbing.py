"""验证当前测试场景在真实调用中的结果、异常与状态边界。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from langgraph_sdk.errors import ConflictError

from app.channels.manager import ChannelManager
from app.channels.message_bus import InboundMessage, InboundMessageType, MessageBus
from app.channels.store import ChannelStore
from deerflow.sandbox.local.local_sandbox import LocalSandbox
from deerflow.sandbox.tools import _github_env_from_runtime, bash_tool


def _make_conflict_error(detail: str = "thread_id already exists") -> ConflictError:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    req = httpx.Request("POST", "http://gateway/api/threads")
    resp = httpx.Response(409, json={"detail": detail}, request=req)
    return ConflictError(detail, response=resp, body={"detail": detail})


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_local_sandbox_env_overlay_reaches_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import deerflow.sandbox.local.local_sandbox as local_sandbox

    captured: dict = {}

    def fake_run_posix(args, timeout, env=None):
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        captured["env"] = env
        return ("", "", 0, False)

    monkeypatch.setattr(LocalSandbox, "_run_posix_command", staticmethod(fake_run_posix))
    monkeypatch.setattr(LocalSandbox, "_get_shell", staticmethod(lambda: "/bin/bash"))
    monkeypatch.setattr(local_sandbox.os, "environ", {"PATH": "/usr/bin", "EXISTING": "kept"})

    LocalSandbox("local:t").execute_command("echo $GITHUB_TOKEN", env={"GITHUB_TOKEN": "tok-123"})

    env = captured["env"]
    assert env["GITHUB_TOKEN"] == "tok-123"
    # 说明当前测试分支所验证的真实行为与边界。
    assert env["EXISTING"] == "kept"


def test_local_sandbox_no_env_passes_sanitized_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import deerflow.sandbox.local.local_sandbox as local_sandbox

    captured: dict = {}

    def fake_run_posix(args, timeout, env=None):
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        captured["env"] = env
        return ("", "", 0, False)

    monkeypatch.setattr(LocalSandbox, "_run_posix_command", staticmethod(fake_run_posix))
    monkeypatch.setattr(LocalSandbox, "_get_shell", staticmethod(lambda: "/bin/bash"))
    monkeypatch.setattr(local_sandbox.os, "environ", {"PATH": "/usr/bin", "OPENAI_API_KEY": "sk-leak"})

    LocalSandbox("local:t").execute_command("echo hi")

    env = captured["env"]
    # 说明当前测试分支所验证的真实行为与边界。
    assert "OPENAI_API_KEY" not in env
    # 说明当前测试分支所验证的真实行为与边界。
    assert env["PATH"] == "/usr/bin"


def test_aio_sandbox_env_routes_through_bash_exec() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox

    captured: dict = {}

    class _FakeBash:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        def exec(self, *, command, env=None, **kwargs):
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            captured["command"] = command
            captured["env"] = env
            return SimpleNamespace(data=SimpleNamespace(stdout="ok", stderr=None))

    sbx = AioSandbox.__new__(AioSandbox)
    sbx._lock = __import__("threading").Lock()
    sbx._client = SimpleNamespace(bash=_FakeBash())
    sbx._DEFAULT_NO_CHANGE_TIMEOUT = 30
    sbx._DEFAULT_HARD_TIMEOUT = 30
    sbx._bash_exec_unsupported = False

    out = sbx.execute_command("gh pr create", env={"GH_TOKEN": "tok-123"})

    assert out == "ok"
    assert captured["command"] == "gh pr create"
    assert captured["env"] == {"GH_TOKEN": "tok-123"}


def test_aio_sandbox_no_env_leaves_command_unchanged() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox

    captured: dict = {}

    class _FakeData:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        output = "ok"

    class _FakeResult:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        data = _FakeData()

    class _FakeShell:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        def exec_command(self, *, command, no_change_timeout=None, **kwargs):
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            captured["command"] = command
            return _FakeResult()

    sbx = AioSandbox.__new__(AioSandbox)
    sbx._lock = __import__("threading").Lock()
    sbx._client = SimpleNamespace(shell=_FakeShell())
    sbx._DEFAULT_NO_CHANGE_TIMEOUT = 30

    sbx.execute_command("echo hello")

    assert captured["command"] == "echo hello"


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_key",
    [
        # 说明当前测试分支所验证的真实行为与边界。
        # 说明当前测试分支所验证的真实行为与边界。
        "X;rm -rf /mnt/user-data;Y",
        "X`whoami`",
        "X$(id)",
        "X&Y",
        "X|Y",
        "X>Y",
        "X<Y",
        "X Y",  # 说明当前测试分支所验证的真实行为与边界。
        "X\tY",  # 说明当前测试分支所验证的真实行为与边界。
        "X\nY",  # 说明当前测试分支所验证的真实行为与边界。
        # 说明当前测试分支所验证的真实行为与边界。
        # 说明当前测试分支所验证的真实行为与边界。
        # 说明当前测试分支所验证的真实行为与边界。
        "1FOO",
        # 说明当前测试分支所验证的真实行为与边界。
        "",
        "   ",
        # 说明当前测试分支所验证的真实行为与边界。
        123,
    ],
)
def test_extra_env_rejects_invalid_keys(bad_key) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from deerflow.sandbox.sandbox import _validate_extra_env

    with pytest.raises(ValueError, match="extra_env key"):
        _validate_extra_env({bad_key: "value"})


@pytest.mark.parametrize(
    "good_key",
    [
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "_HIDDEN",
        "foo123",
        "MIXED_case_42",
        "X",
    ],
)
def test_extra_env_accepts_valid_keys(good_key: str) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from deerflow.sandbox.sandbox import _validate_extra_env

    # 说明当前测试分支所验证的真实行为与边界。
    _validate_extra_env({good_key: "any value with spaces and $metachars"})


def test_extra_env_none_and_empty_pass_through() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from deerflow.sandbox.sandbox import _validate_extra_env

    _validate_extra_env(None)
    _validate_extra_env({})


def test_local_sandbox_rejects_invalid_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import deerflow.sandbox.local.local_sandbox as local_sandbox

    fake_run_called = False

    def fake_run(*args, **kwargs):
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        nonlocal fake_run_called
        fake_run_called = True
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(local_sandbox.subprocess, "run", fake_run)

    with pytest.raises(ValueError, match="extra_env key"):
        LocalSandbox("local:t").execute_command(
            "echo hi",
            env={"X;rm -rf /mnt/user-data;Y": "v"},
        )
    assert fake_run_called is False, "subprocess.run must not run when key is invalid"


def test_aio_sandbox_rejects_invalid_env_key() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox

    exec_called = False

    class _FakeShell:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        def exec_command(self, *, command, no_change_timeout=None, **kwargs):
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            nonlocal exec_called
            exec_called = True
            return SimpleNamespace(data=SimpleNamespace(output="ok"))

    sbx = AioSandbox.__new__(AioSandbox)
    sbx._lock = __import__("threading").Lock()
    sbx._client = SimpleNamespace(shell=_FakeShell())
    sbx._DEFAULT_NO_CHANGE_TIMEOUT = 30

    with pytest.raises(ValueError, match="extra_env key"):
        sbx.execute_command(
            "echo hi",
            env={"X;rm -rf /mnt/user-data;Y": "v"},
        )
    assert exec_called is False, "shell.exec_command must not run when key is invalid"


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_github_env_from_runtime_returns_token_pair() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    runtime = SimpleNamespace(context={"github_token": "tok-abc"})
    env = _github_env_from_runtime(runtime)
    assert env == {"GH_TOKEN": "tok-abc", "GITHUB_TOKEN": "tok-abc"}


def test_github_env_from_runtime_resolves_provider_callable() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    calls = {"n": 0}

    def _provider() -> str:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        calls["n"] += 1
        return f"tok-call-{calls['n']}"

    runtime = SimpleNamespace(context={"github_token": _provider})

    env_1 = _github_env_from_runtime(runtime)
    assert env_1 == {"GH_TOKEN": "tok-call-1", "GITHUB_TOKEN": "tok-call-1"}

    env_2 = _github_env_from_runtime(runtime)
    assert env_2 == {"GH_TOKEN": "tok-call-2", "GITHUB_TOKEN": "tok-call-2"}
    assert calls["n"] == 2  # 说明当前测试分支所验证的真实行为与边界。


def test_github_env_from_runtime_returns_none_when_provider_raises() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""

    def _broken() -> str:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        raise RuntimeError("mint failed")

    runtime = SimpleNamespace(context={"github_token": _broken})
    assert _github_env_from_runtime(runtime) is None


def test_github_env_from_runtime_returns_none_when_provider_returns_empty() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    runtime = SimpleNamespace(context={"github_token": lambda: ""})
    assert _github_env_from_runtime(runtime) is None


def test_github_env_from_runtime_none_when_no_token() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    runtime = SimpleNamespace(context={"thread_id": "t1"})
    assert _github_env_from_runtime(runtime) is None


def test_github_env_from_runtime_none_when_empty() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    runtime = SimpleNamespace(context={"github_token": ""})
    assert _github_env_from_runtime(runtime) is None


def test_bash_tool_passes_token_as_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": "aio:xyz"}},  # 说明当前测试分支所验证的真实行为与边界。
        context={"thread_id": "t1", "github_token": "tok-from-manager"},
        config={},
    )

    captured: dict = {}

    class _Sandbox:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        def execute_command(self, command, env=None, timeout=None):
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            captured["command"] = command
            captured["env"] = env
            return "done"

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: _Sandbox())
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)

    result = bash_tool.func(runtime=runtime, description="push", command="git push")

    assert "done" in result
    assert captured["env"] == {"GH_TOKEN": "tok-from-manager", "GITHUB_TOKEN": "tok-from-manager"}


def test_bash_tool_no_env_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": "aio:xyz"}},
        context={"thread_id": "t1"},  # 说明当前测试分支所验证的真实行为与边界。
        config={},
    )

    captured: dict = {}

    class _Sandbox:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        def execute_command(self, command, env=None, timeout=None):
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            captured["env"] = env
            return "done"

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: _Sandbox())
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)

    bash_tool.func(runtime=runtime, description="ls", command="ls")
    assert captured["env"] is None


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def _github_msg(installation_id: int | None = 140594274) -> InboundMessage:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    return InboundMessage(
        channel_name="github",
        chat_id="zhfeng/llm-gateway",
        user_id="zhfeng",
        text="a PR was opened",
        msg_type=InboundMessageType.CHAT,
        # 说明当前测试分支所验证的真实行为与边界。
        # 说明当前测试分支所验证的真实行为与边界。
        topic_id="7:coding-llm-gateway",
        owner_user_id="default",
        metadata={
            "agent_name": "coding-llm-gateway",
            "github": {
                "repo": "zhfeng/llm-gateway",
                "number": 7,
                "installation_id": installation_id,
            },
            "preferred_thread_id": "uuid5-fixed",
        },
    )


def _new_manager() -> ChannelManager:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    store = ChannelStore(path=Path("/tmp/nonexistent-store-test.json"))
    return ChannelManager(bus=bus, store=store)


@pytest.mark.asyncio
async def test_run_context_after_apply_channel_policy_is_json_serializable(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import json

    manager = _new_manager()
    mint = AsyncMock(return_value="ghs_installation_token")
    monkeypatch.setattr("app.gateway.github.app_auth.mint_installation_token", mint)

    run_context: dict = {"thread_id": "t1", "user_id": "u1"}
    await manager._apply_channel_policy(_github_msg(), run_context)

    # 说明当前测试分支所验证的真实行为与边界。
    encoded = json.dumps(run_context)
    assert '"github_token": "ghs_installation_token"' in encoded


@pytest.mark.asyncio
async def test_apply_channel_policy_degrades_on_mint_failure(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    manager = _new_manager()

    async def boom(_installation_id):
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        raise RuntimeError("GITHUB_APP_ID not set")

    monkeypatch.setattr("app.gateway.github.app_auth.mint_installation_token", boom)

    run_context: dict = {}
    with caplog.at_level("WARNING", logger="app.channels.manager"):
        await manager._apply_channel_policy(_github_msg(), run_context)

    # 说明当前测试分支所验证的真实行为与边界。
    assert "github_token" not in run_context
    assert any("credentials_provider raised" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_apply_channel_policy_skips_token_without_installation_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    manager = _new_manager()
    mint = AsyncMock(return_value="should-not-be-called")
    monkeypatch.setattr("app.gateway.github.app_auth.mint_installation_token", mint)

    run_context: dict = {}
    await manager._apply_channel_policy(_github_msg(installation_id=None), run_context)

    mint.assert_not_awaited()
    assert "github_token" not in run_context
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    assert run_context["disable_clarification"] is True


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_github_policy_is_registered_on_import() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    import app.gateway.github  # noqa: F401
    from app.channels.run_policy import CHANNEL_RUN_POLICY

    policy = CHANNEL_RUN_POLICY.get("github")
    assert policy is not None
    assert policy.is_interactive is False
    assert policy.default_recursion_limit == 250
    assert policy.credentials_provider is not None


@pytest.mark.asyncio
async def test_apply_channel_policy_installs_token_for_github(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    manager = _new_manager()
    mint = AsyncMock(return_value="ghs_unified")
    monkeypatch.setattr("app.gateway.github.app_auth.mint_installation_token", mint)

    run_context: dict = {}
    await manager._apply_channel_policy(_github_msg(), run_context)

    mint.assert_awaited_once_with(140594274)
    assert run_context["github_token"] == "ghs_unified"
    # 说明当前测试分支所验证的真实行为与边界。
    assert run_context["disable_clarification"] is True


@pytest.mark.asyncio
async def test_apply_channel_policy_is_noop_for_unregistered_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    manager = _new_manager()
    mint = AsyncMock(return_value="should-not-be-called")
    monkeypatch.setattr("app.gateway.github.app_auth.mint_installation_token", mint)

    msg = InboundMessage(channel_name="slack", chat_id="C1", user_id="u", text="hi", metadata={})
    run_context: dict = {}
    await manager._apply_channel_policy(msg, run_context)

    mint.assert_not_awaited()
    assert "github_token" not in run_context
    assert "disable_clarification" not in run_context


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_thread_uses_preferred_thread_id() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    manager = _new_manager()
    msg = _github_msg()

    created_kwargs: dict = {}

    class _FakeClient:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        class threads:
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            @staticmethod
            async def create(**kwargs):
                """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
                created_kwargs.update(kwargs)
                return {"thread_id": "uuid5-fixed"}

    with patch.object(manager, "_store_thread_id", new=AsyncMock()):
        thread_id = await manager._create_thread(_FakeClient(), msg)

    assert thread_id == "uuid5-fixed"
    assert created_kwargs["thread_id"] == "uuid5-fixed"
    assert "metadata" in created_kwargs


@pytest.mark.asyncio
async def test_create_thread_without_preferred_id_omits_thread_id_kwarg() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    manager = _new_manager()
    msg = InboundMessage(
        channel_name="slack",
        chat_id="C1",
        user_id="u",
        text="hi",
        metadata={},  # 说明当前测试分支所验证的真实行为与边界。
    )

    created_kwargs: dict = {}

    class _FakeClient:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        class threads:
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            @staticmethod
            async def create(**kwargs):
                """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
                created_kwargs.update(kwargs)
                return {"thread_id": "random-from-gateway"}

    with patch.object(manager, "_store_thread_id", new=AsyncMock()):
        await manager._create_thread(_FakeClient(), msg)

    assert "thread_id" not in created_kwargs


@pytest.mark.asyncio
async def test_create_thread_handles_race_on_preferred_id() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    manager = _new_manager()
    msg = _github_msg()  # 说明当前测试分支所验证的真实行为与边界。

    class _FakeClient:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        class threads:
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            @staticmethod
            async def create(**kwargs):
                """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
                raise _make_conflict_error()

            @staticmethod
            async def get(thread_id, **kwargs):
                # 说明当前测试分支所验证的真实行为与边界。
                # 说明当前测试分支所验证的真实行为与边界。
                """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
                return {"thread_id": thread_id}

    stored: dict = {}

    async def _fake_store(_msg, thread_id):
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        stored["thread_id"] = thread_id

    with patch.object(manager, "_store_thread_id", new=_fake_store):
        thread_id = await manager._create_thread(_FakeClient(), msg)

    # 说明当前测试分支所验证的真实行为与边界。
    assert thread_id == "uuid5-fixed"
    assert stored["thread_id"] == "uuid5-fixed"


@pytest.mark.asyncio
async def test_create_thread_non_conflict_failure_propagates_and_does_not_poison_store() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    manager = _new_manager()
    msg = _github_msg()  # 说明当前测试分支所验证的真实行为与边界。

    class _FakeClient:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        class threads:
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            @staticmethod
            async def create(**kwargs):
                # 说明当前测试分支所验证的真实行为与边界。
                # 说明当前测试分支所验证的真实行为与边界。
                """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
                raise RuntimeError("HTTP 500: Failed to create thread")

            @staticmethod
            async def get(thread_id, **kwargs):
                # 说明当前测试分支所验证的真实行为与边界。
                """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
                raise AssertionError("threads.get must not be called on non-conflict failure")

    store_calls: list = []

    async def _fake_store(_msg, thread_id):
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        store_calls.append(thread_id)

    with patch.object(manager, "_store_thread_id", new=_fake_store):
        with pytest.raises(RuntimeError, match="500"):
            await manager._create_thread(_FakeClient(), msg)

    # 说明当前测试分支所验证的真实行为与边界。
    assert store_calls == []


@pytest.mark.asyncio
async def test_create_thread_conflict_with_get_failure_propagates_and_does_not_poison_store() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    manager = _new_manager()
    msg = _github_msg()

    class _FakeClient:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        class threads:
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            @staticmethod
            async def create(**kwargs):
                """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
                raise _make_conflict_error()

            @staticmethod
            async def get(thread_id, **kwargs):
                # 说明当前测试分支所验证的真实行为与边界。
                """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
                raise RuntimeError("HTTP 404: thread not found")

    store_calls: list = []

    async def _fake_store(_msg, thread_id):
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        store_calls.append(thread_id)

    with patch.object(manager, "_store_thread_id", new=_fake_store):
        with pytest.raises(RuntimeError, match="404"):
            await manager._create_thread(_FakeClient(), msg)

    # 说明当前测试分支所验证的真实行为与边界。
    assert store_calls == []


@pytest.mark.asyncio
async def test_create_thread_without_preferred_id_propagates_error() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    manager = _new_manager()
    msg = InboundMessage(
        channel_name="slack",
        chat_id="C1",
        user_id="u",
        text="hi",
        metadata={},  # 说明当前测试分支所验证的真实行为与边界。
    )

    class _FakeClient:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        class threads:
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            @staticmethod
            async def create(**kwargs):
                """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
                raise RuntimeError("HTTP 500: Failed to create thread")

    with patch.object(manager, "_store_thread_id", new=AsyncMock()):
        with pytest.raises(RuntimeError, match="500"):
            await manager._create_thread(_FakeClient(), msg)
