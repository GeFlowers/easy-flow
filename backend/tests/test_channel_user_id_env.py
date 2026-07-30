"""本模块覆盖相关测试，固定公开行为、失败处理与状态边界。"""

from types import SimpleNamespace

from deerflow.sandbox.tools import (
    CHANNEL_USER_ID_ENV,
    _channel_identity_prefix,
    bash_tool,
)

_THREAD_DATA = {
    "workspace_path": "/tmp/deer-flow/threads/t1/user-data/workspace",
    "uploads_path": "/tmp/deer-flow/threads/t1/user-data/uploads",
    "outputs_path": "/tmp/deer-flow/threads/t1/user-data/outputs",
}


def _aio_runtime(context: dict) -> SimpleNamespace:
    """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
    return SimpleNamespace(
        state={"sandbox": {"sandbox_id": "aio-sandbox-1"}, "thread_data": _THREAD_DATA.copy()},
        context=context,
    )


class _CapturingSandbox:
    """此测试组归集同一组件的用例，分别约束正常流程与关键边界条件。"""
    def __init__(self, output: str = "ok"):
        """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
        self.calls: list[dict] = []
        self._output = output

    def execute_command(self, command: str, env=None, timeout=None) -> str:
        """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
        self.calls.append({"command": command, "env": env})
        return self._output


def _run_bash(monkeypatch, runtime, command: str = "echo hi") -> _CapturingSandbox:
    """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
    sandbox = _CapturingSandbox()
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
    bash_tool.func(runtime=runtime, description="test", command=command)
    return sandbox


