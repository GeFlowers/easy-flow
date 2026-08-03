"""验证图像生成技能的提供商选择、请求构造和文件输出。"""
import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_loader import FakeResp, load  # noqa: E402

img = load("image-generation")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """清理图像生成相关环境变量，隔离每个测试。"""
    for k in ["GEMINI_API_KEY", "MINIMAX_API_KEY", "IMAGE_GENERATION_PROVIDER",
              "MINIMAX_API_HOST", "MINIMAX_IMAGE_MODEL"]:
        monkeypatch.delenv(k, raising=False)


def test_resolve_prefers_gemini(monkeypatch):
    """验证 Gemini 可用时优先选择默认提供商。"""
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    assert img._resolve_provider("IMAGE_GENERATION_PROVIDER", "gemini", True) == "gemini"


def test_resolve_falls_back_to_minimax(monkeypatch):
    """验证 Gemini 不可用时回退到 MiniMax。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    assert img._resolve_provider("IMAGE_GENERATION_PROVIDER", "gemini", False) == "minimax"


def test_resolve_override_wins(monkeypatch):
    """验证显式提供商配置优先于自动选择结果。"""
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("IMAGE_GENERATION_PROVIDER", "MiniMax")
    assert img._resolve_provider("IMAGE_GENERATION_PROVIDER", "gemini", True) == "minimax"


def test_resolve_errors_when_none(monkeypatch):
    """验证没有可用提供商时抛出配置错误。"""
    with pytest.raises(ValueError):
        img._resolve_provider("IMAGE_GENERATION_PROVIDER", "gemini", False)


def test_minimax_builds_payload_and_writes(monkeypatch, tmp_path):
    """验证 MiniMax 请求参数、鉴权信息和图像文件写入。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    raw = b"PNGBYTES"
    captured = {}

    def fake_post(url, headers=None, json=None, **kw):
        """记录 MiniMax 请求并返回 Base64 编码的模拟图像。"""
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return FakeResp({"data": {"image_base64": [base64.b64encode(raw).decode()]},
                         "base_resp": {"status_code": 0, "status_msg": "success"}})

    monkeypatch.setattr(img.requests, "post", fake_post)
    out = tmp_path / "o.jpg"
    prompt_file = tmp_path / "p.json"
    prompt_file.write_text("a red apple", encoding="utf-8")
    msg = img.generate_image(str(prompt_file), [], str(out), "16:9")

    assert out.read_bytes() == raw
    assert captured["url"].endswith("/v1/image_generation")
    assert captured["headers"]["Authorization"] == "Bearer m"
    assert captured["json"]["model"] == "image-01"
    assert captured["json"]["response_format"] == "base64"
    assert captured["json"]["aspect_ratio"] == "16:9"
    assert captured["json"]["n"] == 1
    assert captured["json"]["prompt_optimizer"] is True
    assert "Successfully generated image" in msg


def test_minimax_reference_image_as_data_url(monkeypatch, tmp_path):
    """验证参考图像被编码为带 MIME 类型的 Data URL。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    captured = {}

    def fake_post(url, headers=None, json=None, **kw):
        """记录包含参考图像的请求并返回模拟图像。"""
        captured["json"] = json
        return FakeResp({"data": {"image_base64": [base64.b64encode(b"x").decode()]},
                         "base_resp": {"status_code": 0}})

    monkeypatch.setattr(img.requests, "post", fake_post)
    ref = tmp_path / "ref.jpg"
    ref.write_bytes(b"\xff\xd8refbytes")
    prompt_file = tmp_path / "p.json"
    prompt_file.write_text("scene", encoding="utf-8")
    img.generate_image(str(prompt_file), [str(ref)], str(tmp_path / "o.jpg"), "1:1")

    subj = captured["json"]["subject_reference"]
    assert subj[0]["type"] == "character"
    assert subj[0]["image_file"].startswith("data:image/jpeg;base64,")
    import base64 as _b64
    encoded = subj[0]["image_file"].split(",", 1)[1]
    assert _b64.b64decode(encoded) == b"\xff\xd8refbytes"


def test_minimax_raises_on_base_resp_error(monkeypatch, tmp_path):
    """验证 MiniMax 业务错误码会转换为异常。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")

    def fake_post(url, headers=None, json=None, **kw):
        """返回鉴权失败的模拟业务响应。"""
        return FakeResp({"base_resp": {"status_code": 1004, "status_msg": "auth failed"}})

    monkeypatch.setattr(img.requests, "post", fake_post)
    prompt_file = tmp_path / "p.json"
    prompt_file.write_text("x", encoding="utf-8")
    with pytest.raises(Exception) as e:
        img.generate_image(str(prompt_file), [], str(tmp_path / "o.jpg"), "1:1")
    assert "1004" in str(e.value)


