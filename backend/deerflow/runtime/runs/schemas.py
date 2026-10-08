'''

运行状态与断开连接行为的枚举。'''

from enum import StrEnum


class RunStatus(StrEnum):
    '''

    单个运行的生命周期状态。'''

    pending = "pending"
    running = "running"
    success = "success"
    error = "error"
    timeout = "timeout"
    interrupted = "interrupted"


class DisconnectMode(StrEnum):
    '''

    服务端推送事件的消费方断开连接时的行为。'''

    cancel = "cancel"
    continue_ = "continue"
