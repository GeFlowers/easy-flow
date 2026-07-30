"""覆盖本模块的可回归测试，固定关键输入、失败分支与资源生命周期，避免后续改动破坏既有契约。"""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def sandbox():
    """执行“沙箱”的测试辅助步骤，维持断言所依赖的状态、失败分支与资源生命周期。"""
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox

        sb = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
        return sb


class TestExecuteCommandSerialization:
    """归集“执行命令串行化”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""

    def test_lock_prevents_concurrent_execution(self, sandbox):
        """验证“锁该项并发该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        call_log = []
        barrier = threading.Barrier(3)

        def slow_exec(command, **kwargs):
            """为“该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            call_log.append(("enter", command))
            import time

            time.sleep(0.05)
            call_log.append(("exit", command))
            return SimpleNamespace(data=SimpleNamespace(output=f"ok: {command}"))

        sandbox._client.shell.exec_command = slow_exec

        def worker(cmd):
            """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            barrier.wait()  # 确保所有线程同时争夺锁
            sandbox.execute_command(cmd)

        threads = []
        for i in range(3):
            t = threading.Thread(target=worker, args=(f"cmd-{i}",))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 验证序列化：每个“输入”后面应该跟着自己的
        # 在下一个“输入”之前“退出”（无交错）。
        enters = [i for i, (action, _) in enumerate(call_log) if action == "enter"]
        exits = [i for i, (action, _) in enumerate(call_log) if action == "exit"]
        assert len(enters) == 3
        assert len(exits) == 3
        for e_idx, x_idx in zip(enters, exits):
            assert x_idx == e_idx + 1, f"Interleaved execution detected: {call_log}"


class TestErrorObservationRetry:
    """归集“错误观测重试”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""

    def test_retry_on_error_observation(self, sandbox):
        """验证“重试该项错误观测”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        call_count = 0

        def mock_exec(command, **kwargs):
            """为“模拟该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return SimpleNamespace(data=SimpleNamespace(output="'ErrorObservation' object has no attribute 'exit_code'"))
            return SimpleNamespace(data=SimpleNamespace(output="success"))

        sandbox._client.shell.exec_command = mock_exec

        result = sandbox.execute_command("echo hello")
        assert result == "success"
        assert call_count == 2

    def test_retry_creates_fresh_session_before_targeting_it(self, sandbox):
        """验证“重试该项新建会话该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        exec_calls = []
        created_ids = []
        cleaned_ids = []

        def mock_exec(command, **kwargs):
            """为“模拟该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            exec_calls.append(kwargs)
            if len(exec_calls) == 1:
                return SimpleNamespace(data=SimpleNamespace(output="'ErrorObservation' object has no attribute 'exit_code'"))
            return SimpleNamespace(data=SimpleNamespace(output="ok"))

        def mock_create_session(id, **kwargs):
            """为“模拟创建会话”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            created_ids.append(id)
            return SimpleNamespace(data=SimpleNamespace(session_id=id))

        def mock_cleanup_session(session_id, **kwargs):
            """为“模拟清理会话”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            cleaned_ids.append(session_id)

        sandbox._client.shell.exec_command = mock_exec
        sandbox._client.shell.create_session = mock_create_session
        sandbox._client.shell.cleanup_session = mock_cleanup_session

        result = sandbox.execute_command("test")

        assert result == "ok"
        assert len(exec_calls) == 2
        # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
        assert "id" not in exec_calls[0]
        # 显式创建了一个新会话...
        assert len(created_ids) == 1
        assert len(created_ids[0]) == 36  # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
        # ...并且重试的目标正是创建的会话，而不是
        # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
        assert exec_calls[1].get("id") == created_ids[0]
        # ...并且该一次性恢复会话随后被释放，因此
        # 不断发生损坏的沙箱不会累积会话。
        assert cleaned_ids == [created_ids[0]]

    def test_cleanup_failure_does_not_mask_successful_retry(self, sandbox):
        """验证“清理失败该项该项该项该项重试”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""

        def mock_exec(command, **kwargs):
            """为“模拟该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            if "id" not in kwargs:
                return SimpleNamespace(data=SimpleNamespace(output="'ErrorObservation' object has no attribute 'exit_code'"))
            return SimpleNamespace(data=SimpleNamespace(output="recovered"))

        def mock_cleanup_session(session_id, **kwargs):
            """为“模拟清理会话”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            raise RuntimeError("cleanup boom")

        sandbox._client.shell.exec_command = mock_exec
        sandbox._client.shell.create_session = lambda id, **kwargs: SimpleNamespace(data=SimpleNamespace(session_id=id))
        sandbox._client.shell.cleanup_session = mock_cleanup_session

        # 重试成功；吞没的清理错误一定不能改变这个
        # 变成“错误：...”结果。
        assert sandbox.execute_command("test") == "recovered"

    def test_no_retry_on_clean_output(self, sandbox):
        """验证“该项重试该项该项输出”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        call_count = 0

        def mock_exec(command, **kwargs):
            """为“模拟该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            nonlocal call_count
            call_count += 1
            return SimpleNamespace(data=SimpleNamespace(output="all good"))

        sandbox._client.shell.exec_command = mock_exec

        result = sandbox.execute_command("echo hello")
        assert result == "all good"
        assert call_count == 1


