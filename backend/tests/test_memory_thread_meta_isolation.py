"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langgraph.store.memory import InMemoryStore

from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
from deerflow.runtime.user_context import reset_current_user, set_current_user

USER_A = SimpleNamespace(id="user-a", email="a@test.local")
USER_B = SimpleNamespace(id="user-b", email="b@test.local")


def _as_user(user):
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    class _Ctx:
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __enter__(self):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            self._token = set_current_user(user)
            return user

        def __exit__(self, *exc):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            reset_current_user(self._token)

    return _Ctx()


@pytest.fixture
def store():
    """提供隔离的测试夹具：创建调用用例所需依赖，并保持既定资源回收边界。"""
    return MemoryThreadMetaStore(InMemoryStore())


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_search_isolation(store):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    with _as_user(USER_A):
        await store.create("t-alpha", display_name="A's thread")
    with _as_user(USER_B):
        await store.create("t-beta", display_name="B's thread")

    with _as_user(USER_A):
        results = await store.search()
        assert [r["thread_id"] for r in results] == ["t-alpha"]

    with _as_user(USER_B):
        results = await store.search()
        assert [r["thread_id"] for r in results] == ["t-beta"]


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_get_isolation(store):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    with _as_user(USER_A):
        await store.create("t-alpha", display_name="A's thread")

    with _as_user(USER_B):
        assert await store.get("t-alpha") is None

    with _as_user(USER_A):
        result = await store.get("t-alpha")
        assert result is not None
        assert result["display_name"] == "A's thread"


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_update_display_name_denied(store):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    with _as_user(USER_A):
        await store.create("t-alpha", display_name="original")

    with _as_user(USER_B):
        await store.update_display_name("t-alpha", "hacked")

    with _as_user(USER_A):
        row = await store.get("t-alpha")
        assert row is not None
        assert row["display_name"] == "original"


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_update_status_denied(store):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    with _as_user(USER_A):
        await store.create("t-alpha")

    with _as_user(USER_B):
        await store.update_status("t-alpha", "error")

    with _as_user(USER_A):
        row = await store.get("t-alpha")
        assert row is not None
        assert row["status"] == "idle"


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_update_metadata_denied(store):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    with _as_user(USER_A):
        await store.create("t-alpha", metadata={"key": "original"})

    with _as_user(USER_B):
        await store.update_metadata("t-alpha", {"key": "hacked"})

    with _as_user(USER_A):
        row = await store.get("t-alpha")
        assert row is not None
        assert row["metadata"]["key"] == "original"


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_delete_denied(store):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    with _as_user(USER_A):
        await store.create("t-alpha")

    with _as_user(USER_B):
        await store.delete("t-alpha")

    with _as_user(USER_A):
        row = await store.get("t-alpha")
        assert row is not None


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_no_context_raises(store):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    with pytest.raises(RuntimeError, match="no user context is set"):
        await store.search()


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_explicit_none_bypasses_filter(store):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    with _as_user(USER_A):
        await store.create("t-alpha")
    with _as_user(USER_B):
        await store.create("t-beta")

    all_rows = await store.search(user_id=None)
    assert {r["thread_id"] for r in all_rows} == {"t-alpha", "t-beta"}

    row = await store.get("t-alpha", user_id=None)
    assert row is not None
