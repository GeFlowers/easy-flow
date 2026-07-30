"""提供功能为空的记忆后端适配器，用于验证可插拔契约并充当模板。"""

from .noop_manager import NoopMemoryManager

#: The :class:`~deerflow.agents.memory.manager.MemoryManager` subclass this
#: backend exposes. Discovered by the factory's ``_scan_backends`` drop-in
#: mechanism under the folder name ``noop``.
MANAGER_CLASS = NoopMemoryManager
