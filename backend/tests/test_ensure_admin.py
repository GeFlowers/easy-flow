"""验证网关启动时管理员检查与历史线程迁移的边界行为。"""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-ensure-admin-testing-min-32")

from app.gateway.auth.config import AuthConfig, set_auth_config

_JWT_SECRET = "test-secret-key-ensure-admin-testing-min-32"


@pytest.fixture(autouse=True)
def _setup_auth_config():
    """为每个用例恢复可用的认证令牌配置，避免全局认证配置相互泄漏。"""
    set_auth_config(AuthConfig(jwt_secret=_JWT_SECRET))
    yield
    set_auth_config(AuthConfig(jwt_secret=_JWT_SECRET))


def _make_app_stub(store=None):
    """构造仅含状态存储属性的应用替身，以隔离启动逻辑的存储依赖。"""
    app = SimpleNamespace()
    app.state = SimpleNamespace()
    app.state.store = store
    return app


def _make_provider(admin_count=0):
    """创建可分别记录管理员计数、创建和更新调用的异步认证提供者替身。"""
    p = AsyncMock()
    p.count_users = AsyncMock(return_value=admin_count)
    p.count_admin_users = AsyncMock(return_value=admin_count)
    p.create_user = AsyncMock()
    p.update_user = AsyncMock(side_effect=lambda u: u)
    return p


def _make_session_factory(admin_row=None):
    """构造异步会话工厂，使查询结果稳定返回指定的管理员行或空值。"""
    row_result = MagicMock()
    row_result.scalar_one_or_none.return_value = admin_row

    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = admin_row

    session = AsyncMock()
    session.execute = AsyncMock(return_value=execute_result)

    # 异步上下文管理器替身。
    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=False)

    sf = MagicMock()
    sf.return_value = session_cm
    return sf


# ── 首次启动：没有管理员时应立即返回 ───────────────────────────────────────


def test_first_boot_does_not_create_admin():
    """验证管理员数为零时不会再自动创建管理员账户。"""
    provider = _make_provider(admin_count=0)
    app = _make_app_stub()

    with patch("app.gateway.deps.get_local_provider", return_value=provider):
        from app.gateway.app import _ensure_admin_user

        asyncio.run(_ensure_admin_user(app))

    provider.create_user.assert_not_called()


def test_first_boot_skips_migration():
    """验证没有管理员时，迁移逻辑不会访问线程存储。"""
    provider = _make_provider(admin_count=0)
    store = AsyncMock()
    store.asearch = AsyncMock(return_value=[])
    app = _make_app_stub(store=store)

    with patch("app.gateway.deps.get_local_provider", return_value=provider):
        from app.gateway.app import _ensure_admin_user

        asyncio.run(_ensure_admin_user(app))

    store.asearch.assert_not_called()


# ── 已存在管理员：找到管理员行后执行迁移 ───────────────────────────────────


def test_admin_exists_triggers_migration():
    """验证管理员计数与数据库行均存在时会扫描孤儿线程。"""
    from uuid import uuid4

    admin_row = MagicMock()
    admin_row.id = uuid4()

    provider = _make_provider(admin_count=1)
    sf = _make_session_factory(admin_row=admin_row)
    store = AsyncMock()
    store.asearch = AsyncMock(return_value=[])
    app = _make_app_stub(store=store)

    with patch("app.gateway.deps.get_local_provider", return_value=provider):
        with patch("deerflow.persistence.engine.get_session_factory", return_value=sf):
            from app.gateway.app import _ensure_admin_user

            asyncio.run(_ensure_admin_user(app))

    store.asearch.assert_called_once()


def test_admin_exists_no_admin_row_skips_migration():
    """验证计数存在但查询不到管理员行这一异常边界会安全跳过迁移。"""
    provider = _make_provider(admin_count=2)
    sf = _make_session_factory(admin_row=None)
    store = AsyncMock()
    app = _make_app_stub(store=store)

    with patch("app.gateway.deps.get_local_provider", return_value=provider):
        with patch("deerflow.persistence.engine.get_session_factory", return_value=sf):
            from app.gateway.app import _ensure_admin_user

            asyncio.run(_ensure_admin_user(app))

    store.asearch.assert_not_called()


def test_admin_exists_no_store_skips_migration():
    """验证管理员行存在但应用未挂载存储时不会抛出异常。"""
    from uuid import uuid4

    admin_row = MagicMock()
    admin_row.id = uuid4()

    provider = _make_provider(admin_count=1)
    sf = _make_session_factory(admin_row=admin_row)
    app = _make_app_stub(store=None)

    with patch("app.gateway.deps.get_local_provider", return_value=provider):
        with patch("deerflow.persistence.engine.get_session_factory", return_value=sf):
            from app.gateway.app import _ensure_admin_user

            asyncio.run(_ensure_admin_user(app))

    # 此处只验证调用过程不会崩溃。


def test_admin_exists_session_factory_none_skips_migration():
    """验证会话工厂不可用时会提前返回且不触发存储扫描。"""
    provider = _make_provider(admin_count=1)
    store = AsyncMock()
    app = _make_app_stub(store=store)

    with patch("app.gateway.deps.get_local_provider", return_value=provider):
        with patch("deerflow.persistence.engine.get_session_factory", return_value=None):
            from app.gateway.app import _ensure_admin_user

            asyncio.run(_ensure_admin_user(app))

    store.asearch.assert_not_called()


