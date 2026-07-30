"""提供配置、safety、finish、reason、配置相关功能。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SafetyDetectorConfig(BaseModel):
    """\u6267\u884c SafetyDetectorConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    use: str = Field(
        description=("Class path of a SafetyTerminationDetector implementation (e.g. 'deerflow.agents.middlewares.safety_termination_detectors:OpenAICompatibleContentFilterDetector')."),
    )
    config: dict = Field(
        default_factory=dict,
        description="Constructor kwargs passed to the detector class.",
    )


class SafetyFinishReasonConfig(BaseModel):
    """\u6267\u884c SafetyFinishReasonConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    enabled: bool = Field(
        default=True,
        description="Master switch for the SafetyFinishReasonMiddleware.",
    )
    detectors: list[SafetyDetectorConfig] | None = Field(
        default=None,
        description=(
            "Custom detector list. Leave unset (None) to use the built-in "
            "set covering OpenAI-compatible content_filter, Anthropic "
            "refusal, and Gemini SAFETY/BLOCKLIST/PROHIBITED_CONTENT/SPII/"
            "RECITATION. Provide a non-null list to fully override."
        ),
    )
