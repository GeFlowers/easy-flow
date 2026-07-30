"""本模块覆盖相关测试，固定公开行为、失败处理与状态边界。"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.channels.base import Channel
from app.channels.message_bus import InboundMessage, MessageBus, OutboundMessage, ResolvedAttachment


def _run(coro):
    """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# 已解决的附件测试
# ---------------------------------------------------------------------------


class TestResolvedAttachment:
    """此测试组归集同一组件的用例，分别约束正常流程与关键边界条件。"""
    def test_basic_construction(self, tmp_path):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过3项断言固定返回、状态或副作用边界。"""
        f = tmp_path / "test.pdf"
        f.write_bytes(b"PDF content")

        att = ResolvedAttachment(
            virtual_path="/mnt/user-data/outputs/test.pdf",
            actual_path=f,
            filename="test.pdf",
            mime_type="application/pdf",
            size=11,
            is_image=False,
        )
        assert att.filename == "test.pdf"
        assert att.is_image is False
        assert att.size == 11

    def test_image_detection(self, tmp_path):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过1项断言固定返回、状态或副作用边界。"""
        f = tmp_path / "photo.png"
        f.write_bytes(b"\x89PNG")

        att = ResolvedAttachment(
            virtual_path="/mnt/user-data/outputs/photo.png",
            actual_path=f,
            filename="photo.png",
            mime_type="image/png",
            size=4,
            is_image=True,
        )
        assert att.is_image is True


# ---------------------------------------------------------------------------
# 此处说明该测试段的前置条件、调用限制及预期边界。
# ---------------------------------------------------------------------------


class TestOutboundMessageAttachments:
    """此测试组归集同一组件的用例，分别约束正常流程与关键边界条件。"""
    def test_default_empty_attachments(self):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过1项断言固定返回、状态或副作用边界。"""
        msg = OutboundMessage(
            channel_name="test",
            chat_id="c1",
            thread_id="t1",
            text="hello",
        )
        assert msg.attachments == []

    def test_attachments_populated(self, tmp_path):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过2项断言固定返回、状态或副作用边界。"""
        f = tmp_path / "file.txt"
        f.write_text("content")

        att = ResolvedAttachment(
            virtual_path="/mnt/user-data/outputs/file.txt",
            actual_path=f,
            filename="file.txt",
            mime_type="text/plain",
            size=7,
            is_image=False,
        )
        msg = OutboundMessage(
            channel_name="test",
            chat_id="c1",
            thread_id="t1",
            text="hello",
            attachments=[att],
        )
        assert len(msg.attachments) == 1
        assert msg.attachments[0].filename == "file.txt"


# ---------------------------------------------------------------------------
# 此处说明该测试段的前置条件、调用限制及预期边界。
# ---------------------------------------------------------------------------


