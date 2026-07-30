"""本模块覆盖边界的行为、边界与回归场景，确保既有契约稳定。"""

from __future__ import annotations

import pytest

from deerflow.config.app_config import AppConfig
from deerflow.config.reload_boundary import (
    STARTUP_ONLY_FIELDS,
    STARTUP_ONLY_PREFIX,
    format_field_description,
    is_startup_only_field,
    iter_startup_only_field_paths,
)


def test_registry_has_a_reason_for_every_field():
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    for field_path, reason in STARTUP_ONLY_FIELDS.items():
        assert reason.strip(), f"empty reason for {field_path}"
        assert len(reason) > 20, f"reason for {field_path} too short to be useful: {reason!r}"


def test_iter_startup_only_field_paths_matches_registry():
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    assert sorted(iter_startup_only_field_paths()) == sorted(STARTUP_ONLY_FIELDS)


def test_is_startup_only_field_recognises_registered_fields():
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    for field_path in STARTUP_ONLY_FIELDS:
        assert is_startup_only_field(field_path)
    assert not is_startup_only_field("memory")  # hot-reloadable
    assert not is_startup_only_field("models")
    assert not is_startup_only_field("nonexistent_field")


def test_format_field_description_prefixes_with_marker():
    """验证格式在预期条件及边界场景下的可观察行为，防止相关回归。"""
    for field_path in STARTUP_ONLY_FIELDS:
        text = format_field_description(field_path)
        assert text.startswith(STARTUP_ONLY_PREFIX), text
        # The reason is appended after the prefix; the formatter must not
        # silently drop it.
        assert STARTUP_ONLY_FIELDS[field_path] in text


def test_format_field_description_rejects_unknown_field():
    """验证格式在预期条件及边界场景下的可观察行为，防止相关回归。"""
    with pytest.raises(KeyError):
        format_field_description("not_in_registry")


def test_format_field_description_appends_optional_field_doc():
    """验证格式在预期条件及边界场景下的可观察行为，防止相关回归。"""
    text = format_field_description("log_level", field_doc="Logging level (debug/info/warning/error).")
    assert text.startswith(STARTUP_ONLY_PREFIX)
    assert STARTUP_ONLY_FIELDS["log_level"] in text
    assert "debug/info/warning/error" in text


def test_appconfig_descriptions_retain_original_field_documentation():
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    descriptions = {
        "log_level": "debug/info/warning/error",
        "logging": "Structured logging and request trace correlation settings.",
        "database": "memory, sqlite, or postgres",
        "sandbox": "Sandbox provider",
        "run_events": "memory for dev",
        "checkpointer": "state-persistence checkpointer",
        "stream_bridge": "Stream bridge",
        "channel_connections": "IM channel connection",
    }
    for field_name, expected_substring in descriptions.items():
        description = AppConfig.model_fields[field_name].description or ""
        assert description.startswith(STARTUP_ONLY_PREFIX), f"AppConfig.{field_name} missing startup-only marker"
        assert expected_substring in description, f"AppConfig.{field_name} description lost original field doc; got {description!r}"


def test_appconfig_schema_marks_registered_fields_with_prefix():
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    schema_fields = AppConfig.model_fields
    for field_path in STARTUP_ONLY_FIELDS:
        if field_path not in schema_fields:
            # Some entries (e.g. ``channels``) live outside the AppConfig
            # schema. The registry still owns them, but the schema-prefix
            # assertion does not apply.
            continue
        description = schema_fields[field_path].description or ""
        assert description.startswith(STARTUP_ONLY_PREFIX), f"AppConfig.{field_path} should have Field(description=) starting with {STARTUP_ONLY_PREFIX!r}, got {description!r}"


def test_no_appconfig_field_uses_prefix_without_registration():
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    for name, info in AppConfig.model_fields.items():
        description = info.description or ""
        if not description.startswith(STARTUP_ONLY_PREFIX):
            continue
        assert name in STARTUP_ONLY_FIELDS, f"AppConfig.{name} schema description starts with {STARTUP_ONLY_PREFIX!r} but the field is not listed in reload_boundary.STARTUP_ONLY_FIELDS — update the registry."


def test_pydantic_field_descriptions_are_introspectable_at_runtime():
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    assert "database" in AppConfig.model_fields
    description = AppConfig.model_fields["database"].description
    assert description is not None
    assert description.startswith(STARTUP_ONLY_PREFIX)
