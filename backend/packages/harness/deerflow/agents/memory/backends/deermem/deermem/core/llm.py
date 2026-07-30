"定义 llm 模块提供的职责与可复用接口。\n\nDeerMem's own LLM construction (no deer-flow ``create_chat_model``).\n\n``build_llm(model_config)`` builds a langchain ``ChatModel`` from DeerMem's\nmodel sub-config (provider/model/api_key/base_url/temperature) via\n``langchain.chat_models.init_chat_model``. DeerMem owns the resulting instance\n(``self._llm``) and injects it into ``MemoryUpdater`` (dependency injection).\n\n``DeerMem.__init__`` prefers a host-injected ``host_llm`` (the deer-flow\nfactory injects the app default model there when ``model`` is empty, mirroring\npre-abstraction ``model_name: null``); this ``build_llm`` is the fallback that\nbuilds from the ``model`` sub-config. Returns ``None`` when ``model`` is empty\n- standalone DeerMem then has no LLM (non-LLM ops still work; an update\nraises), but via the factory ``host_llm`` covers the zero-config case. Any\nprovider langchain's ``init_chat_model`` supports works (OpenAI, Anthropic,\nOpenAI-compatible gateways like DeepSeek, ...).\n"

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..config import DeerMemModelConfig

logger = logging.getLogger(__name__)


def build_llm(model_config: DeerMemModelConfig | None) -> Any:
    "构建并返回，并遵守 build_llm 所表达的接口约束。\n\nBuild a langchain ChatModel from DeerMem's model config (DI).\n\n    Returns ``None`` if ``model_config`` is None, has no ``model`` set\n    (zero-config: no LLM; non-LLM ops still work, an update will raise), OR if\n    ``init_chat_model`` fails (misconfigured provider/api_key/base_url). The\n    failure path degrades to ``None`` with a WARNING -- mirroring\n    :func:`_host_default_llm` -- so a bad explicit ``model`` does not crash app\n    startup: memory CRUD/read/search still work, extraction is disabled, and an\n    update raises at runtime with the underlying error logged.\n    "
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