class TestBashExecUnsupportedFailFast:
    """归集“该项该项不支持该项该项”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""

    def _api_error_404(self):
        """为“接口错误该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        from agent_sandbox.core.api_error import ApiError

        return ApiError(
            headers={"server": "nginx/1.18.0 (Ubuntu)"},
            status_code=404,
            body={"success": False, "message": "Not Found", "data": None},
        )

    def test_bash_exec_404_returns_actionable_error(self, sandbox):
        """验证“该项该项该项返回该项错误”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        sandbox._client.bash.exec = MagicMock(side_effect=self._api_error_404())

        out = sandbox.execute_command("echo $TOK", env={"TOK": "secret-v"})

        assert out.startswith("Error:")
        # 可操作：列出缺少的功能和最低映像版本。
        assert "/v1/bash/exec" in out
        assert "1.9.3" in out
        assert "required-secrets" in out
        # 不是模型无法作用的原始上游 404 主体。
        assert "nginx" not in out

    def test_bash_exec_404_is_cached_and_stops_retry_storm(self, sandbox):
        """验证“该项该项该项该项缓存该项该项重试该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        sandbox._client.bash.exec = MagicMock(side_effect=self._api_error_404())

        first = sandbox.execute_command("cmd-1", env={"TOK": "v"})
        second = sandbox.execute_command("cmd-2", env={"TOK": "v"})

        assert sandbox._client.bash.exec.call_count == 1
        assert first == second
        assert "1.9.3" in second

    def test_bash_exec_non_404_error_is_not_cached(self, sandbox):
        """验证“该项该项该项该项错误该项该项缓存”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        from agent_sandbox.core.api_error import ApiError

        sandbox._client.bash.exec = MagicMock(side_effect=ApiError(status_code=500, body="boom"))

        first = sandbox.execute_command("cmd-1", env={"TOK": "v"})
        second = sandbox.execute_command("cmd-2", env={"TOK": "v"})

        assert sandbox._client.bash.exec.call_count == 2
        assert first.startswith("Error:")
        assert "1.9.3" not in first
        assert second.startswith("Error:")

    def test_env_less_path_unaffected_after_404(self, sandbox):
        """验证“环境变量该项路径该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        sandbox._client.bash.exec = MagicMock(side_effect=self._api_error_404())
        sandbox._client.shell.exec_command = MagicMock(return_value=SimpleNamespace(data=SimpleNamespace(output="plain ok")))

        sandbox.execute_command("cmd", env={"TOK": "v"})
        out = sandbox.execute_command("echo plain")

        assert out == "plain ok"
        sandbox._client.shell.exec_command.assert_called_once()

    def test_bash_exec_success_does_not_mark_unsupported(self, sandbox):
        """验证“该项该项该项该项该项该项不支持”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        sandbox._client.bash.exec = MagicMock(return_value=SimpleNamespace(data=SimpleNamespace(stdout="ok", stderr=None)))

        first = sandbox.execute_command("cmd-1", env={"TOK": "v"})
        second = sandbox.execute_command("cmd-2", env={"TOK": "v"})

        assert first == "ok"
        assert second == "ok"
        assert sandbox._client.bash.exec.call_count == 2


class TestListDirSerialization:
    """归集“列出目录串行化”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""

    def test_list_dir_uses_lock(self, sandbox):
        """验证“列出目录使用锁”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        lock_was_held = []

        original_exec = MagicMock(return_value=SimpleNamespace(data=SimpleNamespace(output="/a\n/b")))

        def tracking_exec(command, **kwargs):
            """为“该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            lock_was_held.append(sandbox._lock.locked())
            return original_exec(command, **kwargs)

        sandbox._client.shell.exec_command = tracking_exec

        result = sandbox.list_dir("/test")
        assert result == ["/a", "/b"]
        assert lock_was_held == [True], "list_dir must hold the lock during exec_command"


