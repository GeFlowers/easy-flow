"""验证视频生成技能的提供商选择、任务轮询和文件下载。"""
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_loader import FakeResp, load  # noqa: E402

vid = load("video-generation")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """清理视频生成环境变量并禁用测试中的真实等待。"""
    for k in ["GEMINI_API_KEY", "MINIMAX_API_KEY", "VIDEO_GENERATION_PROVIDER",
              "MINIMAX_API_HOST", "MINIMAX_VIDEO_MODEL"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(vid.time, "sleep", lambda *_: None)


def test_resolve_prefers_gemini():
    """验证 Gemini 可用时选择默认提供商。"""
    assert vid._resolve_provider("VIDEO_GENERATION_PROVIDER", "gemini", True) == "gemini"


def test_resolve_falls_back_to_minimax(monkeypatch):
    """验证 Gemini 不可用时回退到 MiniMax。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    assert vid._resolve_provider("VIDEO_GENERATION_PROVIDER", "gemini", False) == "minimax"


def test_resolve_override(monkeypatch):
    """验证显式提供商配置覆盖自动选择结果。"""
    monkeypatch.setenv("VIDEO_GENERATION_PROVIDER", "minimax")
    assert vid._resolve_provider("VIDEO_GENERATION_PROVIDER", "gemini", True) == "minimax"


def test_unknown_provider_raises(monkeypatch, tmp_path):
    """验证配置不受支持的提供商时抛出错误。"""
    monkeypatch.setenv("VIDEO_GENERATION_PROVIDER", "openai")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    pf = tmp_path / "p.json"
    pf.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        vid.generate_video(str(pf), [], str(tmp_path / "v.mp4"), "16:9")


def test_minimax_full_flow(monkeypatch, tmp_path):
    """验证 MiniMax 视频创建、轮询、地址查询和下载完整流程。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    posts = {}

    def fake_post(url, headers=None, json=None, **kw):
        """记录创建任务请求并返回模拟任务编号。"""
        posts["url"] = url
        posts["json"] = json
        return FakeResp({"task_id": "T1", "base_resp": {"status_code": 0}})

    def fake_get(url, headers=None, params=None, **kw):
        """按请求阶段返回任务状态、下载地址或视频内容。"""
        if url.endswith("/v1/query/video_generation"):
            assert params["task_id"] == "T1"
            return FakeResp({"status": "Success", "file_id": "F1",
                             "base_resp": {"status_code": 0}})
        if url.endswith("/v1/files/retrieve"):
            assert params["file_id"] == "F1"
            return FakeResp({"file": {"download_url": "https://dl/v.mp4"},
                             "base_resp": {"status_code": 0}})
        return FakeResp(content=b"MP4DATA")  # 模拟最终视频下载内容。

    monkeypatch.setattr(vid.requests, "post", fake_post)
    monkeypatch.setattr(vid.requests, "get", fake_get)

    out = tmp_path / "v.mp4"
    pf = tmp_path / "p.json"
    pf.write_text("a cat runs", encoding="utf-8")
    msg = vid.generate_video(str(pf), [], str(out), "16:9")

    assert out.read_bytes() == b"MP4DATA"
    assert posts["url"].endswith("/v1/video_generation")
    assert posts["json"]["model"] == "MiniMax-Hailuo-2.3"
    assert "successfully" in msg.lower()


def test_minimax_reference_first_frame(monkeypatch, tmp_path):
    """验证参考图像作为首帧 Data URL 发送给 MiniMax。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    posts = {}

    def fake_post(url, headers=None, json=None, **kw):
        """记录包含首帧图像的视频创建请求。"""
        posts["json"] = json
        return FakeResp({"task_id": "T1", "base_resp": {"status_code": 0}})

    def fake_get(url, headers=None, params=None, **kw):
        """返回成功任务状态、下载地址和模拟视频内容。"""
        if url.endswith("/v1/query/video_generation"):
            return FakeResp({"status": "Success", "file_id": "F1", "base_resp": {"status_code": 0}})
        if url.endswith("/v1/files/retrieve"):
            return FakeResp({"file": {"download_url": "https://dl/v.mp4"}, "base_resp": {"status_code": 0}})
        return FakeResp(content=b"X")

    monkeypatch.setattr(vid.requests, "post", fake_post)
    monkeypatch.setattr(vid.requests, "get", fake_get)
    ref = tmp_path / "f.jpg"
    ref.write_bytes(b"\xff\xd8img")
    pf = tmp_path / "p.json"
    pf.write_text("x", encoding="utf-8")
    vid.generate_video(str(pf), [str(ref)], str(tmp_path / "v.mp4"), "16:9")
    assert posts["json"]["first_frame_image"].startswith("data:image/jpeg;base64,")


def test_minimax_task_fail(monkeypatch, tmp_path):
    """验证 MiniMax 任务失败状态会终止生成并抛出异常。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")

    def fake_post(url, headers=None, json=None, **kw):
        """返回模拟的视频生成任务编号。"""
        return FakeResp({"task_id": "T1", "base_resp": {"status_code": 0}})

    def fake_get(url, headers=None, params=None, **kw):
        """返回内容审核阻止导致的任务失败状态。"""
        return FakeResp({"status": "Fail", "base_resp": {"status_code": 1027, "status_msg": "blocked"}})

    monkeypatch.setattr(vid.requests, "post", fake_post)
    monkeypatch.setattr(vid.requests, "get", fake_get)
    pf = tmp_path / "p.json"
    pf.write_text("x", encoding="utf-8")
    with pytest.raises(Exception):
        vid.generate_video(str(pf), [], str(tmp_path / "v.mp4"), "16:9")


def test_minimax_poll_timeout(monkeypatch):
    """验证任务持续处理中时轮询达到上限后超时。"""
    def fake_get(url, headers=None, params=None, **kw):
        """始终返回处理中状态以触发超时。"""
        return FakeResp({"status": "Processing", "base_resp": {"status_code": 0}})

    monkeypatch.setattr(vid.requests, "get", fake_get)
    with pytest.raises(Exception) as e:
        vid._poll_video_task("https://h", "Bearer m", "T1", max_attempts=3, interval=0)
    assert "timed out" in str(e.value)


def test_minimax_task_fail_keeps_task_context(monkeypatch, tmp_path):
    """验证任务失败异常保留任务编号和任务级错误上下文。"""
    # Fail 状态优先于通用 base_resp 检查，以保留任务编号和任务级失败信息。
    monkeypatch.setenv("MINIMAX_API_KEY", "m")

    def fake_post(url, headers=None, json=None, **kw):
        """返回需要在异常中保留的模拟任务编号。"""
        return FakeResp({"task_id": "T1", "base_resp": {"status_code": 0}})

    def fake_get(url, headers=None, params=None, **kw):
        """返回带任务级错误信息的失败状态。"""
        return FakeResp({"status": "Fail", "base_resp": {"status_code": 1027, "status_msg": "blocked"}})

    monkeypatch.setattr(vid.requests, "post", fake_post)
    monkeypatch.setattr(vid.requests, "get", fake_get)
    pf = tmp_path / "p.json"
    pf.write_text("x", encoding="utf-8")
    with pytest.raises(Exception, match="task T1 failed"):
        vid.generate_video(str(pf), [], str(tmp_path / "v.mp4"), "16:9")


def test_gemini_download_raises_on_http_error(monkeypatch, tmp_path):
    """验证 Gemini 下载遇到 HTTP 错误时不写入输出文件。"""
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    calls = {}

    def fake_get(url, headers=None, **kw):
        """记录超时参数并返回 HTTP 500 响应。"""
        calls["timeout"] = kw.get("timeout")
        return FakeResp(content=b"error page", status_code=500)

    monkeypatch.setattr(vid.requests, "get", fake_get)
    out = tmp_path / "sub" / "v.mp4"
    with pytest.raises(requests.HTTPError):
        vid.download("https://dl/v.mp4", str(out))
    assert calls["timeout"]  # 下载请求必须设置超时时间。
    assert not out.exists()


def test_gemini_download_writes_nested_dir(monkeypatch, tmp_path):
    """验证 Gemini 下载前自动创建多级输出目录。"""
    monkeypatch.setenv("GEMINI_API_KEY", "g")

    def fake_get(url, headers=None, **kw):
        """返回用于验证文件写入的模拟视频内容。"""
        return FakeResp(content=b"VIDEO")

    monkeypatch.setattr(vid.requests, "get", fake_get)
    out = tmp_path / "nested" / "dir" / "v.mp4"
    vid.download("https://dl/v.mp4", str(out))
    assert out.read_bytes() == b"VIDEO"


def test_gemini_post_raises_on_http_error(monkeypatch, tmp_path):
    """验证 Gemini 创建视频请求的 HTTP 错误会向上抛出。"""
    monkeypatch.setenv("GEMINI_API_KEY", "g")

    def fake_post(url, headers=None, json=None, **kw):
        """返回 HTTP 503 以模拟上游服务不可用。"""
        return FakeResp(status_code=503)

    monkeypatch.setattr(vid.requests, "post", fake_post)
    pf = tmp_path / "p.json"
    pf.write_text("a cat", encoding="utf-8")
    with pytest.raises(requests.HTTPError):
        vid.generate_video(str(pf), [], str(tmp_path / "v.mp4"), "16:9")
