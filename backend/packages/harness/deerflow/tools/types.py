"""定义 DeerFlow 工具使用的运行时类型。"""

from typing import Any

from langchain.tools import ToolRuntime

from deerflow.agents.thread_state import ThreadState

# 所有 DeerFlow 工具共用的具体运行时类型。
# 为 ``context`` 使用 ``dict[str, Any]``，而非未绑定的 ``ContextT`` 类型变量，
# 可避免 LangChain 在对自动生成的 ``args_schema`` 调用 ``model_dump()`` 时发出
# PydanticSerializationUnexpectedValue 警告。
Runtime = ToolRuntime[dict[str, Any], ThreadState]
