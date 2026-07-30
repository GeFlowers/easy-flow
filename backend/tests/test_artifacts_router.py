"""覆盖本模块的可回归测试，固定关键输入、失败分支与资源生命周期，避免后续改动破坏既有契约。"""
import asyncio
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from _router_auth_helpers import call_unwrapped, make_authed_test_app
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import FileResponse

import app.gateway.routers.artifacts as artifacts_router
from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME, INTERNAL_SYSTEM_ROLE
from deerflow.config.paths import make_safe_user_id

ACTIVE_ARTIFACT_CASES = [
    ("poc.html", "<html><body><script>alert('xss')</script></body></html>"),
    ("page.xhtml", '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body>hello</body></html>'),
    ("image.svg", '<svg xmlns="http://www.w3.org/2000/svg"><script>alert("xss")</script></svg>'),
]


def _make_request(query_string: bytes = b"") -> Request:
    """为“构造请求”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": query_string})


def test_get_artifact_reads_utf8_text_file_on_windows_locale(tmp_path, monkeypatch) -> None:
    """验证“获取制品该项统一编码文本文件该项视窗系统区域设置”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    artifact_path = tmp_path / "note.txt"
    text = "Curly quotes: \u201cutf8\u201d"
    artifact_path.write_text(text, encoding="utf-8")

    original_read_text = Path.read_text

    def read_text_with_gbk_default(self, *args, **kwargs):
        """为“读取文本使用该项默认值”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        kwargs.setdefault("encoding", "gbk")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text_with_gbk_default)
    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _thread_id, _path, user_id=None: artifact_path)

    request = _make_request()
    response = asyncio.run(call_unwrapped(artifacts_router.get_artifact, "thread-1", "mnt/user-data/outputs/note.txt", request))

    assert bytes(response.body).decode("utf-8") == text
    assert response.media_type == "text/plain"


@pytest.mark.parametrize(("filename", "content"), ACTIVE_ARTIFACT_CASES)
def test_get_artifact_forces_download_for_active_content(tmp_path, monkeypatch, filename: str, content: str) -> None:
    """验证“获取制品该项下载该项活动内容”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    artifact_path = tmp_path / filename
    artifact_path.write_text(content, encoding="utf-8")

    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _thread_id, _path, user_id=None: artifact_path)

    response = asyncio.run(call_unwrapped(artifacts_router.get_artifact, "thread-1", f"mnt/user-data/outputs/{filename}", _make_request()))

    assert isinstance(response, FileResponse)
    assert response.headers.get("content-disposition", "").startswith("attachment;")


@pytest.mark.parametrize(("filename", "content"), ACTIVE_ARTIFACT_CASES)
def test_get_artifact_forces_download_for_active_content_in_skill_archive(tmp_path, monkeypatch, filename: str, content: str) -> None:
    """验证“获取制品该项下载该项活动内容该项该项归档”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    skill_path = tmp_path / "sample.skill"
    with zipfile.ZipFile(skill_path, "w") as zip_ref:
        zip_ref.writestr(filename, content)

    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _thread_id, _path, user_id=None: skill_path)

    response = asyncio.run(call_unwrapped(artifacts_router.get_artifact, "thread-1", f"mnt/user-data/outputs/sample.skill/{filename}", _make_request()))

    assert response.headers.get("content-disposition", "").startswith("attachment;")
    assert bytes(response.body) == content.encode("utf-8")


def test_get_artifact_download_false_does_not_force_attachment(tmp_path, monkeypatch) -> None:
    """验证“获取制品下载该项该项该项该项附件”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    artifact_path = tmp_path / "note.txt"
    artifact_path.write_text("hello", encoding="utf-8")

    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _thread_id, _path, user_id=None: artifact_path)

    app = make_authed_test_app()
    app.include_router(artifacts_router.router)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/artifacts/mnt/user-data/outputs/note.txt?download=false")

    assert response.status_code == 200
    assert response.text == "hello"
    assert "content-disposition" not in response.headers


