'''提供功能为空的记忆后端适配器，用于验证可插拔契约并充当模板。'''

from .noop_manager import NoopMemoryManager

MANAGER_CLASS = NoopMemoryManager
