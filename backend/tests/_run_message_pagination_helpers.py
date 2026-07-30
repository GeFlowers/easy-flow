'定义 _run_message_pagination_helpers 模块提供的职责与可复用接口'
from fastapi.testclient import TestClient


def assert_run_message_page(
    client: TestClient,
    url: str,
    *,
    expected_seq: list[int],
    has_more: bool = True,
) -> None:
    '执行 assert_run_message_page 的明确职责，并返回与调用约定一致的结果'
    response = client.get(url)

    assert response.status_code == 200
    body = response.json()
    assert body["has_more"] is has_more
    assert [m["seq"] for m in body["data"]] == expected_seq
