'''在图像查看工具完成后读取图片，并在下一次模型调用前将图片内容加入对话状态。'''

import asyncio
import base64
import logging
from pathlib import Path
from typing import override

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from deerflow.agents.thread_state import ThreadState

logger = logging.getLogger(__name__)

_MAX_IMAGE_BYTES = 20 * 1024 * 1024


class ViewImageMiddlewareState(ThreadState):
    '''复用线程状态定义，使图像查看记录沿用现有状态字段及其归并规则。'''


class ViewImageMiddleware(AgentMiddleware[ViewImageMiddlewareState]):
    '''确认图像工具调用均已完成后，把磁盘图片编码为模型可接收的消息并注入线程状态。'''

    state_schema = ViewImageMiddlewareState

    def _get_last_assistant_message(self, messages: list) -> AIMessage | None:
        '''从消息序列末尾向前查找最近一条模型消息；不存在时返回 None。'''
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                return msg
        return None

    def _has_view_image_tool(self, message: AIMessage) -> bool:
        '''判断模型消息是否发起了图像查看工具调用。'''
        if not hasattr(message, "tool_calls") or not message.tool_calls:
            return False

        return any(tool_call.get("name") == "view_image" for tool_call in message.tool_calls)

    def _all_tools_completed(self, messages: list, assistant_msg: AIMessage) -> bool:
        '''核对该模型消息中的每个工具调用编号是否都已出现在后续工具结果消息中。'''
        if not hasattr(assistant_msg, "tool_calls") or not assistant_msg.tool_calls:
            return False

        tool_call_ids = {tool_call.get("id") for tool_call in assistant_msg.tool_calls if tool_call.get("id")}

        try:
            assistant_idx = messages.index(assistant_msg)
        except ValueError:
            return False

        completed_tool_ids = set()
        for msg in messages[assistant_idx + 1 :]:
            if isinstance(msg, ToolMessage) and msg.tool_call_id:
                completed_tool_ids.add(msg.tool_call_id)

        return tool_call_ids.issubset(completed_tool_ids)

    @staticmethod
    def _read_image_as_data_url(actual_path: str, mime_type: str, expected_size: int) -> str | None:
        '''复核图片文件仍存在且大小未变、未超限，再编码为数据 URL；读取失败时返回 None。'''
        try:
            file_path = Path(actual_path)
            if not file_path.exists() or not file_path.is_file():
                return None
            current_size = file_path.stat().st_size
            if current_size != expected_size:
                return None
            if current_size > _MAX_IMAGE_BYTES:
                return None
            with open(file_path, "rb") as f:
                image_bytes = f.read()
            base64_data = base64.b64encode(image_bytes).decode("utf-8")
            return f"data:{mime_type};base64,{base64_data}"
        except OSError:
            return None

    def _create_image_details_message(self, state: ViewImageMiddlewareState) -> list[str | dict]:
        '''按需读取状态记录的图片并构造混合文本与图片内容块，不把编码后的大数据写入检查点。'''
        viewed_images = state.get("viewed_images", {})
        if not viewed_images:
            return [{"type": "text", "text": "No images have been viewed."}]

        content_blocks: list[str | dict] = [{"type": "text", "text": "Here are the images you've viewed:"}]

        for image_path, image_data in viewed_images.items():
            mime_type = image_data.get("mime_type", "unknown")
            actual_path = image_data.get("actual_path", "")
            expected_size = image_data.get("size", 0)

            content_blocks.append({"type": "text", "text": f"\n- **{image_path}** ({mime_type})"})

            if actual_path:
                data_url = self._read_image_as_data_url(actual_path, mime_type, expected_size)
                if data_url:
                    content_blocks.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        }
                    )
                else:
                    content_blocks.append({"type": "text", "text": f"  (file unavailable or changed on disk: {actual_path})"})

        return content_blocks

    def _should_inject_image_message(self, state: ViewImageMiddlewareState) -> bool:
        '''仅当最近的图片查看调用全部完成且尚未注入过图片说明消息时返回 True。'''
        messages = state.get("messages", [])
        if not messages:
            return False

        last_assistant_msg = self._get_last_assistant_message(messages)
        if not last_assistant_msg:
            return False

        if not self._has_view_image_tool(last_assistant_msg):
            return False

        if not self._all_tools_completed(messages, last_assistant_msg):
            return False

        assistant_idx = messages.index(last_assistant_msg)
        for msg in messages[assistant_idx + 1 :]:
            if isinstance(msg, HumanMessage):
                content_str = str(msg.content)
                if "Here are the images you've viewed" in content_str or "Here are the details of the images you've viewed" in content_str:
                    return False

        return True

    def _inject_image_message(self, state: ViewImageMiddlewareState) -> dict | None:
        '''满足注入条件时创建仅供模型使用的隐藏用户消息，并返回消息状态更新。'''
        if not self._should_inject_image_message(state):
            return None

        image_content = self._create_image_details_message(state)

        human_msg = HumanMessage(content=image_content, additional_kwargs={"hide_from_ui": True})

        logger.debug("Injecting image details message with images before LLM call")

        return {"messages": [human_msg]}

    @override
    def before_model(self, state: ViewImageMiddlewareState, runtime: Runtime) -> dict | None:
        '''同步模型调用钩子：必要时将已查看的图片内容加入下一次模型请求。'''
        return self._inject_image_message(state)

    @override
    async def abefore_model(self, state: ViewImageMiddlewareState, runtime: Runtime) -> dict | None:
        '''异步模型调用钩子：在线程中读取并编码图片，避免较大的文件操作阻塞事件循环。'''
        if not self._should_inject_image_message(state):
            return None
        image_content = await asyncio.to_thread(self._create_image_details_message, state)
        human_msg = HumanMessage(content=image_content, additional_kwargs={"hide_from_ui": True})
        logger.debug("Injecting image details message with images before LLM call")
        return {"messages": [human_msg]}
