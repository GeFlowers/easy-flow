'''在首轮对话后为线程生成标题，并在失败或取消时提供本地回退标题。'''

import logging
import re
from typing import TYPE_CHECKING, Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.config import get_config
from langgraph.constants import TAG_NOSTREAM
from langgraph.runtime import Runtime

from deerflow.agents.middlewares.dynamic_context_middleware import is_dynamic_context_reminder
from deerflow.config.title_config import get_title_config
from deerflow.models import create_chat_model

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig
    from deerflow.config.title_config import TitleConfig

logger = logging.getLogger(__name__)


class TitleMiddlewareState(AgentState):
    '''扩展 智能体 状态，承载线程标题字段。'''

    title: NotRequired[str | None]


class TitleMiddleware(AgentMiddleware[TitleMiddlewareState]):
    '''等待首轮用户与助手交互后生成标题，并排除隐藏动态上下文消息。'''

    state_schema = TitleMiddlewareState

    def __init__(self, *, app_config: "AppConfig | None" = None, title_config: "TitleConfig | None" = None):
        '''保存应用配置或直接传入的标题配置。'''
        super().__init__()
        self._app_config = app_config
        self._title_config = title_config

    def _get_title_config(self):
        '''按直接配置、应用配置、全局配置的顺序取得标题参数。'''
        if self._title_config is not None:
            return self._title_config
        if self._app_config is not None:
            return self._app_config.title
        return get_title_config()

    def _normalize_content(self, content: object) -> str:
        '''递归提取字符串、内容块列表或字典中的文本字段。'''
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            parts = [self._normalize_content(item) for item in content]
            return "\n".join(part for part in parts if part)

        if isinstance(content, dict):
            text_value = content.get("text")
            if isinstance(text_value, str):
                return text_value

            nested_content = content.get("content")
            if nested_content is not None:
                return self._normalize_content(nested_content)

        return ""

    @staticmethod
    def _message_type(message: object) -> str | None:
        '''读取 LangChain 消息或序列化字典的类型，并统一 user/assistant 角色名。'''
        message_type = getattr(message, "type", None)
        if message_type is None and isinstance(message, dict):
            message_type = message.get("type") or message.get("role")
        if message_type == "user":
            return "human"
        if message_type == "assistant":
            return "ai"
        return message_type if isinstance(message_type, str) else None

    @staticmethod
    def _message_content(message: object) -> object:
        '''从消息对象或字典中读取内容字段。'''
        if isinstance(message, dict):
            return message.get("content", "")
        return getattr(message, "content", "")

    @staticmethod
    def _is_dynamic_context_reminder_message(message: object) -> bool:
        '''识别对象或字典形式的隐藏动态上下文提醒。'''
        if is_dynamic_context_reminder(message):
            return True
        if isinstance(message, dict):
            additional_kwargs = message.get("additional_kwargs")
            return isinstance(additional_kwargs, dict) and bool(additional_kwargs.get("dynamic_context_reminder"))
        return False

    @staticmethod
    def _is_user_message_for_title(message: object) -> bool:
        '''仅将真实用户消息作为标题素材，排除注入的系统提醒。'''
        return TitleMiddleware._message_type(message) == "human" and not TitleMiddleware._is_dynamic_context_reminder_message(message)

    def _get_title_user_message(self, state: TitleMiddlewareState) -> str:
        '''从历史中提取首条真实用户消息并规范化为文本。'''
        messages = state.get("messages") or []
        user_msg_content = next((self._message_content(m) for m in messages if self._is_user_message_for_title(m)), "")
        return self._normalize_content(user_msg_content)

    def _should_generate_title(self, state: TitleMiddlewareState, *, allow_partial_exchange: bool = False) -> bool:
        '''检查标题开关、现有标题和首轮消息条件，判断是否应生成标题。'''
        config = self._get_title_config()
        if not config.enabled:
            return False

        # 已有标题时保持现值，不重复调用生成逻辑。
        if state.get("title"):
            return False

        # 部分初始化的检查点可能没有消息列表；未完成交换仅在取消回退路径允许。
        messages = state.get("messages") or []
        min_messages = 1 if allow_partial_exchange else 2
        if len(messages) < min_messages:
            return False

        # 标题只从首轮真实用户请求生成。
        user_messages = [m for m in messages if self._is_user_message_for_title(m)]
        assistant_messages = [m for m in messages if self._message_type(m) == "ai"]

        # 正常路径等待首轮回复；中断路径允许仅凭用户请求持久化本地回退标题。
        return len(user_messages) == 1 and (len(assistant_messages) >= 1 or allow_partial_exchange)

    def _build_title_prompt(self, state: TitleMiddlewareState) -> tuple[str, str]:
        '''构造包含首条用户请求和首条助手答复的提示，并返回用户文本供回退使用。'''
        config = self._get_title_config()
        messages = state.get("messages") or []

        assistant_msg_content = next((self._message_content(m) for m in messages if self._message_type(m) == "ai"), "")

        user_msg = self._get_title_user_message(state)
        assistant_msg = self._strip_think_tags(self._normalize_content(assistant_msg_content))

        prompt = config.prompt_template.format(
            max_words=config.max_words,
            user_msg=user_msg[:500],
            assistant_msg=assistant_msg[:500],
        )
        return prompt, user_msg

    def _strip_think_tags(self, text: str) -> str:
        '''移除推理模型输出中的 think 区块，避免其内容进入线程标题。'''
        return re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()

    def _parse_title(self, content: object) -> str:
        '''清理模型输出的引号和推理标签，并按配置限制标题长度。'''
        config = self._get_title_config()
        title_content = self._normalize_content(content)
        title_content = self._strip_think_tags(title_content)
        title = title_content.strip().strip('"').strip("'")
        return title[: config.max_chars] if len(title) > config.max_chars else title

    def _fallback_title(self, user_msg: str) -> str:
        '''截取用户请求作为本地标题；空请求时使用默认会话名称。'''
        config = self._get_title_config()
        fallback_chars = min(config.max_chars, 50)
        if len(user_msg) > fallback_chars:
            # 为省略号预留空间，确保回退标题同样不超过 max_chars。
            ellipsis = "..."
            body = min(fallback_chars, config.max_chars - len(ellipsis))
            return user_msg[:body].rstrip() + ellipsis
        return user_msg if user_msg else "New Conversation"

    def _get_runnable_config(self) -> dict[str, Any]:
        '''继承当前 RunnableConfig 并标记标题模型调用，便于追踪归属且不重复打点。'''
        try:
            parent = get_config()
        except Exception:
            parent = {}
        config = {**parent}
        config["run_name"] = "title_agent"
        config["tags"] = [
            *(config.get("tags") or []),
            "middleware:title",
            TAG_NOSTREAM,
        ]
        return config

    def _generate_title_result(self, state: TitleMiddlewareState, *, allow_partial_exchange: bool = False) -> dict | None:
        '''同步钩子只生成本地回退标题，避免阻塞模型调用线程。'''
        if not self._should_generate_title(state, allow_partial_exchange=allow_partial_exchange):
            return None

        user_msg = self._get_title_user_message(state)
        return {"title": self._fallback_title(user_msg)}

    async def _agenerate_title_result(self, state: TitleMiddlewareState) -> dict | None:
        '''异步调用配置的标题模型；配置缺失或生成失败时回退到用户请求文本。'''
        if not self._should_generate_title(state):
            return None

        config = self._get_title_config()
        if not config.model_name:
            user_msg = self._get_title_user_message(state)
            return {"title": self._fallback_title(user_msg)}

        user_msg = self._get_title_user_message(state)

        try:
            prompt, user_msg = self._build_title_prompt(state)
            # 父 RunnableConfig 已包含追踪回调，模型层再次绑定会产生重复 跨度。
            model_kwargs = {"thinking_enabled": False, "attach_tracing": False}
            if self._app_config is not None:
                model_kwargs["app_config"] = self._app_config
            model = create_chat_model(name=config.model_name, **model_kwargs)
            response = await model.ainvoke(prompt, config=self._get_runnable_config())
            title = self._parse_title(response.content)
            if title:
                return {"title": title}
        except Exception:
            logger.debug("Failed to generate async title; falling back to local title", exc_info=True)
        return {"title": self._fallback_title(user_msg)}

    @override
    def after_model(self, state: TitleMiddlewareState, runtime: Runtime) -> dict | None:
        '''同步路径在首轮交互后写入本地回退标题。'''
        return self._generate_title_result(state)

    @override
    async def aafter_model(self, state: TitleMiddlewareState, runtime: Runtime) -> dict | None:
        '''异步路径生成模型标题，并在必要时使用本地回退。'''
        return await self._agenerate_title_result(state)