def test_get_artifact_download_true_forces_attachment_for_skill_archive(tmp_path, monkeypatch) -> None:
    """验证“获取制品下载该项该项附件该项该项归档”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    skill_path = tmp_path / "sample.skill"
    with zipfile.ZipFile(skill_path, "w") as zip_ref:
        zip_ref.writestr("notes.txt", "hello")

    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _thread_id, _path, user_id=None: skill_path)

    app = make_authed_test_app()
    app.include_router(artifacts_router.router)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/artifacts/mnt/user-data/outputs/sample.skill/notes.txt?download=true")

    assert response.status_code == 200
    assert response.text == "hello"
    assert response.headers.get("content-disposition", "").startswith("attachment;")


def _make_internal_request(owner: str | None, *, system_role: str = INTERNAL_SYSTEM_ROLE) -> Request:
    """为“构造内部请求”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    headers: list[tuple[bytes, bytes]] = []
    if owner is not None:
        headers.append((INTERNAL_OWNER_USER_ID_HEADER_NAME.lower().encode(), owner.encode()))
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": headers, "query_string": b""})
    request.state.user = SimpleNamespace(id="default", system_role=system_role)
    return request


def _capture_resolved_user_id(monkeypatch, tmp_path) -> dict:
    """为“捕获该项用户标识”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    artifact_path = tmp_path / "index.html"
    artifact_path.write_text("<html>", encoding="utf-8")
    seen: dict = {}

    def fake_resolve(_thread_id, _path, user_id=None):
        """为“该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        seen["user_id"] = user_id
        return artifact_path

    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", fake_resolve)
    return seen


def test_get_artifact_scopes_to_trusted_owner_header(tmp_path, monkeypatch) -> None:
    # 代表所有者的内部调用者必须解析下的工件
    # 所有者的存储，而不是合成内部用户。
    """验证“获取制品该项该项可信所有者标头”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    seen = _capture_resolved_user_id(monkeypatch, tmp_path)
    request = _make_internal_request("owner-123")

    asyncio.run(call_unwrapped(artifacts_router.get_artifact, "thread-1", "mnt/user-data/outputs/index.html", request))

    assert seen["user_id"] == "owner-123"


def test_get_artifact_normalizes_raw_owner_id_from_trusted_header(tmp_path, monkeypatch) -> None:
    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    """验证“获取制品标准化原始所有者标识该项可信标头”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    seen = _capture_resolved_user_id(monkeypatch, tmp_path)
    raw_owner = "ou_7d8a.6e6d@example:id"
    request = _make_internal_request(raw_owner)

    asyncio.run(call_unwrapped(artifacts_router.get_artifact, "thread-1", "mnt/user-data/outputs/index.html", request))

    assert seen["user_id"] == make_safe_user_id(raw_owner)
    assert seen["user_id"] != raw_owner


def test_get_artifact_without_owner_header_falls_back_to_effective_user(tmp_path, monkeypatch) -> None:
    # 无所有者标头 → 无覆盖；解决方案回落给有效用户
    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    """验证“获取制品不使用所有者标头该项该项该项有效用户”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    seen = _capture_resolved_user_id(monkeypatch, tmp_path)
    request = _make_internal_request(None)

    asyncio.run(call_unwrapped(artifacts_router.get_artifact, "thread-1", "mnt/user-data/outputs/index.html", request))

    assert seen["user_id"] is None


def test_get_artifact_ignores_owner_header_for_non_internal_caller(tmp_path, monkeypatch) -> None:
    # 所有者标头仅对内部调用者可信；普通用户
    # 携带它的
    # 不能读取其他用户的存储。
    """验证“获取制品忽略所有者标头该项该项内部该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    seen = _capture_resolved_user_id(monkeypatch, tmp_path)
    request = _make_internal_request("owner-123", system_role="user")

    asyncio.run(call_unwrapped(artifacts_router.get_artifact, "thread-1", "mnt/user-data/outputs/index.html", request))

    assert seen["user_id"] is None


def test_skill_archive_preview_rejects_oversized_member_before_decompression(tmp_path) -> None:
    """验证“该项归档预览拒绝该项成员该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    skill_path = tmp_path / "sample.skill"
    payload = b"A" * (artifacts_router.MAX_SKILL_ARCHIVE_MEMBER_BYTES + 1)
    with zipfile.ZipFile(skill_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zip_ref:
        zip_ref.writestr("SKILL.md", payload)

    assert skill_path.stat().st_size < artifacts_router.MAX_SKILL_ARCHIVE_MEMBER_BYTES

    with pytest.raises(HTTPException) as exc_info:
        artifacts_router._extract_file_from_skill_archive(skill_path, "SKILL.md")

    assert exc_info.value.status_code == 413
