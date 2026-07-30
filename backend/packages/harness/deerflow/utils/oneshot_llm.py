"""处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""

from __future__ import annotations

import os

from langchain_core.messages import HumanMessage, SystemMessage

from deerflow.config.app_config import AppConfig
from deerflow.models import create_chat_model
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.tracing import inject_langfuse_metadata
from deerflow.utils.llm_text import extract_response_text


def _resolve_environment() -> str | None:
    """处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""
    return os.environ.get("DEER_FLOW_ENV") or os.environ.get("ENVIRONMENT")


async def run_oneshot_llm(
    *,
    system_instruction: str,
    user_content: str,
    run_name: str,
    app_config: AppConfig,
    model_name: str | None = None,
    thread_id: str | None = None,
) -> str:
    """处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""
    model = create_chat_model(name=model_name, thinking_enabled=False, app_config=app_config)
    invoke_config: dict = {"run_name": run_name}
    inject_langfuse_metadata(
        invoke_config,
        thread_id=thread_id,
        user_id=get_effective_user_id(),
        assistant_id=run_name,
        model_name=model_name,
        environment=_resolve_environment(),
    )
    response = await model.ainvoke(
        [
            SystemMessage(content=system_instruction),
            HumanMessage(content=user_content),
        ],
        config=invoke_config,
    )
    return extract_response_text(response.content)
