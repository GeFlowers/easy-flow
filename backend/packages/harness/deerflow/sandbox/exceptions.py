'''定义沙箱操作使用的异常层级。'''


class SandboxError(Exception):
    '''表示所有沙箱相关异常的基类。'''

    def __init__(self, message: str, details: dict | None = None):
        '''使用错误消息及可选的结构化详情初始化异常。'''
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        '''返回包含详情（如有）的可读错误文本。'''
        if self.details:
            detail_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{self.message} ({detail_str})"
        return self.message


class SandboxNotFoundError(SandboxError):
    '''表示请求的沙箱不存在。'''

    def __init__(self, message: str = "Sandbox not found", sandbox_id: str | None = None):
        '''使用消息和可选沙箱标识初始化未找到错误。'''
        details = {"sandbox_id": sandbox_id} if sandbox_id else None
        super().__init__(message, details)
        self.sandbox_id = sandbox_id


class SandboxRuntimeError(SandboxError):
    '''表示沙箱运行期状态或上下文错误。'''

    pass


class SandboxCommandError(SandboxError):
    '''表示执行沙箱命令时发生的错误。'''

    def __init__(self, message: str, command: str | None = None, exit_code: int | None = None):
        '''使用消息、命令及可选退出码初始化命令错误。'''
        details = {}
        if command:
            details["command"] = command[:100] + "..." if len(command) > 100 else command
        if exit_code is not None:
            details["exit_code"] = exit_code
        super().__init__(message, details)
        self.command = command
        self.exit_code = exit_code


class SandboxFileError(SandboxError):
    '''表示沙箱文件操作时发生的错误。'''

    def __init__(self, message: str, path: str | None = None, operation: str | None = None):
        '''使用消息、路径及可选操作名称初始化文件错误。'''
        details = {}
        if path:
            details["path"] = path
        if operation:
            details["operation"] = operation
        super().__init__(message, details)
        self.path = path
        self.operation = operation


class SandboxPermissionError(SandboxFileError):
    '''表示沙箱文件操作因权限不足而被拒绝。'''

    pass


class SandboxFileNotFoundError(SandboxFileError):
    '''表示请求的沙箱文件不存在。'''

    pass
