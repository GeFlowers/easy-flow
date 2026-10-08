'''按已启用的供应商创建每次智能体运行需要的追踪回调。'''

from __future__ import annotations

import logging
from typing import Any

from deerflow.config import (
    get_enabled_tracing_providers,
    get_tracing_config,
    is_monocle_tracing_enabled,
    validate_enabled_tracing_providers,
)
from deerflow.tracing.monocle import is_monocle_setup_completed

logger = logging.getLogger(__name__)


def _create_langsmith_tracer(config) -> Any:
    '''为 LangSmith 创建绑定到当前项目名称的 LangChain 追踪器。'''
    from langchain_core.tracers.langchain import LangChainTracer

    return LangChainTracer(project_name=config.project)


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


def build_tracing_callbacks() -> list[Any]:
    '''先验证配置，再创建已启用的回调；Monocle 则由应用生命周期单独初始化。'''
    validate_enabled_tracing_providers()
    # Monocle 在进程级初始化；此处仅提醒跳过网关生命周期的嵌入式调用方。
    if is_monocle_tracing_enabled() and not is_monocle_setup_completed():
        logger.debug(
            "MONOCLE_TRACING is set but Monocle is not initialized in this process — only the Gateway lifespan runs setup automatically; embedded callers must call deerflow.tracing.setup_monocle_tracing_if_enabled() themselves."
        )
    enabled_providers = get_enabled_tracing_providers()
    if not enabled_providers:
        return []

    tracing_config = get_tracing_config()
    callbacks: list[Any] = []

    for provider in enabled_providers:
        if provider == "langsmith":
            try:
                callbacks.append(_create_langsmith_tracer(tracing_config.langsmith))
            except Exception as exc:  # pragma: no cover  # 测试通过替换外部追踪组件触发此分支。
                raise RuntimeError(f"LangSmith tracing initialization failed: {exc}") from exc
        elif provider == "langfuse":
            try:
                callbacks.append(_create_langfuse_handler(tracing_config.langfuse))
            except Exception as exc:  # pragma: no cover  # 测试通过替换外部追踪组件触发此分支。
                raise RuntimeError(f"Langfuse tracing initialization failed: {exc}") from exc

    return callbacks
