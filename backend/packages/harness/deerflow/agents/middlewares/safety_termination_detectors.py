'定义 safety_termination_detectors 模块提供的职责与可复用接口。\n\nDetectors for provider-side safety termination signals.\n\nDifferent LLM providers signal "I stopped this response for safety reasons"\nthrough different fields with different values. This module defines a small\nstrategy interface and three built-in detectors that cover the major\nproviders DeerFlow supports today. New providers (Wenxin, Hunyuan, Bedrock\nadapters, in-house gateways, ...) can be added by implementing\n``SafetyTerminationDetector`` and wiring it through\n``config.yaml: safety_finish_reason.detectors``.\n\nThe middleware that consumes these detectors lives in\n``safety_finish_reason_middleware.py``.\n'

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from langchain_core.messages import AIMessage


@dataclass(frozen=True)
class SafetyTermination:
    '封装 SafetyTermination 的状态、协作关系与公开操作。\n\nA detected safety-related termination signal.\n\n    Attributes:\n        detector: Name of the detector that produced this result. Used for\n            observability so operators can see which provider rule fired.\n        reason_field: The message metadata field that carried the signal\n            (e.g. ``finish_reason``, ``stop_reason``).\n        reason_value: The actual value of that field\n            (e.g. ``content_filter``, ``refusal``, ``SAFETY``).\n        extras: Provider-specific metadata that may help downstream\n            consumers (e.g. Azure OpenAI content_filter_results, Gemini\n            safety_ratings). Detectors are free to populate or skip this.\n    '

    detector: str
    reason_field: str
    reason_value: str
    extras: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SafetyTerminationDetector(Protocol):
    '封装 SafetyTerminationDetector 的状态、协作关系与公开操作。\n\nStrategy interface for provider safety termination detection.'

    name: str

    def detect(self, message: AIMessage) -> SafetyTermination | None:
        '执行 detect 的明确职责，并返回与调用约定一致的结果。\n\nReturn a SafetyTermination if *message* indicates provider safety\n        termination, otherwise return ``None``.\n\n        Implementations must be side-effect free and tolerant of missing or\n        oddly-typed metadata — detectors run on every model response.\n        '
        ...


def _get_metadata_value(message: AIMessage, field_name: str) -> str | None:
    '执行 _get_metadata_value 的明确职责，并返回与调用约定一致的结果。\n\nRead a string-typed value from either ``response_metadata`` or\n    ``additional_kwargs``.\n\n    LangChain provider adapters are inconsistent about where they stash\n    provider stop signals. Most modern adapters use ``response_metadata``,\n    but some legacy / passthrough paths still surface them via\n    ``additional_kwargs``. We check both, in that order, and only accept\n    string values — Pydantic enums or dicts are ignored so we never raise\n    on malformed inputs.\n    '
    for container_name in ("response_metadata", "additional_kwargs"):
        container = getattr(message, container_name, None) or {}
        if not isinstance(container, dict):
            continue
        value = container.get(field_name)
        if isinstance(value, str) and value:
            return value
    return None


class OpenAICompatibleContentFilterDetector:
    '封装 OpenAICompatibleContentFilterDetector 的状态、协作关系与公开操作。\n\nOpenAI-compatible content_filter signal.\n\n    Covers OpenAI, Azure OpenAI, Moonshot/Kimi, DeepSeek, Mistral, vLLM,\n    Qwen (OpenAI-compatible mode), and any other adapter that follows the\n    OpenAI ``finish_reason`` convention.\n\n    Some Chinese providers ship custom OpenAI-compatible gateways that use\n    alternative tokens like ``sensitive`` or ``violation``. Extend the set\n    via the ``finish_reasons`` kwarg in config.\n    '

    name = "openai_compatible_content_filter"

    def __init__(self, finish_reasons: list[str] | tuple[str, ...] | None = None) -> None:
        '实现 __init__ 协议方法，保持对象交互语义一致'
        configured = finish_reasons if finish_reasons is not None else ("content_filter",)
        self._finish_reasons: frozenset[str] = frozenset(r.lower() for r in configured)

    def detect(self, message: AIMessage) -> SafetyTermination | None:
        '执行 detect 的明确职责，并返回与调用约定一致的结果'
        value = _get_metadata_value(message, "finish_reason")
        if value is None or value.lower() not in self._finish_reasons:
            return None

        extras: dict[str, Any] = {}
        # Azure OpenAI ships a structured content_filter_results block; carry it
        # through so operators can see *what* was filtered without re-tracing.
        response_metadata = getattr(message, "response_metadata", None) or {}
        if isinstance(response_metadata, dict):
            filter_results = response_metadata.get("content_filter_results")
            if filter_results:
                extras["content_filter_results"] = filter_results

        return SafetyTermination(
            detector=self.name,
            reason_field="finish_reason",
            reason_value=value,
            extras=extras,
        )


