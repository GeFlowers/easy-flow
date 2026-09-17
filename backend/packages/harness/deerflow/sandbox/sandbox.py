"""定义沙箱提供者必须实现的文件与命令操作接口。"""

import re
from abc import ABC, abstractmethod

from deerflow.sandbox.search import GrepMatch

# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_extra_env(extra_env: dict[str, str] | None) -> None:
    """验证额外环境变量名称可安全传递给基于命令解释器的实现。"""
    if not extra_env:
        return
    for key in extra_env:
        if not isinstance(key, str) or not _ENV_NAME_PATTERN.fullmatch(key):
            raise ValueError(f"extra_env key {key!r} is not a valid POSIX environment variable name (must match ^[A-Za-z_][A-Za-z0-9_]*$). This protects shell-using sandbox implementations from command injection via the key.")


class Sandbox(ABC):
    """声明统一的沙箱命令执行和文件访问抽象接口。"""

    _id: str

    def __init__(self, id: str):
        """使用稳定的沙箱标识初始化实例。"""
        self._id = id

    @property
    def id(self) -> str:
        """返回沙箱的稳定标识。"""
        return self._id

    @abstractmethod
    def execute_command(
        self,
        command: str,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> str:
        """在沙箱中执行命令，并支持可选环境变量和超时限制。"""
        pass

    @abstractmethod
    def read_file(self, path: str) -> str:
        """读取指定文本文件的内容。"""
        pass

    @abstractmethod
    def download_file(self, path: str) -> bytes:
        """以字节形式下载指定文件。"""
        pass

    @abstractmethod
    def list_dir(self, path: str, max_depth=2) -> list[str]:
        """列出指定路径下不超过给定深度的目录内容。"""
        pass

    @abstractmethod
    def write_file(self, path: str, content: str, append: bool = False) -> None:
        """写入文本文件，或按需将内容追加到文件末尾。"""
        pass

    @abstractmethod
    def glob(self, path: str, pattern: str, *, include_dirs: bool = False, max_results: int = 200) -> tuple[list[str], bool]:
        """在指定路径中查找匹配通配模式的条目。"""
        pass

    @abstractmethod
    def grep(
        self,
        path: str,
        pattern: str,
        *,
        glob: str | None = None,
        literal: bool = False,
        case_sensitive: bool = False,
        max_results: int = 100,
    ) -> tuple[list[GrepMatch], bool]:
        """在指定路径下的文本文件中查找匹配的行。"""
        pass

    @abstractmethod
    def update_file(self, path: str, content: bytes) -> None:
        """以原始字节内容更新指定文件。"""
        pass
