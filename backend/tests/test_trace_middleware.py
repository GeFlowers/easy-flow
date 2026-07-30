'未说明'
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.responses import Response, StreamingResponse
from starlette.testclient import TestClient

from app.gateway.trace_middleware import TraceMiddleware, resolve_trace_enabled
from deerflow.trace_context import TRACE_ID_HEADER, get_current_trace_id


def _make_app(*, enabled: bool) -> FastAPI:
    '未说明'
    app = FastAPI()
    app.add_middleware(TraceMiddleware, enabled=enabled)

    @app.get("/plain")
    async def plain() -> dict[str, str | None]:
        '未说明'
        return {"trace_id": get_current_trace_id()}

    @app.get("/stream")
    async def stream() -> StreamingResponse:
        """处理流相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        async def body():
            '未说明'
            yield f"trace={get_current_trace_id()}".encode()

        return StreamingResponse(body(), media_type="text/plain")

    @app.get("/pre-set")
    async def pre_set() -> Response:
        '未说明'
        return Response("ok", headers={TRACE_ID_HEADER: "downstream"})

    return app


def test_trace_header_absent_when_disabled() -> None:
    '未说明'
    client = TestClient(_make_app(enabled=False))

    response = client.get("/plain")

    assert TRACE_ID_HEADER not in response.headers
    assert response.json() == {"trace_id": None}


def test_trace_header_inherits_inbound_value_and_binds_context() -> None:
    '未说明'
    client = TestClient(_make_app(enabled=True))

    response = client.get("/plain", headers={TRACE_ID_HEADER: "trace-from-upstream"})

    assert response.headers[TRACE_ID_HEADER] == "trace-from-upstream"
    assert response.json() == {"trace_id": "trace-from-upstream"}


def test_trace_header_generated_when_missing() -> None:
    '未说明'
    client = TestClient(_make_app(enabled=True))

    response = client.get("/plain")

    trace_id = response.headers[TRACE_ID_HEADER]
    assert trace_id
    assert response.json() == {"trace_id": trace_id}


def test_trace_header_added_to_streaming_response_without_consuming_body() -> None:
    '未说明'
    client = TestClient(_make_app(enabled=True))

    response = client.get("/stream", headers={TRACE_ID_HEADER: "stream-trace"})

    assert response.headers[TRACE_ID_HEADER] == "stream-trace"
    assert response.text == "trace=stream-trace"


def test_trace_header_overwrites_duplicate_downstream_value() -> None:
    '未说明'
    client = TestClient(_make_app(enabled=True))

    response = client.get("/pre-set", headers={TRACE_ID_HEADER: "canonical-trace"})

    assert response.headers[TRACE_ID_HEADER] == "canonical-trace"
    assert response.headers.get_list(TRACE_ID_HEADER) == ["canonical-trace"]


def test_trace_header_rejects_crafted_non_ascii_and_generates_fresh_id() -> None:
    '未说明'
    client = TestClient(_make_app(enabled=True))

    # Raw UTF-8 bytes of "café-1"; Starlette latin-1-decodes them into
    # a string containing 0xC3, 0xA9 — both > 0x7E.
    crafted_bytes = b"caf\xc3\xa9-1"
    crafted_decoded = crafted_bytes.decode("latin-1")
    response = client.get("/plain", headers={TRACE_ID_HEADER: crafted_bytes})

    assert response.status_code == 200
    returned = response.headers[TRACE_ID_HEADER]
    assert returned != crafted_decoded
    assert all(0x20 <= ord(ch) <= 0x7E for ch in returned), returned
    assert response.json() == {"trace_id": returned}


def test_trace_header_rejects_crafted_c1_control_and_generates_fresh_id() -> None:
    '未说明'
    client = TestClient(_make_app(enabled=True))

    crafted_bytes = b"trace\x9fid"
    crafted_decoded = crafted_bytes.decode("latin-1")
    response = client.get("/plain", headers={TRACE_ID_HEADER: crafted_bytes})

    assert response.status_code == 200
    returned = response.headers[TRACE_ID_HEADER]
    assert returned != crafted_decoded
    assert all(0x20 <= ord(ch) <= 0x7E for ch in returned), returned


def test_enabled_is_a_startup_snapshot_not_a_live_read() -> None:
    '未说明'
    source = {"enabled": True}
    app = FastAPI()
    app.add_middleware(TraceMiddleware, enabled=source["enabled"])

    @app.get("/plain")
    async def plain() -> dict[str, str | None]:
        '未说明'
        return {"trace_id": get_current_trace_id()}

    client = TestClient(app)

    source["enabled"] = False  # would matter if the middleware read live
    response = client.get("/plain")

    assert TRACE_ID_HEADER in response.headers
    assert response.json()["trace_id"] is not None


def test_resolve_trace_enabled_walks_nested_config() -> None:
    '未说明'
    config = SimpleNamespace(logging=SimpleNamespace(enhance=SimpleNamespace(enabled=True)))
    assert resolve_trace_enabled(config) is True

    config_off = SimpleNamespace(logging=SimpleNamespace(enhance=SimpleNamespace(enabled=False)))
    assert resolve_trace_enabled(config_off) is False


def test_resolve_trace_enabled_defaults_to_false_when_fields_missing() -> None:
    '未说明'
    assert resolve_trace_enabled(SimpleNamespace()) is False
    assert resolve_trace_enabled(SimpleNamespace(logging=None)) is False
    assert resolve_trace_enabled(SimpleNamespace(logging=SimpleNamespace(enhance=None))) is False


def test_gateway_app_construction_trace_flag_defaults_false_when_config_missing(monkeypatch) -> None:
    '未说明'
    import app.gateway.app as gateway_app

    def missing_config():
        """处理配置相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        raise FileNotFoundError("no config")

    monkeypatch.setattr(gateway_app, "get_app_config", missing_config)

    assert gateway_app._resolve_trace_enabled_for_app_construction() is False


def test_gateway_app_construction_trace_flag_uses_config_snapshot(monkeypatch) -> None:
    '未说明'
    import app.gateway.app as gateway_app

    config = SimpleNamespace(logging=SimpleNamespace(enhance=SimpleNamespace(enabled=True)))
    monkeypatch.setattr(gateway_app, "get_app_config", lambda: config)

    assert gateway_app._resolve_trace_enabled_for_app_construction() is True
