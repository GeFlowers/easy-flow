"""定义 patched_deepseek 模块提供的职责与可复用接口。

Patched ChatDeepSeek that preserves reasoning_content in multi-turn conversations.

This module provides a patched version of ChatDeepSeek that properly handles
reasoning_content when sending messages back to the API. The original implementation
stores reasoning_content in additional_kwargs but doesn't include it when making
subsequent API calls, which causes errors with APIs that require reasoning_content
on all assistant messages when thinking mode is enabled.
"""

from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_deepseek import ChatDeepSeek

from deerflow.models.assistant_payload_replay import restore_assistant_payloads, restore_reasoning_content


class PatchedChatDeepSeek(ChatDeepSeek):
    """封装 PatchedChatDeepSeek 的状态、协作关系与公开操作。

    ChatDeepSeek with proper reasoning_content preservation.

        When using thinking/reasoning enabled models, the API expects reasoning_content
        to be present on ALL assistant messages in multi-turn conversations. This patched
        version ensures reasoning_content from additional_kwargs is included in the
        request payload.
    """

    @classmethod
    def is_lc_serializable(cls) -> bool:
        "判断条件是否成立并返回布尔结果，并遵守 is_lc_serializable 所表达的接口约束"
        return True

    @property
    def lc_secrets(self) -> dict[str, str]:
        "执行 lc_secrets 的明确职责，并返回与调用约定一致的结果"
        return {"api_key": "DEEPSEEK_API_KEY", "openai_api_key": "DEEPSEEK_API_KEY"}

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        """执行 _get_request_payload 的明确职责，并返回与调用约定一致的结果。

        Get request payload with reasoning_content preserved.

                Overrides the parent method to inject reasoning_content from
                additional_kwargs into assistant messages in the payload.
        """
        # Get the original messages before conversion
        original_messages = self._convert_input(input_).to_messages()

        # Call parent to get the base payload
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)

        restore_assistant_payloads(
            payload.get("messages", []),
            original_messages,
            restore_reasoning_content,
        )

        return payload
