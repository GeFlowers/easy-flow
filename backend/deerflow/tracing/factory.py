'''按已启用的供应商创建每次智能体运行需要的追踪回调。'''

from __future__ import annotations

from typing import Any

from deerflow.config import (
    get_enabled_tracing_providers,
    get_tracing_config,
    validate_enabled_tracing_providers,
)


def build_tracing_callbacks() -> list[Any]:
    '''先验证配置，再创建已启用的追踪回调。'''
    validate_enabled_tracing_providers()
    enabled_providers = get_enabled_tracing_providers()
    if not enabled_providers:
        return []

    tracing_config = get_tracing_config()
    callbacks: list[Any] = []

    for provider in enabled_providers:
        if provider == "langfuse":
            try:
                callbacks.append(_create_langfuse_handler(tracing_config.langfuse))
            except Exception as exc:  # pragma: no cover  # 测试通过替换外部追踪组件触发此分支。
                raise RuntimeError(f"Langfuse tracing initialization failed: {exc}") from exc

    return callbacks


def _create_langfuse_handler(config) -> Any:
    '''先初始化 Langfuse 客户端凭据，再创建供模型调用使用的回调处理器。'''
    from langfuse import Langfuse
    from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler

    # Langfuse 4 及以上版本从客户端单例读取项目凭据；回调随后复用此客户端。
    Langfuse(
        secret_key=config.secret_key,
        public_key=config.public_key,
        host=config.host,
    )
    return LangfuseCallbackHandler(public_key=config.public_key)
