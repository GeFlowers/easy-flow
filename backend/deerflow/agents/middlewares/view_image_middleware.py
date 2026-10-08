'''向视觉模型提供本轮上传或工具查看的图片，并校验线程路径、格式和读取大小。'''

import asyncio
import base64
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import override

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from deerflow.agents.thread_state import ThreadState
from deerflow.utils.messages import is_real_user_message

logger = logging.getLogger(__name__)

_MAX_IMAGE_BYTES = 20 * 1024 * 1024


class ViewImageMiddlewareState(ThreadState):
    '''复用线程状态定义，使图像查看记录沿用现有状态字段及其归并规则。'''


class ViewImageMiddleware(AgentMiddleware[ViewImageMiddlewareState]):
    '''上传图片仅附加到模型请求副本；工具查看的图片则通过隐藏消息传入后续调用。'''

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
                image_bytes = f.read(_MAX_IMAGE_BYTES + 1)
            from deerflow.tools.builtins.view_image_tool import _detect_image_mime

            if len(image_bytes) != expected_size or _detect_image_mime(image_bytes) != mime_type:
                return None
            base64_data = base64.b64encode(image_bytes).decode("utf-8")
            return f"data:{mime_type};base64,{base64_data}"
        except OSError:
            return None

    def _attach_uploaded_images(self, request: ModelRequest) -> ModelRequest:
        '''仅在模型请求副本中附加最近用户上传的图片，复用线程路径校验并限制总大小。'''
        from deerflow.sandbox.exceptions import SandboxRuntimeError
        from deerflow.sandbox.tools import resolve_and_validate_user_data_path, validate_local_tool_path
        from deerflow.tools.builtins.view_image_tool import _EXTENSION_TO_MIME

        thread_data = request.state.get("thread_data") if request.state else None
        if not thread_data:
            return request
        messages = list(request.messages)
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if not is_real_user_message(message):
                continue
            files = message.additional_kwargs.get("files")
            if not isinstance(files, list):
                return request
            content = list(message.content) if isinstance(message.content, list) else [{"type": "text", "text": message.content}]
            if any(isinstance(block, dict) and block.get("type") in {"image_url", "image"} for block in content):
                return request
            image_blocks: list[dict] = []
            total_size = 0
            seen: set[str] = set()
            for file in files[:10]:
                filename = file.get("filename") if isinstance(file, dict) else None
                if not isinstance(filename, str) or not filename or "/" in filename or "\\" in filename or filename in seen:
                    continue
                mime_type = _EXTENSION_TO_MIME.get(Path(filename).suffix.lower())
                if mime_type is None:
                    continue
                virtual_path = f"/mnt/user-data/uploads/{filename}"
                try:
                    # 不信任客户端传来的宿主路径，始终在当前线程上传目录中重新解析。
                    validate_local_tool_path(virtual_path, thread_data, read_only=True)
                    actual_path = resolve_and_validate_user_data_path(virtual_path, thread_data)
                    size = Path(actual_path).stat().st_size
                    if size > _MAX_IMAGE_BYTES - total_size:
                        continue
                    data_url = self._read_image_as_data_url(actual_path, mime_type, size)
                except (OSError, PermissionError, SandboxRuntimeError):
                    logger.warning("当前上传图片未通过文件读取或线程路径校验")
                    continue
                if data_url:
                    image_blocks.append({"type": "image_url", "image_url": {"url": data_url}})
                    total_size += size
                    seen.add(filename)
            if not image_blocks:
                return request
            messages[index] = message.model_copy(update={"content": [*content, *image_blocks]})
            logger.info("已向本次视觉模型请求附加 %d 张上传图片", len(image_blocks))
            return request.override(messages=messages)
        return request

    @override
    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]) -> ModelCallResult:
        '''同步调用前附加本轮图片，仅修改请求副本，不把图片编码写入检查点。'''
        return handler(self._attach_uploaded_images(request))

    @override
    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]) -> ModelCallResult:
        '''在线程中校验和编码本轮图片，再将请求副本交给异步模型调用链。'''
        prepared = await asyncio.to_thread(self._attach_uploaded_images, request)
        return await handler(prepared)

    def _create_image_details_message(self, state: ViewImageMiddlewareState) -> list[str | dict]:
        '''读取工具已登记的图片并构造混合内容块，交给隐藏消息注入流程。'''
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
