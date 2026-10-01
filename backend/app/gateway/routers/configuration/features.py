'''向前端报告当前配置启用的可选 API 功能。'''

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.gateway.deps import get_config
from deerflow.config.app_config import AppConfig

router = APIRouter(prefix="/api", tags=["features"])


class AgentsApiFeature(BaseModel):
    '''表示自定义 Agent 管理接口是否开放。'''

    enabled: bool = Field(..., description="Whether the agents_api routes are exposed over HTTP")


class FeaturesResponse(BaseModel):
    '''封装前端据以显示或隐藏功能的可用性标志。'''

    agents_api: AgentsApiFeature


@router.get(
    "/features",
    response_model=FeaturesResponse,
    summary="List Feature Flags",
    description="Report which optional config-gated features are enabled, so the frontend can gate UI before issuing requests.",
)
async def list_features(config: AppConfig = Depends(get_config)) -> FeaturesResponse:
    '''返回配置中受开关控制的 API 功能状态，供前端启动时调整界面。'''
    return FeaturesResponse(
        agents_api=AgentsApiFeature(enabled=config.agents_api.enabled),
    )
