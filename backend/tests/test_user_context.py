'未说明'

from types import SimpleNamespace

import pytest

from deerflow.runtime.user_context import (
    DEFAULT_USER_ID,
    CurrentUser,
    get_current_user,
    get_effective_user_id,
    require_current_user,
    reset_current_user,
    set_current_user,
)


@pytest.mark.no_auto_user
def test_default_is_none():
    '未说明'
    assert get_current_user() is None


@pytest.mark.no_auto_user
def test_set_and_reset_roundtrip():
    '未说明'
    user = SimpleNamespace(id="user-1")
    token = set_current_user(user)
    try:
        assert get_current_user() is user
    finally:
        reset_current_user(token)
    assert get_current_user() is None


@pytest.mark.no_auto_user
def test_require_current_user_raises_when_unset():
    '未说明'
    assert get_current_user() is None
    with pytest.raises(RuntimeError, match="without user context"):
        require_current_user()


@pytest.mark.no_auto_user
def test_require_current_user_returns_user_when_set():
    '未说明'
    user = SimpleNamespace(id="user-2")
    token = set_current_user(user)
    try:
        assert require_current_user() is user
    finally:
        reset_current_user(token)


@pytest.mark.no_auto_user
def test_protocol_accepts_duck_typed():
    '未说明'
    user = SimpleNamespace(id="user-3")
    assert isinstance(user, CurrentUser)


@pytest.mark.no_auto_user
def test_protocol_rejects_no_id():
    '未说明'
    not_a_user = SimpleNamespace(email="no-id@example.com")
    assert not isinstance(not_a_user, CurrentUser)


# ---------------------------------------------------------------------------
# get_effective_user_id / DEFAULT_USER_ID tests
# ---------------------------------------------------------------------------


def test_default_user_id_is_default():
    '未说明'
    assert DEFAULT_USER_ID == "default"


@pytest.mark.no_auto_user
def test_effective_user_id_returns_default_when_no_user():
    '未说明'
    assert get_effective_user_id() == "default"


@pytest.mark.no_auto_user
def test_effective_user_id_returns_user_id_when_set():
    '未说明'
    user = SimpleNamespace(id="u-abc-123")
    token = set_current_user(user)
    try:
        assert get_effective_user_id() == "u-abc-123"
    finally:
        reset_current_user(token)


@pytest.mark.no_auto_user
def test_effective_user_id_coerces_to_str():
    '未说明'
    import uuid

    uid = uuid.uuid4()

    user = SimpleNamespace(id=uid)
    token = set_current_user(user)
    try:
        assert get_effective_user_id() == str(uid)
    finally:
        reset_current_user(token)
