"""验证播客生成技能的提供商选择、语音合成、重试和并发策略。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_loader import FakeResp, load  # noqa: E402

pod = load("podcast-generation")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """清理播客生成环境变量并禁用重试退避的真实等待。"""
    for k in ["VOLCENGINE_TTS_APPID", "VOLCENGINE_TTS_ACCESS_TOKEN", "VOLCENGINE_TTS_CLUSTER",
              "MINIMAX_API_KEY", "PODCAST_GENERATION_PROVIDER", "MINIMAX_API_HOST",
              "MINIMAX_TTS_MODEL", "MINIMAX_TTS_VOICE_MALE", "MINIMAX_TTS_VOICE_FEMALE",
              "MINIMAX_TTS_MAX_RETRIES"]:
        monkeypatch.delenv(k, raising=False)
    # 测试重试退避时不执行真实等待。
    monkeypatch.setattr(pod.time, "sleep", lambda *_: None)


def test_resolve_prefers_volcengine(monkeypatch):
    """验证火山引擎凭证完整时优先选择火山引擎。"""
    monkeypatch.setenv("VOLCENGINE_TTS_APPID", "a")
    monkeypatch.setenv("VOLCENGINE_TTS_ACCESS_TOKEN", "t")
    assert pod._resolve_tts_provider() == "volcengine"


def test_resolve_falls_back_to_minimax(monkeypatch):
    """验证仅配置 MiniMax 密钥时回退到 MiniMax。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    assert pod._resolve_tts_provider() == "minimax"


def test_resolve_override(monkeypatch):
    """验证显式提供商配置覆盖自动选择结果。"""
    monkeypatch.setenv("VOLCENGINE_TTS_APPID", "a")
    monkeypatch.setenv("VOLCENGINE_TTS_ACCESS_TOKEN", "t")
    monkeypatch.setenv("PODCAST_GENERATION_PROVIDER", "minimax")
    assert pod._resolve_tts_provider() == "minimax"


def test_resolve_unknown_raises(monkeypatch):
    """验证配置未知语音提供商时抛出错误。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    monkeypatch.setenv("PODCAST_GENERATION_PROVIDER", "openai")
    with pytest.raises(ValueError):
        pod._resolve_tts_provider()


def test_minimax_tts_decodes_hex(monkeypatch):
    """验证 MiniMax 语音响应的十六进制音频解码和请求参数。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    captured = {}

    def fake_post(url, headers=None, json=None, **kw):
        """记录语音请求并返回十六进制编码的模拟音频。"""
        captured["url"] = url
        captured["json"] = json
        return FakeResp({"data": {"audio": b"audiobytes".hex(), "status": 2},
                         "base_resp": {"status_code": 0}})

    monkeypatch.setattr(pod.requests, "post", fake_post)
    out = pod.text_to_speech_minimax("hello", "male-qn-qingse")
    assert out == b"audiobytes"
    assert captured["url"].endswith("/v1/t2a_v2")
    assert captured["json"]["voice_setting"]["voice_id"] == "male-qn-qingse"
    assert captured["json"]["output_format"] == "hex"


def test_process_line_minimax_voice_mapping(monkeypatch):
    """验证女性角色映射到默认 MiniMax 女声音色。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    seen = {}

    def fake_tts(text, voice_id):
        """记录所选音色并返回模拟音频片段。"""
        seen["voice_id"] = voice_id
        return b"x"

    monkeypatch.setattr(pod, "text_to_speech_minimax", fake_tts)
    line = pod.ScriptLine(speaker="female", paragraph="hi")
    idx, audio = pod._process_line((0, line, 1, "minimax"))
    assert audio == b"x"
    assert seen["voice_id"] == "female-tianmei"


def test_generate_podcast_minimax_end_to_end(monkeypatch, tmp_path):
    """验证 MiniMax 多角色播客生成和音频片段拼接流程。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")

    def fake_post(url, headers=None, json=None, **kw):
        """为每行台词返回可拼接的模拟音频片段。"""
        return FakeResp({"data": {"audio": b"chunk".hex(), "status": 2},
                         "base_resp": {"status_code": 0}})

    monkeypatch.setattr(pod.requests, "post", fake_post)
    script = tmp_path / "s.json"
    script.write_text(
        '{"title":"T","locale":"en","lines":[{"speaker":"male","paragraph":"a"},'
        '{"speaker":"female","paragraph":"b"}]}',
        encoding="utf-8",
    )
    out = tmp_path / "o.mp3"
    msg = pod.generate_podcast(str(script), str(out), None)
    assert out.read_bytes() == b"chunkchunk"
    assert "Successfully generated podcast" in msg


