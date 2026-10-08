'''

为 LangChain／LangSmith 追踪解析运行名称的辅助函数。'''

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def resolve_root_run_name(config: Mapping[str, Any], assistant_id: str | None) -> str:
    '''为根运行解析稳定的显示名称，优先保留已有元数据中的名称。'''
    for container_name in ("context", "configurable"):
        container = config.get(container_name)
        if isinstance(container, Mapping):
            agent_name = container.get("agent_name")
            if isinstance(agent_name, str) and agent_name.strip():
                return agent_name
    return assistant_id or "lead_agent"
