'''配置模型终止原因的安全检测和工具循环终止保护。'''

from __future__ import annotations

from pydantic import BaseModel, Field


class SafetyDetectorConfig(BaseModel):
    '''定义单个终止原因检测器的启用状态与判定参数。'''

    use: str = Field(
        description=("Class path of a SafetyTerminationDetector implementation (e.g. 'deerflow.agents.middlewares.safety_termination_detectors:OpenAICompatibleContentFilterDetector')."),
    )
    config: dict = Field(
        default_factory=dict,
        description="Constructor kwargs passed to the detector class.",
    )


class SafetyFinishReasonConfig(BaseModel):
    '''汇总运行结束原因检查及不安全工具循环的兜底行为。'''

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
