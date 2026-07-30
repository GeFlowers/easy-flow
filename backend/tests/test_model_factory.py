"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

import pytest
from langchain.chat_models import BaseChatModel

from deerflow.config.app_config import AppConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.models import factory as factory_module
from deerflow.models import openai_codex_provider as codex_provider_module
from deerflow.reflection import resolve_class

# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


def _make_app_config(models: list[ModelConfig]) -> AppConfig:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    return AppConfig(
        models=models,
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
    )


def _make_model(
    name: str = "test-model",
    *,
    use: str = "langchain_openai:ChatOpenAI",
    supports_thinking: bool = False,
    supports_reasoning_effort: bool = False,
    when_thinking_enabled: dict | None = None,
    when_thinking_disabled: dict | None = None,
    thinking: dict | None = None,
    max_tokens: int | None = None,
) -> ModelConfig:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    return ModelConfig(
        name=name,
        display_name=name,
        description=None,
        use=use,
        model=name,
        max_tokens=max_tokens,
        supports_thinking=supports_thinking,
        supports_reasoning_effort=supports_reasoning_effort,
        when_thinking_enabled=when_thinking_enabled,
        when_thinking_disabled=when_thinking_disabled,
        thinking=thinking,
        supports_vision=False,
    )


class FakeChatModel(BaseChatModel):
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""

    captured_kwargs: dict = {}

    def __init__(self, **kwargs):
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        FakeChatModel.captured_kwargs = dict(kwargs)
        super().__init__(**kwargs)

    @property
    def _llm_type(self) -> str:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return "fake"

    def _generate(self, *args, **kwargs):  # type: ignore[override]
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        raise NotImplementedError

    def _stream(self, *args, **kwargs):  # type: ignore[override]
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        raise NotImplementedError


def _patch_factory(monkeypatch, app_config: AppConfig, model_class=FakeChatModel):
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    monkeypatch.setattr(factory_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: model_class)
    monkeypatch.setattr(factory_module, "build_tracing_callbacks", lambda: [])


def _capturing_class(base_cls: type, captured: dict) -> type:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""

    class _Capturing(base_cls):  # type: ignore[valid-type,misc]
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            captured.clear()
            captured.update(kwargs)

    return _Capturing


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


