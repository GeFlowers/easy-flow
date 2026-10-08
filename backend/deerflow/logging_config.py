'''提供鹿流日志级别、追踪标识与格式化配置辅助功能。'''

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from deerflow.config.app_config import apply_logging_level
from deerflow.trace_context import get_current_trace_id

DEFAULT_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
TRACE_TEXT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - [trace_id=%(trace_id)s] - %(message)s"
_TRACE_FILTER_NAME = "deerflow_trace_context_filter"


class TraceContextFilter(logging.Filter):
    '''为每条日志记录注入当前请求追踪标识，缺失时使用占位符。'''

    name = _TRACE_FILTER_NAME

    def filter(self, record: logging.LogRecord) -> bool:
        '''写入日志记录的追踪标识，并始终允许该记录继续处理。'''
        record.trace_id = get_current_trace_id() or "-"
        return True


class JsonTraceFormatter(logging.Formatter):
    '''在增强日志选择结构化格式时输出包含追踪标识的记录。'''

    _deerflow_trace_formatter = True

    def format(self, record: logging.LogRecord) -> str:
        '''序列化一条日志记录及其异常、堆栈信息为统一编码的结构化文本。'''
        if not hasattr(record, "trace_id"):
            record.trace_id = get_current_trace_id() or "-"
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "logger": record.name,
            "level": record.levelname,
            "trace_id": record.trace_id,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)
        return json.dumps(payload, ensure_ascii=False)


class TraceTextFormatter(logging.Formatter):
    '''标记文本追踪格式化器，以便配置关闭后恢复默认格式。'''

    _deerflow_trace_formatter = True


def _ensure_root_handler() -> None:
    '''在根日志器尚无处理器时安装默认文本处理器。'''
    if logging.root.handlers:
        return
    logging.basicConfig(level=logging.INFO, format=DEFAULT_LOG_FORMAT, datefmt=DEFAULT_LOG_DATE_FORMAT)


def _has_trace_filter(handler: logging.Handler) -> bool:
    '''判断指定处理器是否已经安装鹿流追踪过滤器。'''
    return any(getattr(f, "name", None) == _TRACE_FILTER_NAME or isinstance(f, TraceContextFilter) for f in handler.filters)


def _install_trace_filter(handler: logging.Handler) -> None:
    '''为处理器按需安装唯一的追踪过滤器。'''
    if not _has_trace_filter(handler):
        handler.addFilter(TraceContextFilter())


def _remove_trace_filter(handler: logging.Handler) -> None:
    '''移除处理器中由鹿流安装的全部追踪过滤器。'''
    handler.filters = [f for f in handler.filters if not (getattr(f, "name", None) == _TRACE_FILTER_NAME or isinstance(f, TraceContextFilter))]


def _default_formatter() -> logging.Formatter:
    '''创建未增强追踪信息时使用的默认文本格式化器。'''
    return logging.Formatter(DEFAULT_LOG_FORMAT, datefmt=DEFAULT_LOG_DATE_FORMAT)


def _trace_formatter(format_name: str | None) -> logging.Formatter:
    '''按配置名称返回结构化或文本追踪格式化器。'''
    if (format_name or "text").strip().lower() == "json":
        return JsonTraceFormatter()
    return TraceTextFormatter(TRACE_TEXT_LOG_FORMAT, datefmt=DEFAULT_LOG_DATE_FORMAT)


def configure_logging(config: object) -> None:
    '''依据应用配置设置根日志器的级别、追踪过滤器和输出格式。

    关闭增强时移除本模块添加的追踪组件并恢复默认格式；开启时为所有根处理器加入
    追踪标识字段和所选文本或结构化格式。
    '''
    _ensure_root_handler()

    logging_config = getattr(config, "logging", None)
    enhance = getattr(logging_config, "enhance", None)
    enhanced = bool(getattr(enhance, "enabled", False))

    for handler in logging.root.handlers:
        if enhanced:
            _install_trace_filter(handler)
            handler.setFormatter(_trace_formatter(getattr(enhance, "format", "text")))
        else:
            _remove_trace_filter(handler)
            if getattr(handler.formatter, "_deerflow_trace_formatter", False):
                handler.setFormatter(_default_formatter())

    apply_logging_level(getattr(config, "log_level", None))