def test_volcengine_tts_decodes_base64(monkeypatch):
    """验证火山引擎语音响应的 Base64 音频解码。"""
    import base64
    monkeypatch.setenv("VOLCENGINE_TTS_APPID", "a")
    monkeypatch.setenv("VOLCENGINE_TTS_ACCESS_TOKEN", "t")

    def fake_post(url, headers=None, json=None, **kw):
        """返回 Base64 编码的火山引擎模拟音频。"""
        return FakeResp({"code": 3000, "data": base64.b64encode(b"volcbytes").decode()})

    monkeypatch.setattr(pod.requests, "post", fake_post)
    out = pod.text_to_speech_volcengine("hi", "zh_male_yangguangqingnian_moon_bigtts")
    assert out == b"volcbytes"


def test_volcengine_without_creds_raises(monkeypatch):
    """验证选择火山引擎但缺少凭证时抛出配置错误。"""
    monkeypatch.setenv("PODCAST_GENERATION_PROVIDER", "volcengine")
    script = pod.Script(lines=[pod.ScriptLine("male", "a")])
    with pytest.raises(ValueError):
        pod.tts_node(script)


def test_process_line_minimax_male_and_override(monkeypatch):
    """验证男性默认音色及环境变量覆盖音色。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    seen = []

    def fake_tts(text, voice_id):
        """记录每次台词处理所使用的音色。"""
        seen.append(voice_id)
        return b"x"

    monkeypatch.setattr(pod, "text_to_speech_minimax", fake_tts)
    male = pod.ScriptLine(speaker="male", paragraph="hi")
    pod._process_line((0, male, 1, "minimax"))
    assert seen[-1] == "male-qn-qingse"
    monkeypatch.setenv("MINIMAX_TTS_VOICE_MALE", "custom-male")
    pod._process_line((0, male, 1, "minimax"))
    assert seen[-1] == "custom-male"


def _seq_post(responses):
    """创建按顺序返回预设响应并统计调用次数的 POST 替身。"""
    calls = {"n": 0}

    def fake_post(*a, **k):
        """返回当前顺序响应，耗尽后重复最后一个响应。"""
        resp = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        return resp

    return fake_post, calls


def test_minimax_retries_on_rate_limit_code(monkeypatch):
    """验证 MiniMax 业务限流错误触发重试并最终成功。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    fake_post, calls = _seq_post([
        FakeResp({"base_resp": {"status_code": 1002, "status_msg": "rate limit"}}),
        FakeResp({"base_resp": {"status_code": 1039, "status_msg": "tpm limit"}}),
        FakeResp({"data": {"audio": b"ok".hex()}, "base_resp": {"status_code": 0}}),
    ])
    monkeypatch.setattr(pod.requests, "post", fake_post)
    out = pod.text_to_speech_minimax("hi", "male-qn-qingse", max_retries=3)
    assert out == b"ok"
    assert calls["n"] == 3  # 两次重试后成功。


def test_minimax_retries_on_http_429(monkeypatch):
    """验证 HTTP 429 响应触发重试。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    fake_post, calls = _seq_post([
        FakeResp({}, status_code=429),
        FakeResp({"data": {"audio": b"ok".hex()}, "base_resp": {"status_code": 0}}),
    ])
    monkeypatch.setattr(pod.requests, "post", fake_post)
    out = pod.text_to_speech_minimax("hi", "male-qn-qingse", max_retries=3)
    assert out == b"ok"
    assert calls["n"] == 2


def test_minimax_no_retry_on_auth_error(monkeypatch):
    """验证永久鉴权错误不会触发重试。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    fake_post, calls = _seq_post([
        FakeResp({"base_resp": {"status_code": 1004, "status_msg": "auth failed"}}),
        FakeResp({"data": {"audio": b"never".hex()}, "base_resp": {"status_code": 0}}),
    ])
    monkeypatch.setattr(pod.requests, "post", fake_post)
    out = pod.text_to_speech_minimax("hi", "male-qn-qingse", max_retries=3)
    assert out is None
    assert calls["n"] == 1  # 永久错误不重试。


