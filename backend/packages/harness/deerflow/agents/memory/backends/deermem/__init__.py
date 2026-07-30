"""提供默认且自包含的 DeerMem 记忆管理器后端。

该后端包含自身的管理器类，以及存储、队列、更新器、提示词和消息处理五个
功能模块。所有 DeerMem 私有逻辑均位于此处；共享包顶层只提供契约、工厂和
轻量入口。
"""

from .deer_mem import DeerMem

#: The :class:`~deerflow.agents.memory.manager.MemoryManager` subclass this
#: backend exposes. Discovered by the factory's ``_scan_backends`` drop-in
#: mechanism under the folder name ``deermem``.
MANAGER_CLASS = DeerMem
