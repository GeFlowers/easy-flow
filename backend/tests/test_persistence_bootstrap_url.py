"""本模块覆盖持久化的行为、边界与回归场景，确保既有契约稳定。"""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy.engine.url import make_url

from deerflow.persistence.bootstrap import _alembic_safe_url, _escape_url_for_alembic, _get_alembic_config


def _fake_engine(url: str) -> SimpleNamespace:
    """准备可控测试资源与状态，供后续断言读取。"""
    return SimpleNamespace(url=make_url(url))


def test_safe_url_preserves_password_for_postgres() -> None:
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    engine = _fake_engine("postgresql://alice:s3cret@db.example.com/app")
    safe = _alembic_safe_url(engine)
    assert "s3cret" in safe, "password got masked: alembic would auth with garbage"
    assert "***" not in safe


def test_safe_url_escapes_percent_for_configparser() -> None:
    # URL-encoded ``@`` in password -> raw ``%40`` in URL -> ConfigParser
    # would treat it as an interpolation marker.
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    engine = _fake_engine("postgresql://alice:p%40ss@db.example.com/app")
    safe = _alembic_safe_url(engine)
    assert "p%%40ss" in safe, f"percent not doubled, ConfigParser will fail: {safe}"


def test_alembic_config_accepts_url_with_percent_and_round_trips() -> None:
    # The whole point: build_config should not raise, and the URL alembic
    # reads back should match the original (single ``%``, real password).
    """验证配置在预期条件及边界场景下的可观察行为，防止相关回归。"""
    original = "postgresql://alice:p%40ss@db.example.com/app"
    engine = _fake_engine(original)
    cfg = _get_alembic_config(engine)
    roundtrip = cfg.get_main_option("sqlalchemy.url")
    assert roundtrip == original, f"alembic sees a different URL than we set: {roundtrip}"


def test_sqlite_url_does_not_double_percent_unnecessarily() -> None:
    # No percent in the URL -> no escaping needed -> output equals input.
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    engine = _fake_engine("sqlite+aiosqlite:///tmp/db.sqlite")
    safe = _alembic_safe_url(engine)
    assert safe == "sqlite+aiosqlite:///tmp/db.sqlite"


def test_escape_url_for_alembic_doubles_only_percent_signs() -> None:
    # Shared helper used by both ``bootstrap._alembic_safe_url`` and
    # ``scripts/_autogen_revision._alembic_config`` -- pins the round-trip
    # rule so any future URL/ConfigParser corner case is fixed in one place.
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    assert _escape_url_for_alembic("postgresql://a:p%40ss@h/d") == "postgresql://a:p%%40ss@h/d"
    assert _escape_url_for_alembic("sqlite:///x.db") == "sqlite:///x.db"
    # Idempotency is intentionally NOT a property -- doubling is one-way;
    # callers must escape exactly once on the way into set_main_option.
    assert _escape_url_for_alembic("a%%b") == "a%%%%b"