def test_minimax_gives_up_after_max_retries(monkeypatch):
    """验证连续限流时达到最大重试次数后放弃。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    fake_post, calls = _seq_post([
        FakeResp({"base_resp": {"status_code": 1002, "status_msg": "rate limit"}}),
    ])
    monkeypatch.setattr(pod.requests, "post", fake_post)
    out = pod.text_to_speech_minimax("hi", "male-qn-qingse", max_retries=2)
    assert out is None
    assert calls["n"] == 3  # 首次请求加两次重试。


def test_tts_node_raises_on_partial_failure(monkeypatch):
    """验证部分台词合成失败时报告失败行号。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    calls = {"n": 0}

    def fake_tts(text, voice_id, **kw):
        """首个片段成功、后续片段失败，以模拟部分失败。"""
        calls["n"] += 1
        return b"x" if calls["n"] == 1 else None

    monkeypatch.setattr(pod, "text_to_speech_minimax", fake_tts)
    script = pod.Script(lines=[pod.ScriptLine("male", "a"), pod.ScriptLine("female", "b")])
    with pytest.raises(ValueError) as e:
        pod.tts_node(script)
    assert "2" in str(e.value)  # 错误信息应包含失败的第 2 行。


def test_tts_node_defaults_to_one_worker_for_minimax(monkeypatch):
    """验证 MiniMax 默认仅使用一个语音合成工作线程。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    captured = {}
    real_executor = pod.ThreadPoolExecutor

    class CapturingExecutor(real_executor):
        """记录线程池工作线程数量的执行器替身。"""
        def __init__(self, *args, **kwargs):
            """保存 max_workers 后继续初始化真实线程池。"""
            captured["max_workers"] = kwargs.get("max_workers", args[0] if args else None)
            super().__init__(*args, **kwargs)

    def fake_tts(text, voice_id):
        """返回用于并发策略测试的模拟音频。"""
        return b"x"

    monkeypatch.setattr(pod, "ThreadPoolExecutor", CapturingExecutor)
    monkeypatch.setattr(pod, "text_to_speech_minimax", fake_tts)
    script = pod.Script(lines=[pod.ScriptLine("male", "a"), pod.ScriptLine("female", "b")])

    assert pod.tts_node(script) == [b"x", b"x"]
    assert captured["max_workers"] == 1


def test_tts_node_keeps_four_worker_default_for_volcengine(monkeypatch):
    """验证火山引擎保留四个语音合成工作线程的默认值。"""
    monkeypatch.setenv("VOLCENGINE_TTS_APPID", "a")
    monkeypatch.setenv("VOLCENGINE_TTS_ACCESS_TOKEN", "t")
    captured = {}
    real_executor = pod.ThreadPoolExecutor

    class CapturingExecutor(real_executor):
        """记录线程池工作线程数量的执行器替身。"""
        def __init__(self, *args, **kwargs):
            """保存 max_workers 后继续初始化真实线程池。"""
            captured["max_workers"] = kwargs.get("max_workers", args[0] if args else None)
            super().__init__(*args, **kwargs)

    def fake_tts(text, voice_type):
        """返回用于并发策略测试的模拟音频。"""
        return b"x"

    monkeypatch.setattr(pod, "ThreadPoolExecutor", CapturingExecutor)
    monkeypatch.setattr(pod, "text_to_speech_volcengine", fake_tts)
    script = pod.Script(lines=[pod.ScriptLine("male", "a"), pod.ScriptLine("female", "b")])

    assert pod.tts_node(script) == [b"x", b"x"]
    assert captured["max_workers"] == 4