def test_uses_first_model_when_name_is_none(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    cfg = _make_app_config([_make_model("alpha"), _make_model("beta")])
    _patch_factory(monkeypatch, cfg)

    FakeChatModel.captured_kwargs = {}
    factory_module.create_chat_model(name=None)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert FakeChatModel.captured_kwargs.get("model") == "alpha"


def test_raises_when_model_not_found(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    cfg = _make_app_config([_make_model("only-model")])
    monkeypatch.setattr(factory_module, "get_app_config", lambda: cfg)
    monkeypatch.setattr(factory_module, "build_tracing_callbacks", lambda: [])

    with pytest.raises(ValueError, match="ghost-model"):
        factory_module.create_chat_model(name="ghost-model")


def test_pricing_metadata_never_reaches_the_provider_client(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    model = _make_model("priced")
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    model.pricing = {"currency": "CNY", "input_per_million": 8, "output_per_million": 32, "input_cache_hit_per_million": 0.8}
    cfg = _make_app_config([model])
    _patch_factory(monkeypatch, cfg)

    FakeChatModel.captured_kwargs = {}
    factory_module.create_chat_model(name="priced")

    assert "pricing" not in FakeChatModel.captured_kwargs


def test_appends_all_tracing_callbacks(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    cfg = _make_app_config([_make_model("alpha")])
    _patch_factory(monkeypatch, cfg)
    monkeypatch.setattr(factory_module, "build_tracing_callbacks", lambda: ["smith-callback", "langfuse-callback"])

    FakeChatModel.captured_kwargs = {}
    model = factory_module.create_chat_model(name="alpha")

    assert model.callbacks == ["smith-callback", "langfuse-callback"]


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


def test_thinking_enabled_raises_when_not_supported_but_when_thinking_enabled_is_set(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    wte = {"thinking": {"type": "enabled", "budget_tokens": 5000}}
    cfg = _make_app_config([_make_model("no-think", supports_thinking=False, when_thinking_enabled=wte)])
    _patch_factory(monkeypatch, cfg)

    with pytest.raises(ValueError, match="does not support thinking"):
        factory_module.create_chat_model(name="no-think", thinking_enabled=True)


def test_thinking_enabled_raises_for_empty_when_thinking_enabled_explicitly_set(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    cfg = _make_app_config([_make_model("no-think-empty", supports_thinking=False, when_thinking_enabled={})])
    _patch_factory(monkeypatch, cfg)

    with pytest.raises(ValueError, match="does not support thinking"):
        factory_module.create_chat_model(name="no-think-empty", thinking_enabled=True)


def test_thinking_enabled_merges_when_thinking_enabled_settings(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    wte = {"temperature": 1.0, "max_tokens": 16000}
    cfg = _make_app_config([_make_model("thinker", supports_thinking=True, when_thinking_enabled=wte)])
    _patch_factory(monkeypatch, cfg)

    FakeChatModel.captured_kwargs = {}
    factory_module.create_chat_model(name="thinker", thinking_enabled=True)

    assert FakeChatModel.captured_kwargs.get("temperature") == 1.0
    assert FakeChatModel.captured_kwargs.get("max_tokens") == 16000


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


def test_thinking_disabled_openai_gateway_format(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    wte = {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": 10000}}}
    cfg = _make_app_config(
        [
            _make_model(
                "openai-gw",
                supports_thinking=True,
                supports_reasoning_effort=True,
                when_thinking_enabled=wte,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="openai-gw", thinking_enabled=False)

    assert captured.get("extra_body") == {"thinking": {"type": "disabled"}}
    assert captured.get("reasoning_effort") == "minimal"
    assert "thinking" not in captured  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。


def test_thinking_disabled_langchain_anthropic_format(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    wte = {"thinking": {"type": "enabled", "budget_tokens": 8000}}
    cfg = _make_app_config(
        [
            _make_model(
                "anthropic-native",
                use="langchain_anthropic:ChatAnthropic",
                supports_thinking=True,
                supports_reasoning_effort=False,
                when_thinking_enabled=wte,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="anthropic-native", thinking_enabled=False)

    assert captured.get("thinking") == {"type": "disabled"}
    assert "extra_body" not in captured
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert captured.get("reasoning_effort") is None


def test_thinking_disabled_no_when_thinking_enabled_does_nothing(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    cfg = _make_app_config([_make_model("plain", supports_thinking=True, when_thinking_enabled=None)])
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="plain", thinking_enabled=False)

    assert "extra_body" not in captured
    assert "thinking" not in captured
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert captured.get("reasoning_effort") is None


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


def test_when_thinking_disabled_takes_precedence_over_hardcoded_disable(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    wte = {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": 10000}}}
    wtd = {"extra_body": {"thinking": {"type": "disabled"}}, "reasoning_effort": "low"}
    cfg = _make_app_config(
        [
            _make_model(
                "custom-disable",
                supports_thinking=True,
                supports_reasoning_effort=True,
                when_thinking_enabled=wte,
                when_thinking_disabled=wtd,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="custom-disable", thinking_enabled=False)

    assert captured.get("extra_body") == {"thinking": {"type": "disabled"}}
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert captured.get("reasoning_effort") == "low"


def test_when_thinking_disabled_not_used_when_thinking_enabled(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    wte = {"extra_body": {"thinking": {"type": "enabled"}}}
    wtd = {"extra_body": {"thinking": {"type": "disabled"}}}
    cfg = _make_app_config(
        [
            _make_model(
                "wtd-ignored",
                supports_thinking=True,
                when_thinking_enabled=wte,
                when_thinking_disabled=wtd,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="wtd-ignored", thinking_enabled=True)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert captured.get("extra_body") == {"thinking": {"type": "enabled"}}


def test_when_thinking_disabled_without_when_thinking_enabled_still_applies(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    cfg = _make_app_config(
        [
            _make_model(
                "wtd-only",
                supports_thinking=True,
                supports_reasoning_effort=True,
                when_thinking_disabled={"reasoning_effort": "low"},
            )
        ]
    )
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="wtd-only", thinking_enabled=False)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert captured.get("reasoning_effort") == "low"


def test_when_thinking_disabled_excluded_from_model_dump(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    wte = {"extra_body": {"thinking": {"type": "enabled"}}}
    wtd = {"extra_body": {"thinking": {"type": "disabled"}}}
    cfg = _make_app_config(
        [
            _make_model(
                "no-leak-wtd",
                supports_thinking=True,
                when_thinking_enabled=wte,
                when_thinking_disabled=wtd,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="no-leak-wtd", thinking_enabled=True)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert "when_thinking_disabled" not in captured


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


def test_reasoning_effort_cleared_when_not_supported(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    cfg = _make_app_config([_make_model("no-effort", supports_reasoning_effort=False)])
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="no-effort", thinking_enabled=False)

    assert captured.get("reasoning_effort") is None


def test_reasoning_effort_preserved_when_supported(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    wte = {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": 5000}}}
    cfg = _make_app_config(
        [
            _make_model(
                "effort-model",
                supports_thinking=True,
                supports_reasoning_effort=True,
                when_thinking_enabled=wte,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="effort-model", thinking_enabled=False)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert captured.get("reasoning_effort") == "minimal"


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


def test_thinking_shortcut_enables_thinking_when_thinking_enabled(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    thinking_settings = {"type": "enabled", "budget_tokens": 8000}
    cfg = _make_app_config(
        [
            _make_model(
                "shortcut-model",
                use="langchain_anthropic:ChatAnthropic",
                supports_thinking=True,
                thinking=thinking_settings,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="shortcut-model", thinking_enabled=True)

    assert captured.get("thinking") == thinking_settings


def test_thinking_shortcut_disables_thinking_when_thinking_disabled(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    thinking_settings = {"type": "enabled", "budget_tokens": 8000}
    cfg = _make_app_config(
        [
            _make_model(
                "shortcut-disable",
                use="langchain_anthropic:ChatAnthropic",
                supports_thinking=True,
                supports_reasoning_effort=False,
                thinking=thinking_settings,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="shortcut-disable", thinking_enabled=False)

    assert captured.get("thinking") == {"type": "disabled"}
    assert "extra_body" not in captured


def test_thinking_shortcut_merges_with_when_thinking_enabled(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    thinking_settings = {"type": "enabled", "budget_tokens": 8000}
    wte = {"max_tokens": 16000}
    cfg = _make_app_config(
        [
            _make_model(
                "merge-model",
                use="langchain_anthropic:ChatAnthropic",
                supports_thinking=True,
                thinking=thinking_settings,
                when_thinking_enabled=wte,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="merge-model", thinking_enabled=True)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert captured.get("thinking") == thinking_settings
    assert captured.get("max_tokens") == 16000


def test_thinking_shortcut_not_leaked_into_model_when_disabled(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    thinking_settings = {"type": "enabled", "budget_tokens": 8000}
    cfg = _make_app_config(
        [
            _make_model(
                "no-leak",
                use="langchain_anthropic:ChatAnthropic",
                supports_thinking=True,
                supports_reasoning_effort=False,
                thinking=thinking_settings,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="no-leak", thinking_enabled=False)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert captured.get("thinking") == {"type": "disabled"}


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


def test_openai_compatible_provider_passes_base_url(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    model = ModelConfig(
        name="minimax-m3",
        display_name="MiniMax M3",
        description=None,
        use="langchain_openai:ChatOpenAI",
        model="MiniMax-M3",
        base_url="https://api.minimax.io/v1",
        api_key="test-key",
        max_tokens=4096,
        temperature=1.0,
        supports_vision=True,
        supports_thinking=False,
    )
    from langchain_openai import ChatOpenAI

    cfg = _make_app_config([model])
    captured: dict = {}
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    _patch_factory(monkeypatch, cfg, model_class=_capturing_class(ChatOpenAI, captured))

    factory_module.create_chat_model(name="minimax-m3")

    assert captured.get("model") == "MiniMax-M3"
    assert captured.get("base_url") == "https://api.minimax.io/v1"
    assert captured.get("api_key") == "test-key"
    assert captured.get("temperature") == 1.0
    assert captured.get("max_tokens") == 4096
    assert captured.get("stream_usage") is True


def test_openai_compatible_provider_respects_explicit_stream_usage(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    model = ModelConfig(
        name="minimax-m3",
        display_name="MiniMax M3",
        description=None,
        use="langchain_openai:ChatOpenAI",
        model="MiniMax-M3",
        base_url="https://api.minimax.io/v1",
        api_key="test-key",
        stream_usage=False,
        supports_vision=True,
        supports_thinking=False,
    )
    cfg = _make_app_config([model])
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="minimax-m3")

    assert captured.get("stream_usage") is False


def test_openai_compatible_provider_enables_stream_usage_for_openai_api_base(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    model = ModelConfig(
        name="openai-compatible",
        display_name="OpenAI-Compatible",
        description=None,
        use="langchain_openai:ChatOpenAI",
        model="example-model",
        openai_api_base="https://example.com/v1",
        api_key="test-key",
        supports_vision=False,
        supports_thinking=False,
    )
    from langchain_openai import ChatOpenAI

    cfg = _make_app_config([model])
    captured: dict = {}
    _patch_factory(monkeypatch, cfg, model_class=_capturing_class(ChatOpenAI, captured))

    factory_module.create_chat_model(name="openai-compatible")

    assert captured.get("openai_api_base") == "https://example.com/v1"
    assert captured.get("stream_usage") is True


def test_non_openai_provider_does_not_receive_stream_usage_default(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    model = ModelConfig(
        name="ollama-local",
        display_name="Ollama Local",
        description=None,
        use="langchain_ollama:ChatOllama",
        model="qwen2.5",
        base_url="http://127.0.0.1:11434",
        supports_vision=False,
        supports_thinking=False,
    )
    cfg = _make_app_config([model])
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="ollama-local")

    assert captured.get("base_url") == "http://127.0.0.1:11434"
    assert "stream_usage" not in captured


def test_openai_compatible_provider_multiple_models(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    m1 = ModelConfig(
        name="minimax-m3",
        display_name="MiniMax M3",
        description=None,
        use="langchain_openai:ChatOpenAI",
        model="MiniMax-M3",
        base_url="https://api.minimax.io/v1",
        api_key="test-key",
        temperature=1.0,
        supports_vision=True,
        supports_thinking=False,
    )
    m2 = ModelConfig(
        name="minimax-m2.7-highspeed",
        display_name="MiniMax M2.7 Highspeed",
        description=None,
        use="langchain_openai:ChatOpenAI",
        model="MiniMax-M2.7-highspeed",
        base_url="https://api.minimax.io/v1",
        api_key="test-key",
        temperature=1.0,
        supports_vision=False,  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        supports_thinking=False,
    )
    cfg = _make_app_config([m1, m2])
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    factory_module.create_chat_model(name="minimax-m3")
    assert captured.get("model") == "MiniMax-M3"

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    factory_module.create_chat_model(name="minimax-m2.7-highspeed")
    assert captured.get("model") == "MiniMax-M2.7-highspeed"


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


class FakeCodexChatModel(FakeChatModel):
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
    pass


def test_codex_provider_disables_reasoning_when_thinking_disabled(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    cfg = _make_app_config(
        [
            _make_model(
                "codex",
                use="deerflow.models.openai_codex_provider:CodexChatModel",
                supports_thinking=True,
                supports_reasoning_effort=True,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg, model_class=FakeCodexChatModel)
    monkeypatch.setattr(codex_provider_module, "CodexChatModel", FakeCodexChatModel)

    FakeChatModel.captured_kwargs = {}
    factory_module.create_chat_model(name="codex", thinking_enabled=False)

    assert FakeChatModel.captured_kwargs.get("reasoning_effort") == "none"


def test_codex_provider_preserves_explicit_reasoning_effort(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    cfg = _make_app_config(
        [
            _make_model(
                "codex",
                use="deerflow.models.openai_codex_provider:CodexChatModel",
                supports_thinking=True,
                supports_reasoning_effort=True,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg, model_class=FakeCodexChatModel)
    monkeypatch.setattr(codex_provider_module, "CodexChatModel", FakeCodexChatModel)

    FakeChatModel.captured_kwargs = {}
    factory_module.create_chat_model(name="codex", thinking_enabled=True, reasoning_effort="high")

    assert FakeChatModel.captured_kwargs.get("reasoning_effort") == "high"


def test_codex_provider_defaults_reasoning_effort_to_medium(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    cfg = _make_app_config(
        [
            _make_model(
                "codex",
                use="deerflow.models.openai_codex_provider:CodexChatModel",
                supports_thinking=True,
                supports_reasoning_effort=True,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg, model_class=FakeCodexChatModel)
    monkeypatch.setattr(codex_provider_module, "CodexChatModel", FakeCodexChatModel)

    FakeChatModel.captured_kwargs = {}
    factory_module.create_chat_model(name="codex", thinking_enabled=True)

    assert FakeChatModel.captured_kwargs.get("reasoning_effort") == "medium"


def test_codex_provider_strips_unsupported_max_tokens(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    cfg = _make_app_config(
        [
            _make_model(
                "codex",
                use="deerflow.models.openai_codex_provider:CodexChatModel",
                supports_thinking=True,
                supports_reasoning_effort=True,
                max_tokens=4096,
            )
        ]
    )
    _patch_factory(monkeypatch, cfg, model_class=FakeCodexChatModel)
    monkeypatch.setattr(codex_provider_module, "CodexChatModel", FakeCodexChatModel)

    FakeChatModel.captured_kwargs = {}
    factory_module.create_chat_model(name="codex", thinking_enabled=True)

    assert "max_tokens" not in FakeChatModel.captured_kwargs


def test_thinking_disabled_vllm_chat_template_format(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    wte = {"extra_body": {"chat_template_kwargs": {"thinking": True}}}
    model = _make_model(
        "vllm-qwen",
        use="deerflow.models.vllm_provider:VllmChatModel",
        supports_thinking=True,
        when_thinking_enabled=wte,
    )
    model.extra_body = {"top_k": 20}
    cfg = _make_app_config([model])
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="vllm-qwen", thinking_enabled=False)

    assert captured.get("extra_body") == {"top_k": 20, "chat_template_kwargs": {"thinking": False}}
    assert captured.get("reasoning_effort") is None


def test_thinking_disabled_vllm_enable_thinking_format(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    wte = {"extra_body": {"chat_template_kwargs": {"enable_thinking": True}}}
    model = _make_model(
        "vllm-qwen-enable",
        use="deerflow.models.vllm_provider:VllmChatModel",
        supports_thinking=True,
        when_thinking_enabled=wte,
    )
    model.extra_body = {"top_k": 20}
    cfg = _make_app_config([model])
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="vllm-qwen-enable", thinking_enabled=False)

    assert captured.get("extra_body") == {
        "top_k": 20,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    assert captured.get("reasoning_effort") is None


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


class _FakeWithStreamUsage(FakeChatModel):
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""

    stream_usage: bool | None = None


def test_stream_usage_injected_for_openai_compatible_model(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    cfg = _make_app_config([_make_model("deepseek", use="langchain_deepseek:ChatDeepSeek")])
    _patch_factory(monkeypatch, cfg, model_class=_FakeWithStreamUsage)

    captured: dict = {}

    class CapturingModel(_FakeWithStreamUsage):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="deepseek")

    assert captured.get("stream_usage") is True


def test_stream_usage_not_injected_for_non_openai_model(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    cfg = _make_app_config([_make_model("claude", use="langchain_anthropic:ChatAnthropic")])
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="claude")

    assert "stream_usage" not in captured


def test_stream_usage_not_overridden_when_explicitly_set_in_config(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    cfg = _make_app_config([_make_model("deepseek", use="langchain_deepseek:ChatDeepSeek")])
    _patch_factory(monkeypatch, cfg, model_class=_FakeWithStreamUsage)

    captured: dict = {}

    class CapturingModel(_FakeWithStreamUsage):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    original_get_model_config = cfg.get_model_config

    def patched_get_model_config(name):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        mc = original_get_model_config(name)
        mc.stream_usage = False  # type: ignore[attr-defined]
        return mc

    monkeypatch.setattr(cfg, "get_model_config", patched_get_model_config)

    factory_module.create_chat_model(name="deepseek")

    assert captured.get("stream_usage") is False


def test_openai_responses_api_settings_are_passed_to_chatopenai(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    model = ModelConfig(
        name="gpt-5-responses",
        display_name="GPT-5 Responses",
        description=None,
        use="langchain_openai:ChatOpenAI",
        model="gpt-5",
        api_key="test-key",
        use_responses_api=True,
        output_version="responses/v1",
        supports_thinking=False,
        supports_vision=True,
    )
    cfg = _make_app_config([model])
    _patch_factory(monkeypatch, cfg)

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    monkeypatch.setattr(factory_module, "resolve_class", lambda path, base: CapturingModel)

    factory_module.create_chat_model(name="gpt-5-responses")

    assert captured.get("use_responses_api") is True
    assert captured.get("output_version") == "responses/v1"


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", ["mimo-v2.5-pro", "mimo-v2.5", "mimo-v2-flash"])
def test_create_chat_model_resolves_patched_mimo_provider(model_id):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from deerflow.models.patched_mimo import PatchedChatMiMo

    model = ModelConfig(
        name=f"{model_id}-thinking",
        display_name=f"{model_id} Thinking",
        description=None,
        use="deerflow.models.patched_mimo:PatchedChatMiMo",
        model=model_id,
        api_key="test-key",
        base_url="https://api.xiaomimimo.com/v1",
        supports_thinking=True,
        when_thinking_enabled={"extra_body": {"thinking": {"type": "enabled"}}},
        supports_vision=False,
    )
    cfg = _make_app_config([model])

    chat_model = factory_module.create_chat_model(
        name=f"{model_id}-thinking",
        thinking_enabled=True,
        app_config=cfg,
        attach_tracing=False,
    )

    assert isinstance(chat_model, PatchedChatMiMo)
    assert chat_model.model_name == model_id
    assert chat_model.extra_body["thinking"]["type"] == "enabled"


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


def test_no_duplicate_kwarg_when_reasoning_effort_in_config_and_thinking_disabled(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    wte = {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": 5000}}}
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    model = ModelConfig(
        name="doubao-model",
        display_name="Doubao 1.8",
        description=None,
        use="deerflow.models.patched_deepseek:PatchedChatDeepSeek",
        model="doubao-seed-1-8-250315",
        reasoning_effort="high",  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        supports_thinking=True,
        supports_reasoning_effort=True,
        when_thinking_enabled=wte,
        supports_vision=False,
    )
    cfg = _make_app_config([model])

    captured: dict = {}

    class CapturingModel(FakeChatModel):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            captured.update(kwargs)
            BaseChatModel.__init__(self, **kwargs)

    _patch_factory(monkeypatch, cfg, model_class=CapturingModel)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    factory_module.create_chat_model(name="doubao-model", thinking_enabled=False)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert captured.get("reasoning_effort") == "minimal"


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


def test_stream_chunk_timeout_defaults_to_240_for_openai_compatible_model(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain_openai import ChatOpenAI

    model = _make_model(use="langchain_openai:ChatOpenAI")
    cfg = _make_app_config([model])

    captured: dict = {}
    _patch_factory(monkeypatch, cfg, model_class=_capturing_class(ChatOpenAI, captured))
    factory_module.create_chat_model(name="test-model")

    assert captured.get("stream_chunk_timeout") == 240.0


def test_stream_chunk_timeout_user_value_not_overridden(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain_openai import ChatOpenAI

    model = ModelConfig(
        name="custom-timeout-model",
        display_name="Custom Timeout",
        description=None,
        use="langchain_openai:ChatOpenAI",
        model="gpt-4o-mini",
        stream_chunk_timeout=60.0,  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    )
    cfg = _make_app_config([model])

    captured: dict = {}
    _patch_factory(monkeypatch, cfg, model_class=_capturing_class(ChatOpenAI, captured))
    factory_module.create_chat_model(name="custom-timeout-model")

    assert captured.get("stream_chunk_timeout") == 60.0


def test_stream_chunk_timeout_not_injected_for_non_openai_provider(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain_anthropic import ChatAnthropic

    model = _make_model(use="langchain_anthropic:ChatAnthropic")
    cfg = _make_app_config([model])

    captured: dict = {}
    _patch_factory(monkeypatch, cfg, model_class=_capturing_class(ChatAnthropic, captured))
    factory_module.create_chat_model(name="test-model")

    assert "stream_chunk_timeout" not in captured


def test_stream_chunk_timeout_default_constant_is_documented():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    assert factory_module._DEFAULT_STREAM_CHUNK_TIMEOUT_SECONDS == 240.0


def test_stream_chunk_timeout_popped_for_non_openai_provider_when_user_set_it(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain_anthropic import ChatAnthropic

    model = ModelConfig(
        name="anthropic-with-stray-timeout",
        display_name="Anthropic With Stray Timeout",
        description=None,
        use="langchain_anthropic:ChatAnthropic",
        model="claude-sonnet-4",
        stream_chunk_timeout=60.0,  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    )
    cfg = _make_app_config([model])

    captured: dict = {}
    _patch_factory(monkeypatch, cfg, model_class=_capturing_class(ChatAnthropic, captured))
    factory_module.create_chat_model(name="anthropic-with-stray-timeout")

    assert "stream_chunk_timeout" not in captured


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------

# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
_STREAM_TIMEOUT_OPENAI_SUBCLASS_USE_PATHS = [
    "deerflow.models.vllm_provider:VllmChatModel",
    "deerflow.models.mindie_provider:MindIEChatModel",
    "deerflow.models.patched_deepseek:PatchedChatDeepSeek",
    "deerflow.models.patched_mimo:PatchedChatMiMo",
    "deerflow.models.patched_stepfun:PatchedChatStepFun",
    "deerflow.models.patched_minimax:PatchedChatMiniMax",
]


@pytest.mark.parametrize("use_path", _STREAM_TIMEOUT_OPENAI_SUBCLASS_USE_PATHS)
def test_stream_chunk_timeout_defaults_to_240_for_all_openai_subclasses(monkeypatch, use_path):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    real_cls = resolve_class(use_path, BaseChatModel)
    model = _make_model(use=use_path)
    cfg = _make_app_config([model])

    captured: dict = {}
    _patch_factory(monkeypatch, cfg, model_class=_capturing_class(real_cls, captured))
    factory_module.create_chat_model(name="test-model")

    assert captured.get("stream_chunk_timeout") == 240.0


@pytest.mark.parametrize("use_path", _STREAM_TIMEOUT_OPENAI_SUBCLASS_USE_PATHS)
def test_stream_chunk_timeout_user_override_honored_for_all_openai_subclasses(monkeypatch, use_path):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    real_cls = resolve_class(use_path, BaseChatModel)
    model = ModelConfig(
        name="override-model",
        display_name="Override",
        description=None,
        use=use_path,
        model="reasoning-model",
        stream_chunk_timeout=300.0,  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    )
    cfg = _make_app_config([model])

    captured: dict = {}
    _patch_factory(monkeypatch, cfg, model_class=_capturing_class(real_cls, captured))
    factory_module.create_chat_model(name="override-model")

    assert captured.get("stream_chunk_timeout") == 300.0


def test_stream_chunk_timeout_240_reaches_real_mimo_constructor(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    model = _make_model_with_extras(
        "mimo",
        use="deerflow.models.patched_mimo:PatchedChatMiMo",
        api_key="sk-dummy",
        base_url="http://localhost:8000/v1",
    )
    cfg = _make_app_config([model])
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    monkeypatch.setattr(factory_module, "get_app_config", lambda: cfg)
    monkeypatch.setattr(factory_module, "build_tracing_callbacks", lambda: [])

    instance = factory_module.create_chat_model(name="mimo")

    assert instance.stream_chunk_timeout == 240.0


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


def _make_model_with_extras(name="extra-model", *, use="langchain_openai:ChatOpenAI", **extras):
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    return ModelConfig(
        name=name,
        display_name=name,
        description=None,
        use=use,
        model=name,
        supports_thinking=False,
        supports_reasoning_effort=False,
        supports_vision=False,
        **extras,
    )


def test_api_base_normalized_to_base_url_for_chatopenai(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain_openai import ChatOpenAI

    cfg = _make_app_config([_make_model_with_extras("oai", api_base="http://localhost:4001/v1")])
    captured: dict = {}
    _patch_factory(monkeypatch, cfg, model_class=_capturing_class(ChatOpenAI, captured))

    factory_module.create_chat_model(name="oai")

    assert captured.get("base_url") == "http://localhost:4001/v1"
    assert "api_base" not in captured


def test_base_url_takes_precedence_when_both_set(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain_openai import ChatOpenAI

    cfg = _make_app_config([_make_model_with_extras("oai", base_url="http://canonical/v1", api_base="http://alias/v1")])
    captured: dict = {}
    _patch_factory(monkeypatch, cfg, model_class=_capturing_class(ChatOpenAI, captured))

    factory_module.create_chat_model(name="oai")

    assert captured.get("base_url") == "http://canonical/v1"
    assert "api_base" not in captured


def test_api_base_preserved_for_provider_that_declares_it(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from deerflow.models.patched_deepseek import PatchedChatDeepSeek

    cfg = _make_app_config([_make_model_with_extras("ds", use="deerflow.models.patched_deepseek:PatchedChatDeepSeek", api_base="http://ds/v3")])
    captured: dict = {}
    _patch_factory(monkeypatch, cfg, model_class=_capturing_class(PatchedChatDeepSeek, captured))

    factory_module.create_chat_model(name="ds")

    assert captured.get("api_base") == "http://ds/v3"
    assert "base_url" not in captured


def test_no_op_when_neither_base_url_nor_api_base(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    cfg = _make_app_config([_make_model("plain")])
    _patch_factory(monkeypatch, cfg)

    FakeChatModel.captured_kwargs = {}
    factory_module.create_chat_model(name="plain")

    assert "base_url" not in FakeChatModel.captured_kwargs
    assert "api_base" not in FakeChatModel.captured_kwargs


def test_unknown_config_key_emits_warning(monkeypatch, caplog):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    import logging

    from langchain_openai import ChatOpenAI

    cfg = _make_app_config([_make_model_with_extras("typo", api_key="sk-test", definitely_not_a_real_kwarg=True)])
    _patch_factory(monkeypatch, cfg, model_class=ChatOpenAI)

    with caplog.at_level(logging.WARNING, logger=factory_module.__name__):
        factory_module.create_chat_model(name="typo")

    assert any("definitely_not_a_real_kwarg" in rec.message for rec in caplog.records)


def test_known_config_keys_emit_no_warning(monkeypatch, caplog):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    import logging

    from langchain_openai import ChatOpenAI

    cfg = _make_app_config([_make_model_with_extras("clean", api_key="sk-test", base_url="http://ok/v1", max_tokens=100)])
    _patch_factory(monkeypatch, cfg, model_class=ChatOpenAI)

    with caplog.at_level(logging.WARNING, logger=factory_module.__name__):
        factory_module.create_chat_model(name="clean")

    assert not any("not recognized parameters" in rec.message for rec in caplog.records)


def test_api_base_normalized_for_patched_chatopenai(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from deerflow.models.patched_openai import PatchedChatOpenAI

    cfg = _make_app_config([_make_model_with_extras("patched", use="deerflow.models.patched_openai:PatchedChatOpenAI", api_base="http://localhost:4001/v1")])
    captured: dict = {}
    _patch_factory(monkeypatch, cfg, model_class=_capturing_class(PatchedChatOpenAI, captured))

    factory_module.create_chat_model(name="patched")

    assert captured.get("base_url") == "http://localhost:4001/v1"
    assert "api_base" not in captured


def test_api_base_dropped_when_openai_api_base_field_name_set(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain_openai import ChatOpenAI

    cfg = _make_app_config([_make_model_with_extras("oai", openai_api_base="http://canonical/v1", api_base="http://alias/v1")])
    captured: dict = {}
    _patch_factory(monkeypatch, cfg, model_class=_capturing_class(ChatOpenAI, captured))

    factory_module.create_chat_model(name="oai")

    assert captured.get("openai_api_base") == "http://canonical/v1"
    assert "api_base" not in captured
    assert "base_url" not in captured


def test_no_unknown_key_warning_for_non_openai_class(monkeypatch, caplog):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    import logging

    from langchain_anthropic import ChatAnthropic

    cfg = _make_app_config([_make_model_with_extras("anthropic", use="langchain_anthropic:ChatAnthropic", frequency_penalty=0.5, api_base="http://x/v1")])
    captured: dict = {}
    _patch_factory(monkeypatch, cfg, model_class=_capturing_class(ChatAnthropic, captured))

    with caplog.at_level(logging.WARNING, logger=factory_module.__name__):
        factory_module.create_chat_model(name="anthropic")

    assert not any("not recognized parameters" in rec.message for rec in caplog.records)
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert captured.get("api_base") == "http://x/v1"
    assert "base_url" not in captured


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------

# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
_OPENAI_SUBCLASS_USE_PATHS_WITHOUT_API_BASE = [
    "deerflow.models.vllm_provider:VllmChatModel",
    "deerflow.models.mindie_provider:MindIEChatModel",
    "deerflow.models.patched_mimo:PatchedChatMiMo",
    "deerflow.models.patched_stepfun:PatchedChatStepFun",
    "deerflow.models.patched_minimax:PatchedChatMiniMax",
]


@pytest.mark.parametrize("use_path", _OPENAI_SUBCLASS_USE_PATHS_WITHOUT_API_BASE)
def test_api_base_normalized_for_all_openai_subclasses(monkeypatch, use_path):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    real_cls = resolve_class(use_path, BaseChatModel)
    cfg = _make_app_config([_make_model_with_extras("m", use=use_path, api_base="http://gw.example/v1")])
    captured: dict = {}
    _patch_factory(monkeypatch, cfg, model_class=_capturing_class(real_cls, captured))

    factory_module.create_chat_model(name="m")

    assert captured.get("base_url") == "http://gw.example/v1"
    assert "api_base" not in captured


@pytest.mark.parametrize("use_path", _OPENAI_SUBCLASS_USE_PATHS_WITHOUT_API_BASE)
def test_unknown_config_key_warns_for_all_openai_subclasses(monkeypatch, use_path, caplog):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    import logging

    real_cls = resolve_class(use_path, BaseChatModel)
    cfg = _make_app_config([_make_model_with_extras("m", use=use_path, definitely_not_a_real_kwarg=True)])
    captured: dict = {}
    _patch_factory(monkeypatch, cfg, model_class=_capturing_class(real_cls, captured))

    with caplog.at_level(logging.WARNING, logger=factory_module.__name__):
        factory_module.create_chat_model(name="m")

    assert any("definitely_not_a_real_kwarg" in rec.message for rec in caplog.records)


def test_api_base_reaches_real_minimax_constructor_as_base_url(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    cfg = _make_app_config(
        [
            _make_model_with_extras(
                "minimax",
                use="deerflow.models.patched_minimax:PatchedChatMiniMax",
                api_key="sk-dummy",
                api_base="https://api.minimax.io/v1",
            )
        ]
    )
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    monkeypatch.setattr(factory_module, "get_app_config", lambda: cfg)
    monkeypatch.setattr(factory_module, "build_tracing_callbacks", lambda: [])

    instance = factory_module.create_chat_model(name="minimax")

    assert instance.openai_api_base == "https://api.minimax.io/v1"
    assert "api_base" not in (instance.model_kwargs or {})
