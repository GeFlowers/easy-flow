"""本模块覆盖相关测试，固定公开行为、失败处理与状态边界。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from deerflow.persistence.channel_connections import (
    ChannelConnectionRepository,
    ChannelConnectionRow,
    ChannelCredentialCipher,
    ChannelCredentialRow,
    ChannelOAuthStateRow,
)


@pytest.fixture
async def repo(tmp_path):
    """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'channels.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        yield ChannelConnectionRepository(
            get_session_factory(),
            cipher=ChannelCredentialCipher.from_key("test-encryption-key"),
        )
    finally:
        await close_engine()


class TestChannelConnectionRepository:
    """此测试组归集同一组件的用例，分别约束正常流程与关键边界条件。"""
    @pytest.mark.anyio
    async def test_connections_are_listed_per_owner(self, repo):
        """验证当前场景的异步调用：使用受控输入与依赖替身，通过5项断言固定返回、状态或副作用边界。"""
        alice = await repo.upsert_connection(
            owner_user_id="alice",
            provider="slack",
            external_account_id="U-alice",
            external_account_name="Alice",
            workspace_id="T1",
            workspace_name="Team One",
            scopes=["chat:write"],
        )
        await repo.upsert_connection(
            owner_user_id="bob",
            provider="slack",
            external_account_id="U-bob",
            external_account_name="Bob",
            workspace_id="T1",
            workspace_name="Team One",
            scopes=["chat:write"],
        )

        results = await repo.list_connections("alice")

        assert [item["id"] for item in results] == [alice["id"]]
        assert results[0]["owner_user_id"] == "alice"
        assert results[0]["provider"] == "slack"
        assert results[0]["scopes"] == ["chat:write"]
        assert "encrypted_access_token" not in results[0]

    @pytest.mark.anyio
    async def test_upsert_connection_updates_existing_provider_identity(self, repo):
        """验证当前场景的异步调用：使用受控输入与依赖替身，通过4项断言固定返回、状态或副作用边界。"""
        first = await repo.upsert_connection(
            owner_user_id="alice",
            provider="telegram",
            external_account_id="42",
            external_account_name="Alice",
            workspace_id=None,
            workspace_name=None,
            status="pending",
        )
        second = await repo.upsert_connection(
            owner_user_id="alice",
            provider="telegram",
            external_account_id="42",
            external_account_name="Alice Telegram",
            workspace_id=None,
            workspace_name=None,
            status="connected",
        )

        assert second["id"] == first["id"]
        assert second["status"] == "connected"
        assert second["external_account_name"] == "Alice Telegram"
        assert len(await repo.list_connections("alice")) == 1

    @pytest.mark.anyio
    async def test_upsert_connection_transfers_external_identity_between_owners(self, repo):
        """验证当前场景的异步调用：使用受控输入与依赖替身，通过5项断言固定返回、状态或副作用边界。"""
        await repo.upsert_connection(
            owner_user_id="alice",
            provider="slack",
            external_account_id="U-shared",
            workspace_id="T1",
            status="connected",
        )

        bob = await repo.upsert_connection(
            owner_user_id="bob",
            provider="slack",
            external_account_id="U-shared",
            workspace_id="T1",
            status="connected",
        )

        alice_rows = await repo.list_connections("alice")
        resolved = await repo.find_connection_by_external_identity(
            provider="slack",
            external_account_id="U-shared",
            workspace_id="T1",
        )

        assert alice_rows[0]["status"] == "revoked"
        assert bob["status"] == "connected"
        assert resolved is not None
        assert resolved["owner_user_id"] == "bob"
        assert resolved["id"] == bob["id"]

    @pytest.mark.anyio
    async def test_active_identity_unique_index_rejects_second_connected_owner(self, repo):
        """验证当前场景的异步调用：使用受控输入与依赖替身，通过0项断言固定返回、状态或副作用边界。"""
        # 单活动所有者不变量必须由数据库强制执行，而不是
        # 此处说明该测试段的前置条件、调用限制及预期边界。
        from sqlalchemy.exc import IntegrityError

        await repo.upsert_connection(
            owner_user_id="alice",
            provider="slack",
            external_account_id="U-shared",
            workspace_id="T1",
            status="connected",
        )

        with pytest.raises(IntegrityError):
            async with repo.session_factory() as session:
                session.add(
                    ChannelConnectionRow(
                        id="manual-duplicate-active",
                        owner_user_id="bob",
                        provider="slack",
                        external_account_id="U-shared",
                        workspace_id="T1",
                        status="connected",
                    )
                )
                await session.commit()

    @pytest.mark.anyio
    async def test_active_identity_unique_index_allows_revoked_rows(self, repo):
        """验证当前场景的异步调用：使用受控输入与依赖替身，通过1项断言固定返回、状态或副作用边界。"""
        # 已撤销的行不得占用活动身份槽，因此新的行
        # 随后允许相同身份的
        # 连接绑定。
        first = await repo.upsert_connection(
            owner_user_id="alice",
            provider="slack",
            external_account_id="U-shared",
            workspace_id="T1",
            status="connected",
        )
        await repo.disconnect_connection(connection_id=first["id"], owner_user_id="alice")

        second = await repo.upsert_connection(
            owner_user_id="bob",
            provider="slack",
            external_account_id="U-shared",
            workspace_id="T1",
            status="connected",
        )
        assert second["status"] == "connected"

    @pytest.mark.anyio
    async def test_concurrent_upserts_keep_single_active_owner(self, repo):
        """验证当前场景的异步调用：使用受控输入与依赖替身，通过1项断言固定返回、状态或副作用边界。"""
        import asyncio

        async def connect(owner: str):
            """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
            return await repo.upsert_connection(
                owner_user_id=owner,
                provider="slack",
                external_account_id="U-shared",
                workspace_id="T1",
                status="connected",
            )

        await asyncio.gather(connect("alice"), connect("bob"))

        async with repo.session_factory() as session:
            connected = (
                (
                    await session.execute(
                        select(ChannelConnectionRow).where(
                            ChannelConnectionRow.provider == "slack",
                            ChannelConnectionRow.external_account_id == "U-shared",
                            ChannelConnectionRow.workspace_id == "T1",
                            ChannelConnectionRow.status == "connected",
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert len(connected) == 1

    @pytest.mark.anyio
    async def test_credentials_are_encrypted_at_rest_and_decrypted_by_repository(self, repo):
        """验证当前场景的异步调用：使用受控输入与依赖替身，通过10项断言固定返回、状态或副作用边界。"""
        connection = await repo.upsert_connection(
            owner_user_id="alice",
            provider="slack",
            external_account_id="U-alice",
            workspace_id="T1",
        )
        expires_at = datetime.now(UTC) + timedelta(hours=1)

        await repo.store_credentials(
            connection["id"],
            access_token="xoxb-secret-access-token",
            refresh_token="secret-refresh-token",
            token_type="Bearer",
            expires_at=expires_at,
            extra={"bot_user_id": "B123"},
        )

        async with repo.session_factory() as session:
            row = (await session.execute(select(ChannelCredentialRow))).scalar_one()
            assert row.encrypted_access_token is not None
            assert "xoxb-secret-access-token" not in row.encrypted_access_token
            assert "secret-refresh-token" not in (row.encrypted_refresh_token or "")
            assert "B123" not in (row.encrypted_extra_json or "")

        credentials = await repo.get_credentials(connection["id"])

        assert credentials is not None
        assert credentials["access_token"] == "xoxb-secret-access-token"
        assert credentials["refresh_token"] == "secret-refresh-token"
        assert credentials["token_type"] == "Bearer"
        assert credentials["expires_at"] == expires_at
        assert credentials["extra"] == {"bot_user_id": "B123"}

    @pytest.mark.anyio
    async def test_get_credentials_returns_none_when_decryption_fails(self, repo, caplog):
        """验证当前场景的异步调用：使用受控输入与依赖替身，通过2项断言固定返回、状态或副作用边界。"""
        connection = await repo.upsert_connection(
            owner_user_id="alice",
            provider="slack",
            external_account_id="U-alice",
            workspace_id="T1",
        )
        await repo.store_credentials(connection["id"], access_token="xoxb-secret-access-token")
        wrong_key_repo = ChannelConnectionRepository(
            repo.session_factory,
            cipher=ChannelCredentialCipher.from_key("wrong-encryption-key"),
        )

        with caplog.at_level(logging.WARNING, logger="deerflow.persistence.channel_connections.sql"):
            credentials = await wrong_key_repo.get_credentials(connection["id"])

        assert credentials is None
        assert any("Unable to decrypt channel connection credentials" in record.message for record in caplog.records)

    @pytest.mark.anyio
    async def test_conversations_are_scoped_by_connection(self, repo):
        """验证当前场景的异步调用：使用受控输入与依赖替身，通过2项断言固定返回、状态或副作用边界。"""
        alice = await repo.upsert_connection(
            owner_user_id="alice",
            provider="slack",
            external_account_id="U-alice",
            workspace_id="T1",
        )
        bob = await repo.upsert_connection(
            owner_user_id="bob",
            provider="slack",
            external_account_id="U-bob",
            workspace_id="T1",
        )

        await repo.set_thread_id(
            connection_id=alice["id"],
            owner_user_id="alice",
            provider="slack",
            external_conversation_id="C-shared",
            external_topic_id="1710000000.000100",
            thread_id="thread-alice",
        )
        await repo.set_thread_id(
            connection_id=bob["id"],
            owner_user_id="bob",
            provider="slack",
            external_conversation_id="C-shared",
            external_topic_id="1710000000.000100",
            thread_id="thread-bob",
        )

        assert await repo.get_thread_id(alice["id"], "C-shared", "1710000000.000100") == "thread-alice"
        assert await repo.get_thread_id(bob["id"], "C-shared", "1710000000.000100") == "thread-bob"

    @pytest.mark.anyio
    async def test_disconnect_connection_revokes_owner_connection_and_removes_credentials(self, repo):
        """验证当前场景的异步调用：使用受控输入与依赖替身，通过5项断言固定返回、状态或副作用边界。"""
        connection = await repo.upsert_connection(
            owner_user_id="alice",
            provider="telegram",
            external_account_id="42",
        )
        await repo.store_credentials(connection["id"], access_token="secret-token")

        disconnected = await repo.disconnect_connection(
            connection_id=connection["id"],
            owner_user_id="alice",
        )

        assert disconnected is True
        async with repo.session_factory() as session:
            connection_row = await session.get(ChannelConnectionRow, connection["id"])
            credential_row = await session.get(ChannelCredentialRow, connection["id"])
        assert connection_row is not None
        assert connection_row.status == "revoked"
        assert credential_row is None
        assert (
            await repo.find_connection_by_external_identity(
                provider="telegram",
                external_account_id="42",
            )
            is None
        )

    @pytest.mark.anyio
    async def test_disconnect_connection_is_owner_scoped(self, repo):
        """验证当前场景的异步调用：使用受控输入与依赖替身，通过2项断言固定返回、状态或副作用边界。"""
        connection = await repo.upsert_connection(
            owner_user_id="alice",
            provider="telegram",
            external_account_id="42",
        )

        disconnected = await repo.disconnect_connection(
            connection_id=connection["id"],
            owner_user_id="bob",
        )

        assert disconnected is False
        assert (await repo.list_connections("alice"))[0]["status"] == "connected"

    @pytest.mark.anyio
    async def test_consume_oauth_state_deletes_expired_states(self, repo):
        """验证当前场景的异步调用：使用受控输入与依赖替身，通过2项断言固定返回、状态或副作用边界。"""
        now = datetime.now(UTC)
        await repo.create_oauth_state(
            owner_user_id="alice",
            provider="slack",
            state="expired-state",
            expires_at=now - timedelta(minutes=1),
        )
        await repo.create_oauth_state(
            owner_user_id="alice",
            provider="slack",
            state="active-state",
            expires_at=now + timedelta(minutes=5),
        )

        consumed = await repo.consume_oauth_state(provider="slack", state="expired-state", now=now)

        assert consumed is None
        async with repo.session_factory() as session:
            states = (await session.execute(select(ChannelOAuthStateRow))).scalars().all()
        assert [state.state_hash for state in states] == [repo.hash_state("active-state")]

    @pytest.mark.anyio
    async def test_count_oauth_states_active_only_and_delete_expired(self, repo):
        """验证当前场景的异步调用：使用受控输入与依赖替身，通过4项断言固定返回、状态或副作用边界。"""
        now = datetime.now(UTC)
        await repo.create_oauth_state(
            owner_user_id="alice",
            provider="slack",
            state="expired-state",
            expires_at=now - timedelta(minutes=1),
        )
        await repo.create_oauth_state(
            owner_user_id="alice",
            provider="slack",
            state="active-state",
            expires_at=now + timedelta(minutes=5),
        )

        assert await repo.count_oauth_states(owner_user_id="alice", provider="slack", active_only=True, now=now) == 1
        assert await repo.delete_expired_oauth_states(now=now) == 1
        assert await repo.count_oauth_states(owner_user_id="alice", provider="slack") == 1
        # 固定幸存行是活动行（反向到期
        # 谓词将删除活动行，仍然返回 1，并在上面传递）。
        async with repo.session_factory() as session:
            survivors = (await session.execute(select(ChannelOAuthStateRow))).scalars().all()
        assert [row.state_hash for row in survivors] == [repo.hash_state("active-state")]

    @pytest.mark.anyio
    async def test_create_oauth_state_within_cap_enforces_pending_cap(self, repo):
        """验证当前场景的异步调用：使用受控输入与依赖替身，通过4项断言固定返回、状态或副作用边界。"""
        now = datetime.now(UTC)
        expires = now + timedelta(minutes=5)

        for i in range(3):
            inserted = await repo.create_oauth_state_within_cap(owner_user_id="alice", provider="slack", state=f"code-{i}", expires_at=expires, max_pending=3, now=now)
            assert inserted is True

        # 达到上限：拒绝下一个发行并且不插入任何内容。
        assert await repo.create_oauth_state_within_cap(owner_user_id="alice", provider="slack", state="code-over", expires_at=expires, max_pending=3, now=now) is False
        assert await repo.count_oauth_states(owner_user_id="alice", provider="slack", active_only=True, now=now) == 3

        # 过期行被修剪并释放容量；不同的所有者不受影响。
        assert await repo.create_oauth_state_within_cap(owner_user_id="bob", provider="slack", state="bob-1", expires_at=expires, max_pending=3, now=now) is True

    @pytest.mark.anyio
    async def test_create_oauth_state_within_cap_ignores_expired_rows(self, repo):
        """验证当前场景的异步调用：使用受控输入与依赖替身，通过2项断言固定返回、状态或副作用边界。"""
        now = datetime.now(UTC)
        # 三个已过期的行不得计入上限。
        for i in range(3):
            await repo.create_oauth_state(owner_user_id="alice", provider="slack", state=f"old-{i}", expires_at=now - timedelta(minutes=1))

        inserted = await repo.create_oauth_state_within_cap(owner_user_id="alice", provider="slack", state="fresh", expires_at=now + timedelta(minutes=5), max_pending=3, now=now)
        assert inserted is True
        assert await repo.count_oauth_states(owner_user_id="alice", provider="slack", active_only=True, now=now) == 1

    @pytest.mark.anyio
    async def test_create_oauth_state_within_cap_does_not_leak_under_concurrency(self, repo):
        """验证当前场景的异步调用：使用受控输入与依赖替身，通过2项断言固定返回、状态或副作用边界。"""
        import anyio

        now = datetime.now(UTC)
        expires = now + timedelta(minutes=5)
        results: list[bool] = []

        async def issue(state: str) -> None:
            """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
            results.append(await repo.create_oauth_state_within_cap(owner_user_id="alice", provider="slack", state=state, expires_at=expires, max_pending=3, now=now))

        async with anyio.create_task_group() as tg:
            for i in range(8):
                tg.start_soon(issue, f"code-{i}")

        assert sum(1 for ok in results if ok) == 3
        assert await repo.count_oauth_states(owner_user_id="alice", provider="slack", active_only=True, now=now) == 3

    @pytest.mark.anyio
    async def test_consume_oauth_state_is_one_time_even_under_concurrent_consumers(self, repo):
        """验证当前场景的异步调用：使用受控输入与依赖替身，通过2项断言固定返回、状态或副作用边界。"""
        import anyio

        now = datetime.now(UTC)
        await repo.create_oauth_state(
            owner_user_id="alice",
            provider="slack",
            state="bind-once",
            expires_at=now + timedelta(minutes=5),
        )

        results: list = []

        async def consume():
            """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
            results.append(await repo.consume_oauth_state(provider="slack", state="bind-once", now=now))

        async with anyio.create_task_group() as tg:
            tg.start_soon(consume)
            tg.start_soon(consume)

        consumed = [result for result in results if result is not None]
        assert len(consumed) == 1
        assert consumed[0]["owner_user_id"] == "alice"

    @pytest.mark.anyio
    async def test_upsert_connection_retries_as_update_when_concurrent_insert_wins(self, repo):
        """验证当前场景的异步调用：使用受控输入与依赖替身，通过3项断言固定返回、状态或副作用边界。"""
        first = await repo.upsert_connection(
            owner_user_id="alice",
            provider="slack",
            external_account_id="U-race",
            workspace_id="T-race",
            status="pending",
        )

        real_factory = repo.session_factory

        class _EmptyResult:
            """此测试组归集同一组件的用例，分别约束正常流程与关键边界条件。"""
            @staticmethod
            def scalar_one_or_none():
                """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
                return None

        class MissFirstSelectSession:
            """此测试组归集同一组件的用例，分别约束正常流程与关键边界条件。"""

            def __init__(self, session):
                """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
                self._session = session
                self._missed = False

            def __getattr__(self, name):
                """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
                return getattr(self._session, name)

            async def execute(self, *args, **kwargs):
                """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
                result = await self._session.execute(*args, **kwargs)
                if not self._missed:
                    self._missed = True
                    return _EmptyResult()
                return result

            async def __aenter__(self):
                """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
                await self._session.__aenter__()
                return self

            async def __aexit__(self, *args):
                """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
                return await self._session.__aexit__(*args)

        repo.session_factory = lambda: MissFirstSelectSession(real_factory())
        try:
            second = await repo.upsert_connection(
                owner_user_id="alice",
                provider="slack",
                external_account_id="U-race",
                workspace_id="T-race",
                status="connected",
            )
        finally:
            repo.session_factory = real_factory

        assert second["id"] == first["id"]
        assert second["status"] == "connected"
        connections = await repo.list_connections("alice")
        assert len(connections) == 1
