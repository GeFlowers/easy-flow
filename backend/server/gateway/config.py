'''定义网关进程监听配置及其惰性环境变量读取逻辑。'''

import os

from pydantic import BaseModel, Field


class GatewayConfig(BaseModel):
    '''描述网关监听地址、端口及接口文档开关的进程配置。'''

    host: str = Field(default="0.0.0.0", description="Host to bind the gateway server")
    port: int = Field(default=8001, description="Port to bind the gateway server")
    enable_docs: bool = Field(default=True, description="Enable Swagger/ReDoc/OpenAPI endpoints")


_gateway_config: GatewayConfig | None = None


def get_gateway_config() -> GatewayConfig:
    '''返回进程内缓存的网关配置，首次访问时从环境变量构造。'''
    global _gateway_config
    if _gateway_config is None:
        _gateway_config = GatewayConfig(
            host=os.getenv("GATEWAY_HOST", "0.0.0.0"),
            port=int(os.getenv("GATEWAY_PORT", "8001")),
            enable_docs=os.getenv("GATEWAY_ENABLE_DOCS", "true").lower() == "true",
        )
    return _gateway_config