class TestResolveAttachments:
    """此测试组归集同一组件的用例，分别约束正常流程与关键边界条件。"""
    def test_resolves_existing_file(self, tmp_path):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过5项断言固定返回、状态或副作用边界。"""
        from app.channels.manager import _resolve_attachments

        # 此处说明该测试段的前置条件、调用限制及预期边界。
        thread_id = "test-thread-123"
        outputs_dir = tmp_path / "threads" / thread_id / "user-data" / "outputs"
        outputs_dir.mkdir(parents=True)
        test_file = outputs_dir / "report.pdf"
        test_file.write_bytes(b"%PDF-1.4 fake content")

        mock_paths = MagicMock()
        mock_paths.resolve_virtual_path.return_value = test_file
        mock_paths.sandbox_outputs_dir.return_value = outputs_dir

        with patch("deerflow.config.paths.get_paths", return_value=mock_paths):
            result = _resolve_attachments(thread_id, ["/mnt/user-data/outputs/report.pdf"])

        assert len(result) == 1
        assert result[0].filename == "report.pdf"
        assert result[0].mime_type == "application/pdf"
        assert result[0].is_image is False
        assert result[0].size == len(b"%PDF-1.4 fake content")

    def test_resolves_image_file(self, tmp_path):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过3项断言固定返回、状态或副作用边界。"""
        from app.channels.manager import _resolve_attachments

        thread_id = "test-thread"
        outputs_dir = tmp_path / "threads" / thread_id / "user-data" / "outputs"
        outputs_dir.mkdir(parents=True)
        img = outputs_dir / "chart.png"
        img.write_bytes(b"\x89PNG fake image")

        mock_paths = MagicMock()
        mock_paths.resolve_virtual_path.return_value = img
        mock_paths.sandbox_outputs_dir.return_value = outputs_dir

        with patch("deerflow.config.paths.get_paths", return_value=mock_paths):
            result = _resolve_attachments(thread_id, ["/mnt/user-data/outputs/chart.png"])

        assert len(result) == 1
        assert result[0].is_image is True
        assert result[0].mime_type == "image/png"

    def test_skips_missing_file(self, tmp_path):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过1项断言固定返回、状态或副作用边界。"""
        from app.channels.manager import _resolve_attachments

        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()

        mock_paths = MagicMock()
        mock_paths.resolve_virtual_path.return_value = outputs_dir / "nonexistent.txt"
        mock_paths.sandbox_outputs_dir.return_value = outputs_dir

        with patch("deerflow.config.paths.get_paths", return_value=mock_paths):
            result = _resolve_attachments("t1", ["/mnt/user-data/outputs/nonexistent.txt"])

        assert result == []

    def test_skips_invalid_path(self):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过1项断言固定返回、状态或副作用边界。"""
        from app.channels.manager import _resolve_attachments

        mock_paths = MagicMock()
        mock_paths.resolve_virtual_path.side_effect = ValueError("bad path")

        with patch("deerflow.config.paths.get_paths", return_value=mock_paths):
            result = _resolve_attachments("t1", ["/invalid/path"])

        assert result == []

    def test_rejects_uploads_path(self):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过1项断言固定返回、状态或副作用边界。"""
        from app.channels.manager import _resolve_attachments

        mock_paths = MagicMock()

        with patch("deerflow.config.paths.get_paths", return_value=mock_paths):
            result = _resolve_attachments("t1", ["/mnt/user-data/uploads/secret.pdf"])

        assert result == []
        mock_paths.resolve_virtual_path.assert_not_called()

    def test_rejects_workspace_path(self):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过1项断言固定返回、状态或副作用边界。"""
        from app.channels.manager import _resolve_attachments

        mock_paths = MagicMock()

        with patch("deerflow.config.paths.get_paths", return_value=mock_paths):
            result = _resolve_attachments("t1", ["/mnt/user-data/workspace/config.py"])

        assert result == []
        mock_paths.resolve_virtual_path.assert_not_called()

    def test_rejects_path_traversal_escape(self, tmp_path):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过1项断言固定返回、状态或副作用边界。"""
        from app.channels.manager import _resolve_attachments

        thread_id = "t1"
        outputs_dir = tmp_path / "threads" / thread_id / "user-data" / "outputs"
        outputs_dir.mkdir(parents=True)
        # 模拟转义到输出目录之外的已解析路径
        escaped_file = tmp_path / "threads" / thread_id / "user-data" / "uploads" / "stolen.txt"
        escaped_file.parent.mkdir(parents=True, exist_ok=True)
        escaped_file.write_text("sensitive")

        mock_paths = MagicMock()
        mock_paths.resolve_virtual_path.return_value = escaped_file
        mock_paths.sandbox_outputs_dir.return_value = outputs_dir

        with patch("deerflow.config.paths.get_paths", return_value=mock_paths):
            result = _resolve_attachments(thread_id, ["/mnt/user-data/outputs/../uploads/stolen.txt"])

        assert result == []

    def test_multiple_artifacts_partial_resolution(self, tmp_path):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过2项断言固定返回、状态或副作用边界。"""
        from app.channels.manager import _resolve_attachments

        thread_id = "t1"
        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()
        good_file = outputs_dir / "data.csv"
        good_file.write_text("a,b,c")

        mock_paths = MagicMock()
        mock_paths.sandbox_outputs_dir.return_value = outputs_dir

        def resolve_side_effect(tid, vpath, *, user_id=None):
            """模拟本用例所需的外部交互，为调用方提供受控返回、异常或调用记录。"""
            if "data.csv" in vpath:
                return good_file
            return tmp_path / "missing.txt"

        mock_paths.resolve_virtual_path.side_effect = resolve_side_effect

        with patch("deerflow.config.paths.get_paths", return_value=mock_paths):
            result = _resolve_attachments(
                thread_id,
                ["/mnt/user-data/outputs/data.csv", "/mnt/user-data/outputs/missing.txt"],
            )

        assert len(result) == 1
        assert result[0].filename == "data.csv"