class TestNoChangeTimeout:
    """归集“该项变化超时”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""

    def test_execute_command_passes_no_change_timeout(self, sandbox):
        """验证“执行命令该项该项变化超时”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        calls = []

        def mock_exec(command, **kwargs):
            """为“模拟该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            calls.append(kwargs)
            return SimpleNamespace(data=SimpleNamespace(output="ok"))

        sandbox._client.shell.exec_command = mock_exec

        sandbox.execute_command("echo hello")

        assert len(calls) == 1
        assert calls[0].get("no_change_timeout") == sandbox._DEFAULT_NO_CHANGE_TIMEOUT

    def test_retry_passes_no_change_timeout(self, sandbox):
        """验证“重试该项该项变化超时”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        calls = []

        def mock_exec(command, **kwargs):
            """为“模拟该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            calls.append(kwargs)
            if len(calls) == 1:
                return SimpleNamespace(data=SimpleNamespace(output="'ErrorObservation' object has no attribute 'exit_code'"))
            return SimpleNamespace(data=SimpleNamespace(output="ok"))

        sandbox._client.shell.exec_command = mock_exec

        sandbox.execute_command("echo hello")

        assert len(calls) == 2
        assert calls[0].get("no_change_timeout") == sandbox._DEFAULT_NO_CHANGE_TIMEOUT
        assert calls[1].get("no_change_timeout") == sandbox._DEFAULT_NO_CHANGE_TIMEOUT

    def test_list_dir_passes_no_change_timeout(self, sandbox):
        """验证“列出目录该项该项变化超时”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        calls = []

        def mock_exec(command, **kwargs):
            """为“模拟该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            calls.append(kwargs)
            return SimpleNamespace(data=SimpleNamespace(output="/a\n/b"))

        sandbox._client.shell.exec_command = mock_exec

        sandbox.list_dir("/test")

        assert len(calls) == 1
        assert calls[0].get("no_change_timeout") == sandbox._DEFAULT_NO_CHANGE_TIMEOUT


class TestConcurrentFileWrites:
    """归集“并发文件该项”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""

    def test_append_should_preserve_both_parallel_writes(self, sandbox):
        """验证“追加该项该项该项并行该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        storage = {"content": "seed\n"}
        active_reads = 0
        state_lock = threading.Lock()
        overlap_detected = threading.Event()

        def overlapping_read_file(path):
            """为“该项读取文件”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            nonlocal active_reads
            with state_lock:
                active_reads += 1
                snapshot = storage["content"]
                if active_reads == 2:
                    overlap_detected.set()

            overlap_detected.wait(0.05)

            with state_lock:
                active_reads -= 1

            return snapshot

        def write_back(*, file, content, **kwargs):
            """为“写入该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            storage["content"] = content
            return SimpleNamespace(data=SimpleNamespace())

        sandbox.read_file = overlapping_read_file
        sandbox._client.file.write_file = write_back

        barrier = threading.Barrier(2)

        def writer(payload: str):
            """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            barrier.wait()
            sandbox.write_file("/tmp/shared.log", payload, append=True)

        threads = [
            threading.Thread(target=writer, args=("A\n",)),
            threading.Thread(target=writer, args=("B\n",)),
        ]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert storage["content"] in {"seed\nA\nB\n", "seed\nB\nA\n"}


