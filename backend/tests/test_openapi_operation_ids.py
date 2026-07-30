"""验证 OpenAPI 文档中操作标识的唯一性及流式运行路由的双方法声明。"""

from __future__ import annotations

import warnings

import pytest


@pytest.fixture(scope="module")
def openapi_spec() -> dict:
    """生成模块级 OpenAPI 快照；每次夹具初始化前清除应用缓存。"""
    from app.gateway.app import app

    # ``app.openapi()`` 会在 FastAPI 实例上缓存结果；重置缓存可强制重新生成并触发重复标识警告。
    app.openapi_schema = None
    return app.openapi()


def test_openapi_spec_has_no_duplicate_operation_warnings() -> None:
    """验证重新生成 OpenAPI 文档时不会发出重复 operationId 警告。"""
    from app.gateway.app import app

    app.openapi_schema = None
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        app.openapi()

    dup_messages = [str(item.message) for item in caught if "Duplicate Operation ID" in str(item.message)]
    assert dup_messages == [], f"OpenAPI generation emitted duplicate operation id warnings: {dup_messages}"


def test_openapi_operation_ids_are_unique(openapi_spec: dict) -> None:
    """验证 OpenAPI 中每个 operationId 至多对应一个路径和 HTTP 方法。"""
    op_id_to_locations: dict[str, list[tuple[str, str]]] = {}

    for path, path_item in openapi_spec.get("paths", {}).items():
        for method, operation in path_item.items():
            if not isinstance(operation, dict):
                continue
            op_id = operation.get("operationId")
            if op_id is None:
                continue
            op_id_to_locations.setdefault(op_id, []).append((path, method))

    duplicates = {op_id: locations for op_id, locations in op_id_to_locations.items() if len(locations) > 1}
    assert not duplicates, f"Duplicate operationIds in OpenAPI spec: {duplicates}"


def test_stream_existing_run_exposes_distinct_get_and_post(openapi_spec: dict) -> None:
    """验证既有运行的流式端点同时声明 GET、POST 且二者的 operationId 不同。"""
    path = "/api/threads/{thread_id}/runs/{run_id}/stream"
    path_item = openapi_spec["paths"].get(path)
    assert path_item is not None, f"Expected {path} to be present in the OpenAPI spec"

    assert "get" in path_item, f"Expected GET handler on {path}"
    assert "post" in path_item, f"Expected POST handler on {path}"

    get_op_id = path_item["get"].get("operationId")
    post_op_id = path_item["post"].get("operationId")
    assert get_op_id and post_op_id, "Both GET and POST must have operationIds"
    assert get_op_id != post_op_id, f"GET and POST share operationId {get_op_id!r}, which breaks OpenAPI codegen"
