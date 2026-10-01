'''根据记忆后端的模型配置创建事实抽取模型；配置无效时禁用抽取但保留非模型操作。'''

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..config import DeerMemModelConfig

logger = logging.getLogger(__name__)


def build_llm(model_config: DeerMemModelConfig | None) -> Any:
    '''按供应商、模型名称和可选凭据参数初始化聊天模型；失败时记录警告并返回 None。'''
    if model_config is None or not model_config.model:
        return None
    from langchain.chat_models import init_chat_model

    kwargs: dict[str, Any] = {}
    if model_config.api_key is not None:
        kwargs["api_key"] = model_config.api_key
    if model_config.base_url is not None:
        kwargs["base_url"] = model_config.base_url
    if model_config.temperature is not None:
        kwargs["temperature"] = model_config.temperature
    try:
        return init_chat_model(
            model=model_config.model,
            model_provider=model_config.provider or "openai",
            **kwargs,
        )
    except Exception as e:  # noqa: BLE001 - degrade like _host_default_llm (don't crash startup)
        logger.warning(
            "build_llm failed for model=%r (provider=%r): %s; memory extraction disabled (non-LLM ops still work; an update will raise).",
            model_config.model,
            model_config.provider or "openai",
            e,
        )
        return None