class TestDownloadFile:
    """归集“下载文件”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""

    def test_returns_concatenated_bytes(self, sandbox):
        """验证“返回该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        sandbox._client.file.download_file = MagicMock(return_value=[b"hel", b"lo"])

        result = sandbox.download_file("/mnt/user-data/outputs/file.bin")

        assert result == b"hello"
        sandbox._client.file.download_file.assert_called_once_with(path="/mnt/user-data/outputs/file.bin")

    def test_returns_empty_bytes_for_empty_file(self, sandbox):
        """验证“返回空值该项该项空值文件”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        sandbox._client.file.download_file = MagicMock(return_value=iter([]))

        result = sandbox.download_file("/mnt/user-data/outputs/empty.bin")

        assert result == b""

    def test_uses_lock_during_download(self, sandbox):
        """验证“使用锁该项下载”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        lock_was_held = []

        def tracking_download(path):
            """为“该项下载”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            lock_was_held.append(sandbox._lock.locked())
            return iter([b"data"])

        sandbox._client.file.download_file = tracking_download

        sandbox.download_file("/mnt/user-data/outputs/file.bin")

        assert lock_was_held == [True], "download_file must hold the lock during client call"

    def test_raises_oserror_on_client_error(self, sandbox):
        """验证“抛出该项该项客户端错误”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        sandbox._client.file.download_file = MagicMock(side_effect=RuntimeError("network error"))

        with pytest.raises(OSError, match="network error"):
            sandbox.download_file("/mnt/user-data/outputs/file.bin")

    def test_preserves_oserror_from_client(self, sandbox):
        """验证“保留该项该项客户端”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        sandbox._client.file.download_file = MagicMock(side_effect=OSError("disk error"))

        with pytest.raises(OSError, match="disk error"):
            sandbox.download_file("/mnt/user-data/outputs/file.bin")

    def test_rejects_path_outside_virtual_prefix_and_logs_error(self, sandbox, caplog):
        """验证“拒绝路径该项该项该项该项该项错误”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        sandbox._client.file.download_file = MagicMock()

        with caplog.at_level("ERROR"):
            with pytest.raises(PermissionError, match="must be under"):
                sandbox.download_file("/etc/passwd")

        assert "outside allowed directory" in caplog.text
        sandbox._client.file.download_file.assert_not_called()

    @pytest.mark.parametrize(
        "path",
        [
            "/mnt/workspace/../../etc/passwd",
            "../secret",
            "/a/b/../../../etc/shadow",
        ],
    )
    def test_rejects_path_traversal(self, sandbox, path):
        """验证“拒绝路径越界遍历”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        sandbox._client.file.download_file = MagicMock()

        with pytest.raises(PermissionError, match="path traversal"):
            sandbox.download_file(path)

        sandbox._client.file.download_file.assert_not_called()

    def test_single_chunk(self, sandbox):
        """验证“该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        sandbox._client.file.download_file = MagicMock(return_value=[b"single-chunk"])

        result = sandbox.download_file("/mnt/user-data/outputs/single.bin")

        assert result == b"single-chunk"


class TestClose:
    """归集“该项”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""

    def test_close_calls_real_nested_httpx_client(self, sandbox):
        """验证“该项该项该项该项该项客户端”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        real_httpx = MagicMock(spec=["close"])
        fern_http = SimpleNamespace(httpx_client=real_httpx)  # 该层没有关闭
        sandbox._client._client_wrapper = SimpleNamespace(httpx_client=fern_http)

        sandbox.close()

        real_httpx.close.assert_called_once_with()

    def test_close_clears_client_reference(self, sandbox):
        """验证“该项清除客户端该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        real_httpx = MagicMock(spec=["close"])
        fern_http = SimpleNamespace(httpx_client=real_httpx)
        sandbox._client._client_wrapper = SimpleNamespace(httpx_client=fern_http)

        sandbox.close()

        assert sandbox._client is None
        assert sandbox._closed is True

    def test_close_is_idempotent(self, sandbox):
        """验证“该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        real_httpx = MagicMock(spec=["close"])
        fern_http = SimpleNamespace(httpx_client=real_httpx)
        sandbox._client._client_wrapper = SimpleNamespace(httpx_client=fern_http)

        sandbox.close()
        sandbox.close()
        sandbox.close()

        assert real_httpx.close.call_count == 1

    def test_close_swallows_exceptions(self, sandbox, caplog):
        """验证“该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        real_httpx = MagicMock(spec=["close"])
        real_httpx.close.side_effect = RuntimeError("teardown boom")
        fern_http = SimpleNamespace(httpx_client=real_httpx)
        sandbox._client._client_wrapper = SimpleNamespace(httpx_client=fern_http)

        with caplog.at_level("WARNING"):
            sandbox.close()

        assert "Error closing AioSandbox client" in caplog.text

    def test_close_falls_back_to_client_close(self, sandbox):
        """验证“该项该项该项该项客户端该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
        client = MagicMock(spec=["close"])
        sandbox._client = client

        sandbox.close()

        client.close.assert_called_once_with()

    def test_close_when_no_close_attr_does_not_raise(self, sandbox):
        """验证“该项当该项该项该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        sandbox._client = SimpleNamespace()  # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
        sandbox.close()  # 不得提出
        assert sandbox._client is None
