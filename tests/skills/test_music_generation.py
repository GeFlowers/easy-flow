"""验证音乐生成技能的请求构造、响应处理和输入校验。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_loader import FakeResp, load  # noqa: E402

mus = load("music-generation")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """清理 MiniMax 音乐生成相关环境变量，隔离每个测试。"""
    for k in ["MINIMAX_API_KEY", "MINIMAX_API_HOST", "MINIMAX_MUSIC_MODEL"]:
        monkeypatch.delenv(k, raising=False)


def _post_ok(captured):
    """创建记录请求参数并返回成功音频响应的 POST 替身。"""
    def fake_post(url, headers=None, json=None, **kw):
        """记录请求内容并返回十六进制编码的模拟音频。"""
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return FakeResp({"data": {"audio": b"songbytes".hex(), "status": 2},
                         "base_resp": {"status_code": 0}})
    return fake_post


def test_with_lyrics_payload_and_writes(monkeypatch, tmp_path):
    """验证含歌词请求的参数构造、音频写入和成功消息。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    captured = {}
    monkeypatch.setattr(mus.requests, "post", _post_ok(captured))
    spec = tmp_path / "s.json"
    spec.write_text('{"title":"X","prompt":"pop, happy","lyrics":"[verse]\\nla la"}',
                    encoding="utf-8")
    out = tmp_path / "o.mp3"
    msg = mus.generate_music(str(spec), str(out))
    assert out.read_bytes() == b"songbytes"
    assert captured["url"].endswith("/v1/music_generation")
    assert captured["headers"]["Authorization"] == "Bearer m"
    assert captured["json"]["model"] == "music-2.6-free"
    assert captured["json"]["lyrics"] == "[verse]\nla la"
    assert captured["json"]["output_format"] == "hex"
    assert "Successfully generated music" in msg


def test_instrumental_sets_flag(monkeypatch, tmp_path):
    """验证纯音乐模式仅发送伴奏标记而不发送歌词参数。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    captured = {}
    monkeypatch.setattr(mus.requests, "post", _post_ok(captured))
    spec = tmp_path / "s.json"
    spec.write_text('{"prompt":"lofi beats","is_instrumental":true}', encoding="utf-8")
    mus.generate_music(str(spec), str(tmp_path / "o.mp3"))
    assert captured["json"]["is_instrumental"] is True
    assert "lyrics" not in captured["json"]
    assert "lyrics_optimizer" not in captured["json"]


def test_no_lyrics_uses_optimizer(monkeypatch, tmp_path):
    """验证缺少歌词时启用歌词优化器。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    captured = {}
    monkeypatch.setattr(mus.requests, "post", _post_ok(captured))
    spec = tmp_path / "s.json"
    spec.write_text('{"prompt":"sad ballad"}', encoding="utf-8")
    mus.generate_music(str(spec), str(tmp_path / "o.mp3"))
    assert captured["json"]["lyrics_optimizer"] is True
    assert "lyrics" not in captured["json"]


def test_model_override(monkeypatch, tmp_path):
    """验证环境变量可以覆盖默认音乐模型。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    monkeypatch.setenv("MINIMAX_MUSIC_MODEL", "music-2.6")
    captured = {}
    monkeypatch.setattr(mus.requests, "post", _post_ok(captured))
    spec = tmp_path / "s.json"
    spec.write_text('{"prompt":"jazz","lyrics":"[verse]\\nhi"}', encoding="utf-8")
    mus.generate_music(str(spec), str(tmp_path / "o.mp3"))
    assert captured["json"]["model"] == "music-2.6"


def test_raises_on_base_resp_error(monkeypatch, tmp_path):
    """验证 MiniMax 业务错误码会转换为包含错误码的异常。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")

    def fake_post(url, headers=None, json=None, **kw):
        """返回余额不足的模拟业务错误。"""
        return FakeResp({"base_resp": {"status_code": 1008, "status_msg": "no balance"}})

    monkeypatch.setattr(mus.requests, "post", fake_post)
    spec = tmp_path / "s.json"
    spec.write_text('{"prompt":"x","lyrics":"[verse]\\ny"}', encoding="utf-8")
    with pytest.raises(Exception) as e:
        mus.generate_music(str(spec), str(tmp_path / "o.mp3"))
    assert "1008" in str(e.value)


def test_missing_api_key_returns_message(monkeypatch, tmp_path):
    """验证缺少 API 密钥时返回配置提示。"""
    spec = tmp_path / "s.json"
    spec.write_text('{"prompt":"x"}', encoding="utf-8")
    msg = mus.generate_music(str(spec), str(tmp_path / "o.mp3"))
    assert "MINIMAX_API_KEY" in msg


def test_raises_on_missing_audio_data(monkeypatch, tmp_path):
    """验证成功响应缺少音频数据时抛出异常。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")

    def fake_post(url, headers=None, json=None, **kw):
        """返回不包含 data 字段的模拟成功响应。"""
        return FakeResp({"base_resp": {"status_code": 0}})

    monkeypatch.setattr(mus.requests, "post", fake_post)
    spec = tmp_path / "s.json"
    spec.write_text('{"prompt":"x"}', encoding="utf-8")
    with pytest.raises(Exception, match="no audio data"):
        mus.generate_music(str(spec), str(tmp_path / "o.mp3"))


def test_empty_prompt_raises(monkeypatch, tmp_path):
    """验证提示词为空时在调用 API 前抛出参数错误。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")

    def fake_post(url, headers=None, json=None, **kw):  # pragma: no cover
        """在不应调用 API 的场景中主动使测试失败。"""
        raise AssertionError("must not call the API when prompt is missing")

    monkeypatch.setattr(mus.requests, "post", fake_post)
    spec = tmp_path / "s.json"
    spec.write_text('{"title":"X","lyrics":"[verse]\\nhi"}', encoding="utf-8")  # 刻意省略提示词。
    with pytest.raises(ValueError, match="prompt"):
        mus.generate_music(str(spec), str(tmp_path / "o.mp3"))


def test_empty_lyrics_falls_back_to_optimizer(monkeypatch, tmp_path):
    """验证空歌词按未提供歌词处理并启用优化器。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    captured = {}
    monkeypatch.setattr(mus.requests, "post", _post_ok(captured))
    spec = tmp_path / "s.json"
    spec.write_text('{"prompt":"x","lyrics":""}', encoding="utf-8")
    mus.generate_music(str(spec), str(tmp_path / "o.mp3"))
    assert captured["json"]["lyrics_optimizer"] is True
    assert "lyrics" not in captured["json"]
