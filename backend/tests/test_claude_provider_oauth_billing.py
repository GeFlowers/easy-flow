'定义 test_claude_provider_oauth_billing 模块提供的职责与可复用接口。\n\nTests for ClaudeChatModel._apply_oauth_billing.'

import asyncio
import json
from unittest import mock

import pytest

from deerflow.models.claude_provider import OAUTH_BILLING_HEADER, ClaudeChatModel


def _make_model() -> ClaudeChatModel:
    '执行 _make_model 的明确职责，并返回与调用约定一致的结果。\n\nReturn a minimal ClaudeChatModel instance in OAuth mode without network calls.'
    import unittest.mock as mock

    with mock.patch.object(ClaudeChatModel, "model_post_init"):
        m = ClaudeChatModel(model="claude-sonnet-4-6", anthropic_api_key="sk-ant-oat-fake-token")  # type: ignore[call-arg]
    m._is_oauth = True
    m._oauth_access_token = "sk-ant-oat-fake-token"
    return m


@pytest.fixture()
def model() -> ClaudeChatModel:
    '执行 model 的明确职责，并返回与调用约定一致的结果'
    return _make_model()


def _billing_block() -> dict:
    '执行 _billing_block 的明确职责，并返回与调用约定一致的结果'
    return {"type": "text", "text": OAUTH_BILLING_HEADER}


# ---------------------------------------------------------------------------
# Billing block injection
# ---------------------------------------------------------------------------


def test_billing_injected_first_when_no_system(model):
    '验证 billing、injected、first、when、no、system 场景下的预期行为、边界条件与结果'
    payload: dict = {}
    model._apply_oauth_billing(payload)
    assert payload["system"][0] == _billing_block()


def test_billing_injected_first_into_list(model):
    '验证 billing、injected、first、into、list 场景下的预期行为、边界条件与结果'
    payload = {"system": [{"type": "text", "text": "You are a helpful assistant."}]}
    model._apply_oauth_billing(payload)
    assert payload["system"][0] == _billing_block()
    assert payload["system"][1]["text"] == "You are a helpful assistant."


def test_billing_injected_first_into_string_system(model):
    '验证 billing、injected、first、into、string、system 场景下的预期行为、边界条件与结果'
    payload = {"system": "You are helpful."}
    model._apply_oauth_billing(payload)
    assert payload["system"][0] == _billing_block()
    assert payload["system"][1]["text"] == "You are helpful."


def test_billing_not_duplicated_on_second_call(model):
    '验证 billing、not、duplicated、on、second、call 场景下的预期行为、边界条件与结果'
    payload = {"system": [{"type": "text", "text": "prompt"}]}
    model._apply_oauth_billing(payload)
    model._apply_oauth_billing(payload)
    billing_count = sum(1 for b in payload["system"] if isinstance(b, dict) and OAUTH_BILLING_HEADER in b.get("text", ""))
    assert billing_count == 1


def test_billing_moved_to_first_if_not_already_first(model):
    '验证 billing、moved、to、first、if、not、already、first 场景下的预期行为、边界条件与结果。\n\nBilling block already present but not first — must be normalized to index 0.'
    payload = {
        "system": [
            {"type": "text", "text": "other block"},
            _billing_block(),
        ]
    }
    model._apply_oauth_billing(payload)
    assert payload["system"][0] == _billing_block()
    assert len([b for b in payload["system"] if OAUTH_BILLING_HEADER in b.get("text", "")]) == 1


def test_billing_string_with_header_collapsed_to_single_block(model):
    '验证 billing、string、with、header、collapsed、to、single、block 场景下的预期行为、边界条件与结果。\n\nIf system is a string that already contains the billing header, collapse to one block.'
    payload = {"system": OAUTH_BILLING_HEADER}
    model._apply_oauth_billing(payload)
    assert payload["system"] == [_billing_block()]


# ---------------------------------------------------------------------------
# metadata.user_id
# ---------------------------------------------------------------------------


def test_metadata_user_id_added_when_missing(model):
    '验证 metadata、user、id、added、when、missing 场景下的预期行为、边界条件与结果'
    payload: dict = {}
    model._apply_oauth_billing(payload)
    assert "metadata" in payload
    user_id = json.loads(payload["metadata"]["user_id"])
    assert "device_id" in user_id
    assert "session_id" in user_id
    assert user_id["account_uuid"] == "deerflow"


def test_metadata_user_id_not_overwritten_if_present(model):
    '验证 metadata、user、id、not、overwritten、if、present 场景下的预期行为、边界条件与结果'
    payload = {"metadata": {"user_id": "existing-value"}}
    model._apply_oauth_billing(payload)
    assert payload["metadata"]["user_id"] == "existing-value"


def test_metadata_non_dict_replaced_with_dict(model):
    '验证 metadata、non、dict、replaced、with、dict 场景下的预期行为、边界条件与结果。\n\nNon-dict metadata (e.g. None or a string) should be replaced, not crash.'
    for bad_value in (None, "string-metadata", 42):
        payload = {"metadata": bad_value}
        model._apply_oauth_billing(payload)
        assert isinstance(payload["metadata"], dict)
        assert "user_id" in payload["metadata"]


def test_sync_create_strips_cache_control_from_oauth_payload(model):
    '验证 sync、create、strips、cache、control、from、oauth、payload 场景下的预期行为、边界条件与结果'
    payload = {
        "system": [{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}],
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}}],
            }
        ],
        "tools": [{"name": "demo", "input_schema": {"type": "object"}, "cache_control": {"type": "ephemeral"}}],
    }

    with mock.patch.object(model._client.messages, "create", return_value=object()) as create:
        model._create(payload)

    sent_payload = create.call_args.kwargs
    assert "cache_control" not in sent_payload["system"][0]
    assert "cache_control" not in sent_payload["messages"][0]["content"][0]
    assert "cache_control" not in sent_payload["tools"][0]


def test_async_create_strips_cache_control_from_oauth_payload(model):
    '验证 async、create、strips、cache、control、from、oauth、payload 场景下的预期行为、边界条件与结果'
    payload = {
        "system": [{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}],
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}}],
            }
        ],
        "tools": [{"name": "demo", "input_schema": {"type": "object"}, "cache_control": {"type": "ephemeral"}}],
    }

    with mock.patch.object(model._async_client.messages, "create", new=mock.AsyncMock(return_value=object())) as create:
        asyncio.run(model._acreate(payload))

    sent_payload = create.call_args.kwargs
    assert "cache_control" not in sent_payload["system"][0]
    assert "cache_control" not in sent_payload["messages"][0]["content"][0]
    assert "cache_control" not in sent_payload["tools"][0]