def test_migration_failure_is_non_fatal():
    """验证迁移存储抛错会被启动流程吸收，不会阻断应用启动。"""
    from uuid import uuid4

    admin_row = MagicMock()
    admin_row.id = uuid4()

    provider = _make_provider(admin_count=1)
    sf = _make_session_factory(admin_row=admin_row)
    store = AsyncMock()
    store.asearch = AsyncMock(side_effect=RuntimeError("store crashed"))
    app = _make_app_stub(store=store)

    with patch("app.gateway.deps.get_local_provider", return_value=provider):
        with patch("deerflow.persistence.engine.get_session_factory", return_value=sf):
            from app.gateway.app import _ensure_admin_user

            # 调用过程不应抛出异常。
            asyncio.run(_ensure_admin_user(app))


# ── 5.1–5.6 升级路径：孤儿线程迁移 ──────────────────────────────────────────


def test_migrate_orphaned_threads_stamps_user_id_on_unowned_rows():
    """验证升级后为仅存储于线程仓库且未归属的历史线程写入管理员标识。

    三条无主记录应保留原有标题并写入新管理员标识；已有其他归属的记录必须
    原样保留，防止升级迁移越权改写用户数据。
    """
    from app.gateway.app import _migrate_orphaned_threads

    # 三条孤儿记录与一条必须保持不变的已归属记录。
    items = [
        SimpleNamespace(key="t1", value={"metadata": {"title": "old-thread-1"}}),
        SimpleNamespace(key="t2", value={"metadata": {"title": "old-thread-2"}}),
        SimpleNamespace(key="t3", value={"metadata": {}}),
        SimpleNamespace(key="t4", value={"metadata": {"user_id": "someone-else", "title": "preserved"}}),
    ]
    store = AsyncMock()
    # 首次搜索返回整页，随后返回空页以终止迭代器。
    store.asearch = AsyncMock(side_effect=[items, []])
    aput_calls: list[tuple[tuple, str, dict]] = []

    async def _record_aput(namespace, key, value):
        """记录迁移写入参数，以验证写入目标和保留字段。"""
        aput_calls.append((namespace, key, value))

    store.aput = AsyncMock(side_effect=_record_aput)

    migrated = asyncio.run(_migrate_orphaned_threads(store, "admin-id-42"))

    # 三条孤儿行被迁移，已归属行保持不变。
    assert migrated == 3
    assert len(aput_calls) == 3
    rewritten_keys = {call[1] for call in aput_calls}
    assert rewritten_keys == {"t1", "t2", "t3"}
    # 每次改写都携带新用户标识，且已有标题必须保留。
    by_key = {call[1]: call[2] for call in aput_calls}
    assert by_key["t1"]["metadata"]["user_id"] == "admin-id-42"
    assert by_key["t1"]["metadata"]["title"] == "old-thread-1"
    assert by_key["t3"]["metadata"]["user_id"] == "admin-id-42"
    # 已归属记录绝不能被改写。
    assert "t4" not in rewritten_keys


def test_migrate_orphaned_threads_empty_store_is_noop():
    """验证空线程存储返回零迁移数且不会产生写入调用。"""
    from app.gateway.app import _migrate_orphaned_threads

    store = AsyncMock()
    store.asearch = AsyncMock(return_value=[])
    store.aput = AsyncMock()

    migrated = asyncio.run(_migrate_orphaned_threads(store, "admin-id-42"))

    assert migrated == 0
    store.aput.assert_not_called()


def test_iter_store_items_walks_multiple_pages():
    """验证游标式迭代器持续拉取满页，直到短页终止。

    以较小页大小模拟大量升级前数据，防止固定查询上限导致后续孤儿线程被
    静默遗漏。
    """
    from app.gateway.app import _iter_store_items

    page_a = [SimpleNamespace(key=f"t{i}", value={"metadata": {}}) for i in range(2)]
    page_b = [SimpleNamespace(key=f"t{i + 2}", value={"metadata": {}}) for i in range(2)]
    page_c: list = []  # 空短页会终止循环。

    store = AsyncMock()
    store.asearch = AsyncMock(side_effect=[page_a, page_b, page_c])

    async def _collect():
        """收集异步迭代器产出的键，用于确认跨页顺序完整。"""
        return [item.key async for item in _iter_store_items(store, ("threads",), page_size=2)]

    keys = asyncio.run(_collect())
    assert keys == ["t0", "t1", "t2", "t3"]
    # 共三次搜索：两页满页和一页空终止页。
    assert store.asearch.await_count == 3


def test_iter_store_items_terminates_on_short_page():
    """验证短页会立即结束循环，不会再发起无意义的终止探测。"""
    from app.gateway.app import _iter_store_items

    page = [SimpleNamespace(key=f"t{i}", value={}) for i in range(3)]
    store = AsyncMock()
    store.asearch = AsyncMock(return_value=page)

    async def _collect():
        """收集短页场景中的异步迭代结果。"""
        return [item.key async for item in _iter_store_items(store, ("threads",), page_size=10)]

    keys = asyncio.run(_collect())
    assert keys == ["t0", "t1", "t2"]
    # 只有一次调用：批次不足页大小时无需额外探测。
    assert store.asearch.await_count == 1