# ---------------------------------------------------------------------------
# 入站文件摄取测试
# ---------------------------------------------------------------------------


class TestInboundFileIngestion:
    """此测试组归集同一组件的用例，分别约束正常流程与关键边界条件。"""
    def test_rejects_preexisting_symlink_destination(self, tmp_path):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过3项断言固定返回、状态或副作用边界。"""
        from app.channels import manager

        uploads_dir = tmp_path / "uploads"
        uploads_dir.mkdir()
        outside_file = tmp_path / "outside-created.txt"
        (uploads_dir / "victim.txt").symlink_to(outside_file)

        msg = InboundMessage(
            channel_name="test-channel",
            chat_id="chat-1",
            user_id="user-1",
            text="see attachment",
            files=[{"filename": "victim.txt", "url": "https://example.invalid/victim.txt"}],
        )

        async def fake_reader(file_info, client):
            """模拟本用例所需的外部交互，为调用方提供受控返回、异常或调用记录。"""
            return b"attacker data"

        with (
            patch("deerflow.uploads.manager.ensure_uploads_dir", return_value=uploads_dir),
            patch.dict(manager.INBOUND_FILE_READERS, {"test-channel": fake_reader}, clear=False),
        ):
            result = _run(manager._ingest_inbound_files("thread-1", msg))

        assert result == []
        assert not outside_file.exists()
        assert (uploads_dir / "victim.txt").is_symlink()

    def test_rejects_dangling_symlink_destination(self, tmp_path):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过3项断言固定返回、状态或副作用边界。"""
        from app.channels import manager

        uploads_dir = tmp_path / "uploads"
        uploads_dir.mkdir()
        missing_target = tmp_path / "missing-created.txt"
        (uploads_dir / "victim.txt").symlink_to(missing_target)

        msg = InboundMessage(
            channel_name="test-channel",
            chat_id="chat-1",
            user_id="user-1",
            text="see attachment",
            files=[{"filename": "victim.txt", "url": "https://example.invalid/victim.txt"}],
        )

        async def fake_reader(file_info, client):
            """模拟本用例所需的外部交互，为调用方提供受控返回、异常或调用记录。"""
            return b"attacker data"

        with (
            patch("deerflow.uploads.manager.ensure_uploads_dir", return_value=uploads_dir),
            patch.dict(manager.INBOUND_FILE_READERS, {"test-channel": fake_reader}, clear=False),
        ):
            result = _run(manager._ingest_inbound_files("thread-1", msg))

        assert result == []
        assert not missing_target.exists()
        assert (uploads_dir / "victim.txt").is_symlink()

    def test_hardlinked_existing_file_is_not_overwritten(self, tmp_path):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过4项断言固定返回、状态或副作用边界。"""
        from app.channels import manager

        uploads_dir = tmp_path / "uploads"
        uploads_dir.mkdir()
        outside_file = tmp_path / "outside-created.txt"
        outside_file.write_text("protected", encoding="utf-8")
        os.link(outside_file, uploads_dir / "victim.txt")

        msg = InboundMessage(
            channel_name="test-channel",
            chat_id="chat-1",
            user_id="user-1",
            text="see attachment",
            files=[{"filename": "victim.txt", "url": "https://example.invalid/victim.txt"}],
        )

        async def fake_reader(file_info, client):
            """模拟本用例所需的外部交互，为调用方提供受控返回、异常或调用记录。"""
            return b"new attachment data"

        with (
            patch("deerflow.uploads.manager.ensure_uploads_dir", return_value=uploads_dir),
            patch.dict(manager.INBOUND_FILE_READERS, {"test-channel": fake_reader}, clear=False),
        ):
            result = _run(manager._ingest_inbound_files("thread-1", msg))

        assert result == [
            {
                "filename": "victim_1.txt",
                "size": len(b"new attachment data"),
                "path": "/mnt/user-data/uploads/victim_1.txt",
                "is_image": False,
            }
        ]
        assert outside_file.read_text(encoding="utf-8") == "protected"
        assert (uploads_dir / "victim.txt").read_text(encoding="utf-8") == "protected"
        assert (uploads_dir / "victim_1.txt").read_bytes() == b"new attachment data"


# ---------------------------------------------------------------------------
# 此处说明该测试段的前置条件、调用限制及预期边界。
# ---------------------------------------------------------------------------


class _DummyChannel(Channel):
    """此测试组归集同一组件的用例，分别约束正常流程与关键边界条件。"""

    def __init__(self, bus):
        """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
        super().__init__(name="dummy", bus=bus, config={})
        self.sent_messages: list[OutboundMessage] = []
        self.sent_files: list[tuple[OutboundMessage, ResolvedAttachment]] = []

    async def start(self):
        """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
        pass

    async def stop(self):
        """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
        pass

    async def send(self, msg: OutboundMessage) -> None:
        """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
        self.sent_messages.append(msg)

    async def send_file(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
        self.sent_files.append((msg, attachment))
        return True


class TestBaseChannelOnOutbound:
    """此测试组归集同一组件的用例，分别约束正常流程与关键边界条件。"""
    def test_default_receive_file_returns_original_message(self):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过3项断言固定返回、状态或副作用边界。"""

        class MinimalChannel(Channel):
            """此测试组归集同一组件的用例，分别约束正常流程与关键边界条件。"""
            async def start(self):
                """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
                pass

            async def stop(self):
                """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
                pass

            async def send(self, msg):
                """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
                pass

        from app.channels.message_bus import InboundMessage

        bus = MessageBus()
        ch = MinimalChannel(name="minimal", bus=bus, config={})
        msg = InboundMessage(channel_name="minimal", chat_id="c1", user_id="u1", text="hello", files=[{"file_key": "k1"}])

        result = _run(ch.receive_file(msg, "thread-1"))

        assert result is msg
        assert result.text == "hello"
        assert result.files == [{"file_key": "k1"}]

    def test_send_file_called_for_each_attachment(self, tmp_path):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过4项断言固定返回、状态或副作用边界。"""
        bus = MessageBus()
        ch = _DummyChannel(bus)

        f1 = tmp_path / "a.txt"
        f1.write_text("aaa")
        f2 = tmp_path / "b.png"
        f2.write_bytes(b"\x89PNG")

        att1 = ResolvedAttachment("/mnt/user-data/outputs/a.txt", f1, "a.txt", "text/plain", 3, False)
        att2 = ResolvedAttachment("/mnt/user-data/outputs/b.png", f2, "b.png", "image/png", 4, True)

        msg = OutboundMessage(
            channel_name="dummy",
            chat_id="c1",
            thread_id="t1",
            text="Here are your files",
            attachments=[att1, att2],
        )

        _run(ch._on_outbound(msg))

        assert len(ch.sent_messages) == 1
        assert len(ch.sent_files) == 2
        assert ch.sent_files[0][1].filename == "a.txt"
        assert ch.sent_files[1][1].filename == "b.png"

    def test_no_attachments_no_send_file(self):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过2项断言固定返回、状态或副作用边界。"""
        bus = MessageBus()
        ch = _DummyChannel(bus)

        msg = OutboundMessage(
            channel_name="dummy",
            chat_id="c1",
            thread_id="t1",
            text="No files here",
        )

        _run(ch._on_outbound(msg))

        assert len(ch.sent_messages) == 1
        assert len(ch.sent_files) == 0

    def test_send_file_failure_does_not_block_others(self, tmp_path):
        """验证当前场景的异步、异常调用：使用受控输入与依赖替身，通过2项断言固定返回、状态或副作用边界。"""
        bus = MessageBus()
        ch = _DummyChannel(bus)

        # 此处说明该测试段的前置条件、调用限制及预期边界。
        call_count = 0
        original_send_file = ch.send_file

        async def flaky_send_file(msg, att):
            """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("upload failed")
            return await original_send_file(msg, att)

        ch.send_file = flaky_send_file  # 此处说明该测试段的前置条件、调用限制及预期边界。

        f1 = tmp_path / "fail.txt"
        f1.write_text("x")
        f2 = tmp_path / "ok.txt"
        f2.write_text("y")

        att1 = ResolvedAttachment("/mnt/user-data/outputs/fail.txt", f1, "fail.txt", "text/plain", 1, False)
        att2 = ResolvedAttachment("/mnt/user-data/outputs/ok.txt", f2, "ok.txt", "text/plain", 1, False)

        msg = OutboundMessage(
            channel_name="dummy",
            chat_id="c1",
            thread_id="t1",
            text="files",
            attachments=[att1, att2],
        )

        _run(ch._on_outbound(msg))

        # 第一次上传失败，第二次成功
        assert len(ch.sent_files) == 1
        assert ch.sent_files[0][1].filename == "ok.txt"

    def test_send_raises_skips_file_uploads(self, tmp_path):
        """验证当前场景的异常调用：使用受控输入与依赖替身，通过1项断言固定返回、状态或副作用边界。"""
        bus = MessageBus()
        ch = _DummyChannel(bus)

        async def failing_send(msg):
            """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
            raise RuntimeError("network error")

        ch.send = failing_send  # 此处说明该测试段的前置条件、调用限制及预期边界。

        f = tmp_path / "a.pdf"
        f.write_bytes(b"%PDF")
        att = ResolvedAttachment("/mnt/user-data/outputs/a.pdf", f, "a.pdf", "application/pdf", 4, False)
        msg = OutboundMessage(
            channel_name="dummy",
            chat_id="c1",
            thread_id="t1",
            text="Here is the file",
            attachments=[att],
        )

        _run(ch._on_outbound(msg))

        # 此处说明该测试段的前置条件、调用限制及预期边界。
        assert len(ch.sent_files) == 0

    def test_default_send_file_returns_false(self):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过1项断言固定返回、状态或副作用边界。"""

        class MinimalChannel(Channel):
            """此测试组归集同一组件的用例，分别约束正常流程与关键边界条件。"""
            async def start(self):
                """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
                pass

            async def stop(self):
                """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
                pass

            async def send(self, msg):
                """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
                pass

        bus = MessageBus()
        ch = MinimalChannel(name="minimal", bus=bus, config={})
        att = ResolvedAttachment("/x", Path("/x"), "x", "text/plain", 0, False)
        msg = OutboundMessage(channel_name="minimal", chat_id="c", thread_id="t", text="t")

        result = _run(ch.send_file(msg, att))
        assert result is False


# ---------------------------------------------------------------------------
# 此处说明该测试段的前置条件、调用限制及预期边界。
# ---------------------------------------------------------------------------


class TestManagerArtifactResolution:
    """此测试组归集同一组件的用例，分别约束正常流程与关键边界条件。"""
    def test_handle_chat_populates_attachments(self):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过1项断言固定返回、状态或副作用边界。"""
        from app.channels.manager import _resolve_attachments

        # 基本冒烟测试：空工件返回空列表
        mock_paths = MagicMock()
        with patch("deerflow.config.paths.get_paths", return_value=mock_paths):
            result = _resolve_attachments("t1", [])
        assert result == []

    def test_format_artifact_text_for_unresolved(self):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过3项断言固定返回、状态或副作用边界。"""
        from app.channels.manager import _format_artifact_text

        assert "report.pdf" in _format_artifact_text(["/mnt/user-data/outputs/report.pdf"])
        result = _format_artifact_text(["/mnt/user-data/outputs/a.txt", "/mnt/user-data/outputs/b.txt"])
        assert "a.txt" in result
        assert "b.txt" in result
