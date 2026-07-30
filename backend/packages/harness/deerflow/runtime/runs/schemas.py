'定义 schemas 模块提供的职责与可复用接口。\n\nRun status and disconnect mode enums.'

from enum import StrEnum


class RunStatus(StrEnum):
    '封装 RunStatus 的状态、协作关系与公开操作。\n\nLifecycle status of a single run.'

    pending = "pending"
    running = "running"
    success = "success"
    error = "error"
    timeout = "timeout"
    interrupted = "interrupted"


class DisconnectMode(StrEnum):
    '封装 DisconnectMode 的状态、协作关系与公开操作。\n\nBehaviour when the SSE consumer disconnects.'

    cancel = "cancel"
    continue_ = "continue"
