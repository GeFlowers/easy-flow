'''实现不保存任何对话内容的记忆管理器，用于关闭记忆或作为后端扩展范例。

Noop 记忆后端是可正常调用但始终为空的 :class:`MemoryManager`。

它验证工厂、目录自动发现及配置切换组成的完整可插拔流程，也可作为新后端的模板。

可移植性原则（完整说明见 ``config.py``）：后端仅通过抽象基类的方法参数和
``backend_config`` 字典接收全部宿主信息。此目录唯一允许的 ``from deerflow``
导入是下方抽象接口导入；移植到其他代理时只需修改这一行。不得导入 deer-flow
路径辅助函数、配置单例或模型，应从 ``backend_config`` 获取这些信息。

编写新后端：
  1. 将此目录复制到 ``backends/<yourname>/``。
  2. 在 ``config.py`` 声明配置项与 ``from_backend_config``，解析 ``backend_config``，
     并从中读取 ``storage_path``，不要从 deer-flow 直接获取。
  3. 在 ``<yourname>_manager.py`` 重命名类；在 ``__init__`` 中将 ``backend_config``
     解析为自己的配置，并针对实际记忆系统实现抽象基类的方法。
  4. 可选实现 DeerMem 的内部能力方法：
     ``create_fact`` / ``delete_fact`` / ``update_fact`` / ``reload_memory`` /
     ``warm``，使宿主网关的 ``hasattr`` 探测能找到它们，从而支持事实增删改查、
     重载和预热界面。
  5. 在 ``__init__.py`` 中通过相对导入设置 ``MANAGER_CLASS = YourManager``。
  6. 在 ``config.yaml`` 中设置 ``manager_class: <yourname>``。

返回结构说明：宿主网关将 ``get_memory`` / ``export_memory`` /
``clear_memory`` / ``import_memory`` 的返回值转换为 DeerMem 响应结构，包含
``version`` / ``lastUpdated`` / ``user`` / ``history`` / ``facts[]``。
实际后端应返回可转换成此结构的字典；其他后端应将自身记录映射到此结构。
Noop 返回最小的 ``{"facts": []}``，其余字段由网关填入默认值。

使用 ``manager_class: noop`` 时，系统不保存或注入记忆，所有读取均为空。
适合测试、在不修改 ``enabled`` 的情况下关闭记忆，以及提供基准行为。
'''

from __future__ import annotations

from typing import Any

from deerflow.agents.memory.manager import MemoryManager

from .config import NoopConfig


def _empty_memory() -> dict[str, Any]:
    '''创建最小空记忆文档，供读取、清空和导出操作返回。'''
    return {"facts": []}


class NoopMemoryManager(MemoryManager):
    '''实现记忆管理器协议但不存储、不召回任何对话或事实。'''

    def __init__(self, backend_config: dict[str, Any] | None = None) -> None:
        '''解析宿主传入的后端配置，供示例说明配置注入方式；此后端不会使用这些配置。'''
        super().__init__(backend_config)
        self._config: NoopConfig = NoopConfig.from_backend_config(backend_config)

    def add(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        '''忽略排队记忆更新的请求，不保存本轮对话。'''
        return None

    def add_nowait(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
    ) -> None:
        '''忽略无需等待的记忆更新请求。'''
        return None

    def get_context(
        self,
        user_id: str | None,
        *,
        agent_name: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        '''不注入任何记忆上下文，始终返回空文本。'''
        return ""

    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        '''不执行记忆检索，始终返回空结果列表。'''
        return []

    def get_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '''返回符合最小记忆响应结构的空文档。'''
        return _empty_memory()

    def delete_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> None:
        '''保持空操作；此管理器没有持久化记忆可删除。'''
        return None

    def clear_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '''返回空记忆文档，表示清空后的状态。'''
        return _empty_memory()

    def import_memory(
        self,
        memory_data: dict[str, Any],
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '''忽略导入内容并返回空记忆状态，不写入任何数据。'''
        return _empty_memory()

    def export_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '''导出最小空记忆文档。'''
        return _empty_memory()

    def shutdown_flush(self, timeout: float) -> bool:
        '''空后端不会排队写入任务，因此关闭刷新无需操作并始终报告成功。'''
        return True