def test_minimax_extracts_json_prompt_field(monkeypatch, tmp_path):
    """验证 JSON 提示文件仅提取 prompt 字段发送给 MiniMax。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    captured = {}

    def fake_post(url, headers=None, json=None, **kw):
        """记录解析后的提示词请求并返回模拟图像。"""
        captured["json"] = json
        return FakeResp({"data": {"image_base64": [base64.b64encode(b"x").decode()]},
                         "base_resp": {"status_code": 0}})

    monkeypatch.setattr(img.requests, "post", fake_post)
    prompt_file = tmp_path / "p.json"
    prompt_file.write_text(
        '{"prompt": "a red barn at dawn", "style": "watercolor", '
        '"composition": "rule of thirds", "negative_prompt": "blurry"}',
        encoding="utf-8",
    )
    img.generate_image(str(prompt_file), [], str(tmp_path / "o.jpg"), "16:9")

    # 仅将 JSON 中的 prompt 字段发送给 MiniMax，不携带其他字段或 JSON 语法。
    assert captured["json"]["prompt"] == "a red barn at dawn"
    assert captured["json"]["prompt_optimizer"] is True


def test_minimax_plaintext_prompt_passes_through(monkeypatch, tmp_path):
    """验证纯文本提示词保持原样发送。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    captured = {}

    def fake_post(url, headers=None, json=None, **kw):
        """记录纯文本提示词请求并返回模拟图像。"""
        captured["json"] = json
        return FakeResp({"data": {"image_base64": [base64.b64encode(b"x").decode()]},
                         "base_resp": {"status_code": 0}})

    monkeypatch.setattr(img.requests, "post", fake_post)
    prompt_file = tmp_path / "p.txt"
    prompt_file.write_text("a red apple on a table", encoding="utf-8")
    img.generate_image(str(prompt_file), [], str(tmp_path / "o.jpg"), "1:1")

    assert captured["json"]["prompt"] == "a red apple on a table"


def test_minimax_rejects_overlong_prompt_without_calling_api(monkeypatch, tmp_path):
    """验证超长提示词在调用 API 前被拒绝。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")

    def fake_post(url, headers=None, json=None, **kw):  # pragma: no cover
        """在不应调用 API 的场景中主动使测试失败。"""
        raise AssertionError("must not call the API when the prompt is over the limit")

    monkeypatch.setattr(img.requests, "post", fake_post)
    prompt_file = tmp_path / "p.json"
    prompt_file.write_text('{"prompt": "' + "x" * 1600 + '"}', encoding="utf-8")
    out = tmp_path / "o.jpg"
    msg = img.generate_image(str(prompt_file), [], str(out), "16:9")

    assert "1500" in msg
    assert "character" in msg.lower()
    assert not out.exists()


def test_minimax_creates_nested_output_dir(monkeypatch, tmp_path):
    """验证生成图像前自动创建多级输出目录。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")

    def fake_post(url, headers=None, json=None, **kw):
        """返回用于验证目录创建和文件写入的模拟图像。"""
        return FakeResp({"data": {"image_base64": [base64.b64encode(b"img").decode()]},
                         "base_resp": {"status_code": 0}})

    monkeypatch.setattr(img.requests, "post", fake_post)
    prompt_file = tmp_path / "p.txt"
    prompt_file.write_text("a cat", encoding="utf-8")
    out = tmp_path / "nested" / "dir" / "o.jpg"
    img.generate_image(str(prompt_file), [], str(out), "1:1")

    assert out.read_bytes() == b"img"


def test_unknown_provider_raises(monkeypatch, tmp_path):
    """验证配置不受支持的提供商时抛出错误。"""
    monkeypatch.setenv("IMAGE_GENERATION_PROVIDER", "openai")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    pf = tmp_path / "p.json"
    pf.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        img.generate_image(str(pf), [], str(tmp_path / "o.jpg"), "1:1")


def test_guess_mime_by_extension():
    """验证根据常见扩展名推断 MIME 类型及默认回退值。"""
    assert img._guess_mime("/a/b.png") == "image/png"
    assert img._guess_mime("/a/b.webp") == "image/webp"
    assert img._guess_mime("/a/b.jpg") == "image/jpeg"
    assert img._guess_mime("/a/b.unknown") == "image/jpeg"
