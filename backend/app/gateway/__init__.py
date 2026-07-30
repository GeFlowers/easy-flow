"""网关包的延迟导出入口，避免导入时启动应用副作用。"""

from .config import GatewayConfig, get_gateway_config

__all__ = ["app", "create_app", "GatewayConfig", "get_gateway_config"]


def __getattr__(name: str):
    """按需导入应用对象及工厂，维持轻量包级导入。"""
    if name in {"app", "create_app"}:
        from .app import app, create_app

        return app if name == "app" else create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
