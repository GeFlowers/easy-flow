'''为网关 HTTP 请求建立并回传关联追踪标识的 ASGI 中间件。'''

from __future__ import annotations

import logging
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from deerflow.config.app_config import is_trace_correlation_enabled
from deerflow.trace_context import TRACE_ID_HEADER, request_trace_context

logger = logging.getLogger(__name__)


class TraceMiddleware:
    '''在启用时将每个 HTTP 请求绑定到独立的追踪上下文。'''

    def __init__(self, app: ASGIApp, *, enabled: bool):
        '''保存下游 ASGI 应用及进程启动时确定的追踪开关。'''
        self.app = app
        self.enabled = bool(enabled)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        '''处理 HTTP 调用，在响应起始事件中写入当前请求的追踪标识。'''
        if scope["type"] != "http" or not self.enabled:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        incoming_trace_id = headers.get(TRACE_ID_HEADER)

        with request_trace_context(incoming_trace_id) as trace_id:

            async def send_with_trace(message: Message) -> None:
                '''在下游发送响应起始事件时追加追踪响应头。'''
                if message["type"] == "http.response.start":
                    response_headers = MutableHeaders(scope=message)
                    response_headers[TRACE_ID_HEADER] = trace_id
                await send(message)

            await self.app(scope, receive, send_with_trace)


def resolve_trace_enabled(config: Any) -> bool:
    '''根据应用配置解析追踪关联功能是否启用。'''
    return is_trace_correlation_enabled(config)
