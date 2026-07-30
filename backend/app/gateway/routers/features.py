'定义 features 模块提供的职责与可复用接口。\n\nRead-only feature-flag endpoint for the frontend bootstrap.\n\nReports which optional, config-gated features are exposed over HTTP so the\nfrontend can gate UI and avoid firing requests that the backend would reject\nwith 403. Reads through ``get_config`` so edits to ``config.yaml`` take effect\non the next request without a restart (config hot-reload boundary).\n'

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.gateway.deps import get_config
from deerflow.config.app_config import AppConfig

router = APIRouter(prefix="/api", tags=["features"])


class AgentsApiFeature(BaseModel):
    '封装 AgentsApiFeature 的状态、协作关系与公开操作。\n\nAvailability of the custom-agent management API.'

    enabled: bool = Field(..., description="Whether the agents_api routes are exposed over HTTP")


class FeaturesResponse(BaseModel):
    '封装 FeaturesResponse 的状态、协作关系与公开操作。\n\nFrontend-facing feature availability flags.'

    agents_api: AgentsApiFeature


@router.get(
    "/features",
    response_model=FeaturesResponse,
    summary="List Feature Flags",
    description="Report which optional config-gated features are enabled, so the frontend can gate UI before issuing requests.",
)
async def list_features(config: AppConfig = Depends(get_config)) -> FeaturesResponse:
    '收集并返回，并遵守 list_features 所表达的接口约束。\n\nReturn availability of optional, config-gated frontend features.'
    return FeaturesResponse(
        agents_api=AgentsApiFeature(enabled=config.agents_api.enabled),
    )
