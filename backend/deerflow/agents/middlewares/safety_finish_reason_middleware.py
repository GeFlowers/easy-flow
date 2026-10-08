'''当供应商因安全原因中止生成时，阻止执行可能被截断的工具调用并记录判定信息。'''

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares.safety_termination_detectors import (
    SafetyTermination,
    SafetyTerminationDetector,
    default_detectors,
)
from deerflow.agents.middlewares.tool_call_metadata import clone_ai_message_with_tool_calls

if TYPE_CHECKING:
    from deerflow.config.safety_finish_reason_config import SafetyFinishReasonConfig

logger = logging.getLogger(__name__)


_USER_FACING_MESSAGE = (
    "The model provider stopped this response with a safety-related signal "
    "({reason_field}={reason_value!r}, detector={detector!r}). Any tool "
    "calls produced in this turn were suppressed because their arguments "
    "may be truncated and unsafe to execute. Please rephrase the request "
    "or ask for a narrower output."
)


class SafetyFinishReasonMiddleware(AgentMiddleware[AgentState]):
    '''根据可配置检测器识别安全终止信号，并清除同一响应中的不完整工具调用。'''

    def __init__(self, detectors: list[SafetyTerminationDetector] | None = None) -> None:
        '''复制传入检测器列表，或在未配置时创建项目内置检测器。'''
        super().__init__()
        self._detectors: list[SafetyTerminationDetector] = list(detectors) if detectors else default_detectors()

    @classmethod
    def from_config(cls, config: SafetyFinishReasonConfig) -> SafetyFinishReasonMiddleware:
        '''根据校验后的应用配置加载自定义检测器；显式空列表报错以避免静默关闭检测。'''
        if config.detectors is None:
            return cls()

        if not config.detectors:
            raise ValueError("safety_finish_reason.detectors must be omitted (use built-ins) or contain at least one entry; use enabled=false to disable the middleware entirely.")

        from deerflow.reflection import resolve_variable

        detectors: list[SafetyTerminationDetector] = []
        for entry in config.detectors:
            detector_cls = resolve_variable(entry.use)
            kwargs = dict(entry.config) if entry.config else {}
            detector = detector_cls(**kwargs)
            if not isinstance(detector, SafetyTerminationDetector):
                raise TypeError(f"{entry.use} did not produce a SafetyTerminationDetector (got {type(detector).__name__}); ensure it has a `name` attribute and a `detect(message)` method")
            detectors.append(detector)
        return cls(detectors=detectors)


    def _detect(self, message: AIMessage) -> SafetyTermination | None:
        '''依次调用检测器，跳过发生异常的实现，并返回首个识别到的终止信号。'''
        for detector in self._detectors:
            try:
                hit = detector.detect(message)
            except Exception:  # noqa: BLE001 - 检测器异常不应中断智能体运行
                logger.exception("SafetyTerminationDetector %r raised; treating as no-match", getattr(detector, "name", type(detector).__name__))
                continue
            if hit is not None:
                return hit
        return None


    @staticmethod
    def _append_user_message(content: object, text: str) -> str | list:
        '''按消息内容类型追加面向用户的说明，保留分块消息的原始结构。'''
        if content is None or content == "":
            return text
        if isinstance(content, list):
            return [*content, {"type": "text", "text": f"\n\n{text}"}]
        if isinstance(content, str):
            return content + f"\n\n{text}"
        return str(content) + f"\n\n{text}"

    def _build_suppressed_message(
        self,
        message: AIMessage,
        termination: SafetyTermination,
    ) -> AIMessage:
        '''复制模型回复，清空结构化和原始工具调用，并附加终止原因与被抑制工具信息。'''
        suppressed_names = [tc.get("name") or "unknown" for tc in (message.tool_calls or [])]
        explanation = _USER_FACING_MESSAGE.format(
            reason_field=termination.reason_field,
            reason_value=termination.reason_value,
            detector=termination.detector,
        )
        new_content = self._append_user_message(message.content, explanation)

        cleared = clone_ai_message_with_tool_calls(message, [], content=new_content)

        kwargs = dict(getattr(cleared, "additional_kwargs", None) or {})
        kwargs["safety_termination"] = {
            "detector": termination.detector,
            "reason_field": termination.reason_field,
            "reason_value": termination.reason_value,
            "suppressed_tool_call_count": len(suppressed_names),
            "suppressed_tool_call_names": suppressed_names,
            "extras": dict(termination.extras) if termination.extras else {},
        }
        return cleared.model_copy(update={"additional_kwargs": kwargs})


    def _emit_event(
        self,
        termination: SafetyTermination,
        suppressed_names: list[str],
        runtime: Runtime,
    ) -> None:
        '''向实时流发送工具调用被抑制的事件，便于界面清理已经显示的工具运行占位。'''
        try:
            from langgraph.config import get_stream_writer

            writer = get_stream_writer()
        except Exception:  # noqa: BLE001
            logger.debug("get_stream_writer unavailable; skipping safety_termination event", exc_info=True)
            return

        thread_id = None
        if runtime is not None and getattr(runtime, "context", None):
            thread_id = runtime.context.get("thread_id") if isinstance(runtime.context, dict) else None

        try:
            writer(
                {
                    "type": "safety_termination",
                    "detector": termination.detector,
                    "reason_field": termination.reason_field,
                    "reason_value": termination.reason_value,
                    "suppressed_tool_call_count": len(suppressed_names),
                    "suppressed_tool_call_names": suppressed_names,
                    "thread_id": thread_id,
                }
            )
        except Exception:  # noqa: BLE001
            logger.debug("Failed to emit safety_termination stream event", exc_info=True)

    def _record_audit_event(
        self,
        termination: SafetyTermination,
        message,
        tool_calls: list[dict],
        runtime: Runtime,
    ) -> None:
        '''将终止信号及被抑制工具的名称、数量和标识写入运行日志，不记录工具参数。'''
        journal = None
        if runtime is not None and getattr(runtime, "context", None):
            context = runtime.context
            if isinstance(context, dict):
                journal = context.get("__run_journal")
        if journal is None:
            return

        suppressed_names = [tc.get("name") or "unknown" for tc in tool_calls]
        suppressed_ids = [tc.get("id") for tc in tool_calls if tc.get("id")]

        changes = {
            "detector": termination.detector,
            "reason_field": termination.reason_field,
            "reason_value": termination.reason_value,
            "suppressed_tool_call_count": len(tool_calls),
            "suppressed_tool_call_names": suppressed_names,
            "suppressed_tool_call_ids": suppressed_ids,
            "message_id": getattr(message, "id", None),
            "extras": dict(termination.extras) if termination.extras else {},
        }

        try:
            journal.record_middleware(
                tag="safety_termination",
                name=type(self).__name__,
                hook="after_model",
                action="suppress_tool_calls",
                changes=changes,
            )
        except Exception:  # noqa: BLE001
            logger.debug("Failed to record middleware:safety_termination event", exc_info=True)


    def _apply(self, state: AgentState, runtime: Runtime) -> dict | None:
        '''仅在最后一条模型消息包含工具调用且检测到安全终止时清理调用并发出审计事件。'''
        messages = state.get("messages", [])
        if not messages:
            return None

        last = messages[-1]
        if not isinstance(last, AIMessage):
            return None

        tool_calls = last.tool_calls
        if not tool_calls:
            return None

        termination = self._detect(last)
        if termination is None:
            return None

        ctx = getattr(runtime, "context", None)
        if isinstance(ctx, dict):
            ctx["stop_reason"] = "safety_capped"
        patched = self._build_suppressed_message(last, termination)

        thread_id = None
        if runtime is not None and getattr(runtime, "context", None):
            thread_id = runtime.context.get("thread_id") if isinstance(runtime.context, dict) else None

        logger.warning(
            "Provider safety termination detected — suppressed %d tool call(s)",
            len(tool_calls),
            extra={
                "thread_id": thread_id,
                "detector": termination.detector,
                "reason_field": termination.reason_field,
                "reason_value": termination.reason_value,
                "suppressed_tool_call_names": [tc.get("name") for tc in tool_calls],
            },
        )

        self._emit_event(termination, [tc.get("name") or "unknown" for tc in tool_calls], runtime)
        self._record_audit_event(termination, last, list(tool_calls), runtime)

        return {"messages": [patched]}


    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        '''在同步模型返回后应用工具调用抑制逻辑。'''
        return self._apply(state, runtime)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        '''在异步模型返回后应用同一套工具调用抑制逻辑。'''
        return self._apply(state, runtime)
