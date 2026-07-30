'未说明'

import json


def _format_sse(event: str, data, *, event_id: str | None = None) -> str:
    '未说明'
    from app.gateway.services import format_sse

    return format_sse(event, data, event_id=event_id)


def test_sse_end_event_data_null():
    '未说明'
    frame = _format_sse("end", None)
    assert "data: null" in frame


def test_sse_metadata_event():
    '未说明'
    frame = _format_sse("metadata", {"run_id": "abc", "attempt": 1}, event_id="123-0")
    assert "event: metadata" in frame
    assert "id: 123-0" in frame


def test_sse_error_format():
    '未说明'
    frame = _format_sse("error", {"message": "boom", "name": "ValueError"})
    parsed = json.loads(frame.split("data: ")[1].split("\n")[0])
    assert parsed["message"] == "boom"
    assert parsed["name"] == "ValueError"
