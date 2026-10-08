'''统一识别不同模型供应方在回复元数据中标记的内容安全终止信号。'''

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from langchain_core.messages import AIMessage


@dataclass(frozen=True)
class SafetyTermination:
    '''保存触发检测器、承载信号的元数据字段和值，以及可选供应方详情。'''

    detector: str
    reason_field: str
    reason_value: str
    extras: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SafetyTerminationDetector(Protocol):
    '''安全终止检测器需实现的只读策略接口。'''

    name: str

    def detect(self, message: AIMessage) -> SafetyTermination | None:
        '''若模型消息包含该检测器负责识别的安全终止信号则返回结构化结果。'''
        ...


def _get_metadata_value(message: AIMessage, field_name: str) -> str | None:
    '''依次从响应元数据和扩展字段读取指定字符串值，忽略缺失或类型不符的数据。'''
    for container_name in ("response_metadata", "additional_kwargs"):
        container = getattr(message, container_name, None) or {}
        if not isinstance(container, dict):
            continue
        value = container.get(field_name)
        if isinstance(value, str) and value:
            return value
    return None


class OpenAICompatibleContentFilterDetector:
    '''识别使用 OpenAI 兼容协议的模型在 finish_reason 字段中返回的内容过滤标记。'''

    name = "openai_compatible_content_filter"

    def __init__(self, finish_reasons: list[str] | tuple[str, ...] | None = None) -> None:
        '''保存允许视为内容过滤的结束原因；未配置时只匹配 content_filter。'''
        configured = finish_reasons if finish_reasons is not None else ("content_filter",)
        self._finish_reasons: frozenset[str] = frozenset(r.lower() for r in configured)

    def detect(self, message: AIMessage) -> SafetyTermination | None:
        '''检查结束原因是否命中配置，并附带存在的供应方内容过滤详情。'''
        value = _get_metadata_value(message, "finish_reason")
        if value is None or value.lower() not in self._finish_reasons:
            return None

        extras: dict[str, Any] = {}
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
    '''识别 Anthropic 回复中 stop_reason 字段标记的拒绝结果。'''

    name = "anthropic_refusal"

    def __init__(self, stop_reasons: list[str] | tuple[str, ...] | None = None) -> None:
        '''保存拒绝类结束原因；默认仅匹配 refusal。'''
        configured = stop_reasons if stop_reasons is not None else ("refusal",)
        self._stop_reasons: frozenset[str] = frozenset(r.lower() for r in configured)

    def detect(self, message: AIMessage) -> SafetyTermination | None:
        '''匹配 stop_reason 配置值，命中时返回 Anthropic 拒绝信号。'''
        value = _get_metadata_value(message, "stop_reason")
        if value is None or value.lower() not in self._stop_reasons:
            return None
        return SafetyTermination(
            detector=self.name,
            reason_field="stop_reason",
            reason_value=value,
        )


class GeminiSafetyDetector:
    '''识别 Gemini 和 Vertex AI 的安全、屏蔽、隐私及图像安全结束原因。

    Gemini / Vertex AI 的安全类结束原因。

        Gemini 与 OpenAI 使用相同的 ``finish_reason`` 字段，但采用大写枚举分类。
        默认集合覆盖因内容或图像触发安全、屏蔽名单、复述或个人身份信息过滤而
        停止生成的 Gemini 结束原因；这些情况下同时返回的 tool_calls 可能已被
        截断或不可靠。完整枚举参见：
        https://docs.cloud.google.com/python/docs/reference/aiplatform/latest/google.cloud.aiplatform_v1.types.Candidate.FinishReason

        默认集合有意排除以下类别：
        - ``STOP``                       — 正常结束。
        - ``MAX_TOKENS``                 — 输出长度截断，而非安全过滤；
                                           根本失效模式与 content_filter 相同，
                                           但问题 #3028 将其排除在范围外，
                                           如有需要可单独暴露。
        - ``LANGUAGE`` / ``NO_IMAGE``    — 能力不匹配，与安全无关，
                                           通常也不会包含 tool_calls。
        - ``MALFORMED_FUNCTION_CALL`` /
          ``UNEXPECTED_TOOL_CALL``       — 工具调用协议错误；此时 tool_calls
                                           同样不可靠，但失效类别不同于安全过滤，
                                           应使用专门检测器处理，以准确记录观测结果。
        - ``OTHER`` / ``IMAGE_OTHER`` /
          ``FINISH_REASON_UNSPECIFIED``  — 含义过宽，不适合默认启用；
                                           若供应方将其用于安全过滤，
                                           可通过 ``finish_reasons=`` 显式启用。
    '''

    name = "gemini_safety"

    _DEFAULT_FINISH_REASONS = (
        "SAFETY",
        "BLOCKLIST",
        "PROHIBITED_CONTENT",
        "SPII",
        "RECITATION",
        "IMAGE_SAFETY",
        "IMAGE_PROHIBITED_CONTENT",
        "IMAGE_RECITATION",
    )

    def __init__(self, finish_reasons: list[str] | tuple[str, ...] | None = None) -> None:
        '''保存需识别的结束原因；未配置时采用内置的文本及图像安全类别。'''
        configured = finish_reasons if finish_reasons is not None else self._DEFAULT_FINISH_REASONS
        self._finish_reasons: frozenset[str] = frozenset(r.upper() for r in configured)

    def detect(self, message: AIMessage) -> SafetyTermination | None:
        '''比对大写结束原因，并在命中时附带模型返回的安全评分详情。'''
        value = _get_metadata_value(message, "finish_reason")
        if value is None or value.upper() not in self._finish_reasons:
            return None

        extras: dict[str, Any] = {}
        response_metadata = getattr(message, "response_metadata", None) or {}
        if isinstance(response_metadata, dict):
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
    '''创建兼容 OpenAI 协议、Anthropic 拒绝及 Gemini 安全信号的默认检测器集合。'''
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