class AnthropicRefusalDetector:
    '封装 AnthropicRefusalDetector 的状态、协作关系与公开操作。\n\nAnthropic ``stop_reason == "refusal"`` signal.\n\n    Anthropic models surface safety refusals via a dedicated ``stop_reason``\n    rather than ``finish_reason``. See:\n    https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/handle-streaming-refusals\n    '

    name = "anthropic_refusal"

    def __init__(self, stop_reasons: list[str] | tuple[str, ...] | None = None) -> None:
        '实现 __init__ 协议方法，保持对象交互语义一致'
        configured = stop_reasons if stop_reasons is not None else ("refusal",)
        self._stop_reasons: frozenset[str] = frozenset(r.lower() for r in configured)

    def detect(self, message: AIMessage) -> SafetyTermination | None:
        '执行 detect 的明确职责，并返回与调用约定一致的结果'
        value = _get_metadata_value(message, "stop_reason")
        if value is None or value.lower() not in self._stop_reasons:
            return None
        return SafetyTermination(
            detector=self.name,
            reason_field="stop_reason",
            reason_value=value,
        )


class GeminiSafetyDetector:
    '封装 GeminiSafetyDetector 的状态、协作关系与公开操作。\n\nGemini / Vertex AI safety-related finish reasons.\n\n    Gemini uses the same ``finish_reason`` field as OpenAI but with an\n    enumerated upper-case taxonomy. The default set covers every Gemini\n    finish_reason that means "the model stopped because the content/image\n    tripped a safety, blocklist, recitation, or PII filter" — i.e. cases\n    where any tool_calls returned alongside are likely truncated/\n    unreliable. Full enum:\n    https://docs.cloud.google.com/python/docs/reference/aiplatform/latest/google.cloud.aiplatform_v1.types.Candidate.FinishReason\n\n    Intentionally **excluded** from the default set:\n    - ``STOP``                       — normal termination.\n    - ``MAX_TOKENS``                 — output length truncation, not safety\n                                       (same root failure mode as\n                                       content_filter, but issue #3028\n                                       scopes it out; expose separately if\n                                       desired).\n    - ``LANGUAGE`` / ``NO_IMAGE``    — capability mismatches, unrelated to\n                                       safety; tool_calls would be absent\n                                       anyway.\n    - ``MALFORMED_FUNCTION_CALL`` /\n      ``UNEXPECTED_TOOL_CALL``       — tool-call protocol errors. The\n                                       tool_calls are *also* unreliable\n                                       here, but the failure category is\n                                       distinct from safety filtering;\n                                       handle in a dedicated detector to\n                                       keep observability records honest.\n    - ``OTHER`` / ``IMAGE_OTHER`` /\n      ``FINISH_REASON_UNSPECIFIED``  — too broad to enable by default;\n                                       opt in via ``finish_reasons=`` if\n                                       your provider abuses these.\n    '

    name = "gemini_safety"

    _DEFAULT_FINISH_REASONS = (
        # Text safety
        "SAFETY",
        "BLOCKLIST",
        "PROHIBITED_CONTENT",
        "SPII",
        "RECITATION",
        # Image safety (multimodal generation)
        "IMAGE_SAFETY",
        "IMAGE_PROHIBITED_CONTENT",
        "IMAGE_RECITATION",
    )

    def __init__(self, finish_reasons: list[str] | tuple[str, ...] | None = None) -> None:
        '实现 __init__ 协议方法，保持对象交互语义一致'
        configured = finish_reasons if finish_reasons is not None else self._DEFAULT_FINISH_REASONS
        self._finish_reasons: frozenset[str] = frozenset(r.upper() for r in configured)

    def detect(self, message: AIMessage) -> SafetyTermination | None:
        '执行 detect 的明确职责，并返回与调用约定一致的结果'
        value = _get_metadata_value(message, "finish_reason")
        if value is None or value.upper() not in self._finish_reasons:
            return None

        extras: dict[str, Any] = {}
        response_metadata = getattr(message, "response_metadata", None) or {}
        if isinstance(response_metadata, dict):
            # Gemini surfaces per-category scoring under safety_ratings.
            ratings = response_metadata.get("safety_ratings")
            if ratings:
                extras["safety_ratings"] = ratings

        return SafetyTermination(
            detector=self.name,
            reason_field="finish_reason",
            reason_value=value,
            extras=extras,
        )


def default_detectors() -> list[SafetyTerminationDetector]:
    '执行 default_detectors 的明确职责，并返回与调用约定一致的结果。\n\nBuilt-in detector set used when no custom detectors are configured.'
    return [
        OpenAICompatibleContentFilterDetector(),
        AnthropicRefusalDetector(),
        GeminiSafetyDetector(),
    ]


__all__ = [
    "AnthropicRefusalDetector",
    "GeminiSafetyDetector",
    "OpenAICompatibleContentFilterDetector",
    "SafetyTermination",
    "SafetyTerminationDetector",
    "default_detectors",
]
