"""提供模型列表与模型详情的只读 FastAPI 路由。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.gateway.deps import get_config
from deerflow.config.app_config import AppConfig

router = APIRouter(prefix="/api", tags=["models"])


class ModelResponse(BaseModel):
    '封装 ModelResponse 的状态、协作关系与公开操作。\n\nResponse model for model information.'

    name: str = Field(..., description="Unique identifier for the model")
    model: str = Field(..., description="Actual provider model identifier")
    display_name: str | None = Field(None, description="Human-readable name")
    description: str | None = Field(None, description="Model description")
    supports_thinking: bool = Field(default=False, description="Whether model supports thinking mode")
    supports_reasoning_effort: bool = Field(default=False, description="Whether model supports reasoning effort")


class TokenUsageResponse(BaseModel):
    '封装 TokenUsageResponse 的状态、协作关系与公开操作。\n\nToken usage display configuration.'

    enabled: bool = Field(default=False, description="Whether token usage display is enabled")


class ModelsListResponse(BaseModel):
    '封装 ModelsListResponse 的状态、协作关系与公开操作。\n\nResponse model for listing all models.'

    models: list[ModelResponse]
    token_usage: TokenUsageResponse


@router.get(
    "/models",
    response_model=ModelsListResponse,
    summary="List All Models",
    description="Retrieve a list of all available AI models configured in the system.",
)
async def list_models(config: AppConfig = Depends(get_config)) -> ModelsListResponse:
    '收集并返回，并遵守 list_models 所表达的接口约束。\n\nList all available models from configuration.\n\n    Returns model information suitable for frontend display,\n    excluding sensitive fields like API keys and internal configuration.\n\n    Returns:\n        A list of all configured models with their metadata and token usage display settings.\n\n    Example Response:\n        ```json\n        {\n            "models": [\n                {\n                    "name": "gpt-4",\n                    "model": "gpt-4",\n                    "display_name": "GPT-4",\n                    "description": "OpenAI GPT-4 model",\n                    "supports_thinking": false,\n                    "supports_reasoning_effort": false\n                },\n                {\n                    "name": "claude-3-opus",\n                    "model": "claude-3-opus",\n                    "display_name": "Claude 3 Opus",\n                    "description": "Anthropic Claude 3 Opus model",\n                    "supports_thinking": true,\n                    "supports_reasoning_effort": false\n                }\n            ],\n            "token_usage": {\n                "enabled": true\n            }\n        }\n        ```\n    '
    models = [
        ModelResponse(
            name=model.name,
            model=model.model,
            display_name=model.display_name,
            description=model.description,
            supports_thinking=model.supports_thinking,
            supports_reasoning_effort=model.supports_reasoning_effort,
        )
        for model in config.models
    ]
    return ModelsListResponse(
        models=models,
        token_usage=TokenUsageResponse(enabled=config.token_usage.enabled),
    )


@router.get(
    "/models/{model_name}",
    response_model=ModelResponse,
    summary="Get Model Details",
    description="Retrieve detailed information about a specific AI model by its name.",
)
async def get_model(model_name: str, config: AppConfig = Depends(get_config)) -> ModelResponse:
    '读取并返回，并遵守 get_model 所表达的接口约束。\n\nGet a specific model by name.\n\n    Args:\n        model_name: The unique name of the model to retrieve.\n\n    Returns:\n        Model information if found.\n\n    Raises:\n        HTTPException: 404 if model not found.\n\n    Example Response:\n        ```json\n        {\n            "name": "gpt-4",\n            "display_name": "GPT-4",\n            "description": "OpenAI GPT-4 model",\n            "supports_thinking": false\n        }\n        ```\n    '
    model = config.get_model_config(model_name)
    if model is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")

    return ModelResponse(
        name=model.name,
        model=model.model,
        display_name=model.display_name,
        description=model.description,
        supports_thinking=model.supports_thinking,
        supports_reasoning_effort=model.supports_reasoning_effort,
    )
