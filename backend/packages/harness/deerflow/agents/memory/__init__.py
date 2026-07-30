"""提供可插拔的记忆系统。

此包包含与后端无关的共享核心：记忆管理器契约、单例工厂及其重置入口。
后端位于后端子包中，每个后端都自包含并暴露管理器类；默认记忆后端的功能
模块位于其核心目录。替换后端只需新增对应目录并在记忆配置中指定名称，其他
宿主代码无需改动。

默认后端的私有格式化、数据访问、更新器和文件存储等符号不在此重新导出，
应从该后端的核心模块直接导入。
"""

from deerflow.agents.memory.manager import (
    MemoryManager,
    get_memory_manager,
    reset_memory_manager,
)

__all__ = [
    "MemoryManager",
    "get_memory_manager",
    "reset_memory_manager",
]
