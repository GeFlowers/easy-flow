'未说明'

import json

from deerflow.client import StreamEvent
from deerflow.tui import cli


class _FakeClient:
    '未说明'
    def chat(self, message, *, thread_id=None, **kwargs):
        '未说明'
        return f"answer:{message}"

    def stream(self, message, *, thread_id=None, **kwargs):
        """处理流相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        yield StreamEvent(type="messages-tuple", data={"type": "ai", "content": "hi", "id": "m1"})
        yield StreamEvent(type="end", data={"usage": {"total_tokens": 1}})


class _FakeSession:
    '未说明'
    def __init__(self):
        '未说明'
        self.client = _FakeClient()

    def resolve_thread(self, plan):
        """处理会话相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return None


def test_main_print_outputs_chat_answer(monkeypatch, capsys):
    '未说明'
    monkeypatch.setattr(cli, "_make_session", _FakeSession)
    rc = cli.main(["--print", "hello"])
    assert rc == 0
    assert "answer:hello" in capsys.readouterr().out


def test_main_json_emits_ndjson_stream_events(monkeypatch, capsys):
    '未说明'
    monkeypatch.setattr(cli, "_make_session", _FakeSession)
    rc = cli.main(["--json", "hello"])
    assert rc == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    payloads = [json.loads(ln) for ln in lines]
    assert payloads[0]["type"] == "messages-tuple"
    assert payloads[-1]["type"] == "end"


def test_main_headless_help_returns_2_and_prints_usage(monkeypatch, capsys):
    # On a TTY with no message and no piped stdin, --cli has nothing to run.
    '未说明'
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    rc = cli.main(["--cli"])
    assert rc == 2
    assert "deerflow" in capsys.readouterr().err
