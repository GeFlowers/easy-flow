'''定义空记忆后端的配置解析范例，并展示宿主注入字段的标准入口。

Noop 后端配置是解析 ``backend_config`` 的模板。

此模块展示新记忆后端如何配置自身。编写后端前应遵守以下可移植性原则：

    后端只能通过两条途径接收宿主提供的全部信息：
      1. :class:`MemoryManager` 抽象基类的方法参数（``manager.py``），
         如 ``user_id`` / ``agent_name`` / ``thread_id`` / ``messages`` 等。
      2. 传入 ``__init__`` 的 ``backend_config`` 字典。
    不得导入其他 deer-flow 模块或硬编码其路径。整个后端目录唯一允许的
    ``from deerflow`` 语句是 ``<name>_manager.py`` 中的抽象接口导入：

        from deerflow.agents.memory.manager import MemoryManager

    这一行将后端与宿主连接起来；移植到其他代理时只需修改这一行。
    存储根目录、模型及钩子等其他信息均通过 ``backend_config`` 提供。

工厂（``manager.py::get_memory_manager``）为每个后端向 ``backend_config`` 注入：
  - ``storage_path`` (str)：可写状态目录，使用宿主默认值或用户在 config.yaml
    中配置的值。应将其作为存储根目录，不要自行调用 deer-flow 路径辅助函数。
  - ``tracing_callback`` (Callable | None)：宿主提供的默认模型调用追踪回调（langfuse）。
    后端需要追踪时应声明并使用此字段；否则可忽略，未知字段过滤会将其丢弃。
  - ``should_keep_hidden_message`` (Callable | None)：宿主提供的默认隐藏消息保留策略，
    用于 ``hide_from_ui`` 标记的人类澄清消息。后端过滤隐藏消息时应使用此回调，否则可忽略。
  - 用户的 ``config.yaml::memory.backend_config`` 字段，如 ``model``、
    ``vector_store``、``embedder`` 及阈值等后端自身配置。

下方 ``NoopConfig`` 对应这些字段。Noop 不存储任何内容，因此忽略全部字段；
开发新后端时可复制此结构、重命名并补充自己的配置项。
'''

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class NoopConfig:
    '''保存空记忆后端可识别的宿主注入字段；该后端不实际使用这些配置。'''

    storage_path: str = ""

    example_option: str = "default"

    tracing_callback: Callable[..., Any] | None = None

    should_keep_hidden_message: Callable[[Any], bool] | None = None

    @classmethod
    def from_backend_config(cls, backend_config: dict[str, Any] | None) -> NoopConfig:
        '''从后端配置字典读取已知字段，并忽略该后端不消费的其他配置项。'''
        cfg = dict(backend_config or {})
        return cls(
            storage_path=str(cfg.get("storage_path") or ""),
            example_option=str(cfg.get("example_option", "default")),
            tracing_callback=cfg.get("tracing_callback"),
            should_keep_hidden_message=cfg.get("should_keep_hidden_message"),
        )