class TestMergeRunContextOverridesChannelUserId:
    """此测试组归集同一组件的用例，分别约束正常流程与关键边界条件。"""
    def test_channel_user_id_propagates_to_runtime_context_only(self):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过2项断言固定返回、状态或副作用边界。"""
        from app.gateway.services import build_run_config, merge_run_context_overrides

        config = build_run_config("thread-1", None, None)
        merge_run_context_overrides(config, {"channel_user_id": "ou_feishu_123"})

        assert config["context"]["channel_user_id"] == "ou_feishu_123"
        # 永远不要进入可配置状态：该映射通过线程设置检查点。
        assert "channel_user_id" not in config["configurable"]

    def test_existing_runtime_context_value_wins(self):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过1项断言固定返回、状态或副作用边界。"""
        from app.gateway.services import build_run_config, merge_run_context_overrides

        config = build_run_config("thread-1", None, None)
        config.setdefault("context", {})["channel_user_id"] = "server-stamped"
        merge_run_context_overrides(config, {"channel_user_id": "client-supplied"})

        assert config["context"]["channel_user_id"] == "server-stamped"

    def test_absent_channel_user_id_adds_nothing(self):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过1项断言固定返回、状态或副作用边界。"""
        from app.gateway.services import build_run_config, merge_run_context_overrides

        config = build_run_config("thread-1", None, None)
        merge_run_context_overrides(config, {"model_name": "gpt"})

        assert "channel_user_id" not in config.get("context", {})


class TestBashToolChannelIdentityPrefix:
    """此测试组归集同一组件的用例，分别约束正常流程与关键边界条件。"""
    def test_identity_exported_and_env_stays_none(self, monkeypatch):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过3项断言固定返回、状态或副作用边界。"""
        sandbox = _run_bash(monkeypatch, _aio_runtime({"channel_user_id": "ou_feishu_123"}))

        assert len(sandbox.calls) == 1
        assert sandbox.calls[0]["command"] == f"export {CHANNEL_USER_ID_ENV}=ou_feishu_123; cd /mnt/user-data/workspace; echo hi"
        assert sandbox.calls[0]["env"] is None

    def test_no_channel_user_id_omits_identity_prefix(self, monkeypatch):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过2项断言固定返回、状态或副作用边界。"""
        sandbox = _run_bash(monkeypatch, _aio_runtime({"thread_id": "t1"}))

        assert sandbox.calls[0]["command"] == "cd /mnt/user-data/workspace; echo hi"
        assert sandbox.calls[0]["env"] is None

    def test_per_call_identity_follows_current_context(self, monkeypatch):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过2项断言固定返回、状态或副作用边界。"""
        first = _run_bash(monkeypatch, _aio_runtime({"channel_user_id": "sender-a"}))
        second = _run_bash(monkeypatch, _aio_runtime({"channel_user_id": "sender-b"}))

        assert "sender-a" in first.calls[0]["command"]
        assert "sender-b" in second.calls[0]["command"]

    def test_value_is_shell_quoted(self, monkeypatch):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过2项断言固定返回、状态或副作用边界。"""
        sandbox = _run_bash(monkeypatch, _aio_runtime({"channel_user_id": "x'; rm -rf /tmp/y; '"}))

        command = sandbox.calls[0]["command"]
        assert command.endswith("; cd /mnt/user-data/workspace; echo hi")
        # 此处说明该测试段的前置条件、调用限制及预期边界。
        # 作为引用区域之外的可执行语法。
        assert "export " + CHANNEL_USER_ID_ENV + "='x'\"'\"'; rm -rf /tmp/y; '\"'\"''; cd /mnt/user-data/workspace; echo hi" == command

    def test_secrets_and_identity_compose(self, monkeypatch):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过3项断言固定返回、状态或副作用边界。"""
        runtime = _aio_runtime(
            {
                "channel_user_id": "ou_1",
                "__active_skill_secrets": {"ERP_TOKEN": "secret-value"},
            }
        )
        sandbox = _run_bash(monkeypatch, runtime)

        call = sandbox.calls[0]
        assert call["env"] == {"ERP_TOKEN": "secret-value"}
        assert call["command"] == f"export {CHANNEL_USER_ID_ENV}=ou_1; cd /mnt/user-data/workspace; echo hi"
        assert "secret-value" not in call["command"]

    def test_non_im_run_leaves_command_untouched(self):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过3项断言固定返回、状态或副作用边界。"""
        assert _channel_identity_prefix(SimpleNamespace(context={"thread_id": "t1"})) is None
        assert _channel_identity_prefix(SimpleNamespace(context={})) is None
        assert _channel_identity_prefix(SimpleNamespace(context=None)) is None

    def test_unusable_value_emits_unset_not_none(self, monkeypatch):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过1项断言固定返回、状态或副作用边界。"""
        for bad in ("", 123, "x" * 5000, None):
            prefix = _channel_identity_prefix(SimpleNamespace(context={"channel_user_id": bad}))
            assert prefix == f"unset {CHANNEL_USER_ID_ENV}; ", f"value={bad!r}"

    def test_group_chat_dropped_id_clears_previous_sender(self, monkeypatch):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过3项断言固定返回、状态或副作用边界。"""
        a = _run_bash(monkeypatch, _aio_runtime({"channel_user_id": "sender-a"}))
        b = _run_bash(monkeypatch, _aio_runtime({"channel_user_id": "b" * 5000}))

        assert a.calls[0]["command"] == f"export {CHANNEL_USER_ID_ENV}=sender-a; cd /mnt/user-data/workspace; echo hi"
        assert b.calls[0]["command"] == f"unset {CHANNEL_USER_ID_ENV}; cd /mnt/user-data/workspace; echo hi"
        assert b.calls[0]["env"] is None

    def test_windows_local_sandbox_skips_prefix(self, monkeypatch):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过2项断言固定返回、状态或副作用边界。"""
        runtime = SimpleNamespace(
            state={"sandbox": {"sandbox_id": "local"}, "thread_data": _THREAD_DATA.copy()},
            context={"channel_user_id": "ou_1", "thread_id": "t1"},
        )
        sandbox = _CapturingSandbox()
        monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)
        monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
        monkeypatch.setattr("deerflow.sandbox.tools.is_host_bash_allowed", lambda: True)
        monkeypatch.setattr("deerflow.sandbox.tools._is_windows", lambda: True)

        bash_tool.func(runtime=runtime, description="test", command="echo hi")

        assert len(sandbox.calls) == 1
        assert "export" not in sandbox.calls[0]["command"]

    def test_posix_local_sandbox_gets_prefix(self, monkeypatch):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过3项断言固定返回、状态或副作用边界。"""
        runtime = SimpleNamespace(
            state={"sandbox": {"sandbox_id": "local"}, "thread_data": _THREAD_DATA.copy()},
            context={"channel_user_id": "ou_1", "thread_id": "t1"},
        )
        sandbox = _CapturingSandbox()
        monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)
        monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
        monkeypatch.setattr("deerflow.sandbox.tools.is_host_bash_allowed", lambda: True)

        bash_tool.func(runtime=runtime, description="test", command="echo hi")

        assert len(sandbox.calls) == 1
        command = sandbox.calls[0]["command"]
        assert command.startswith(f"export {CHANNEL_USER_ID_ENV}=ou_1; ")
        assert command.endswith("echo hi")
