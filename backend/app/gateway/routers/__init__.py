"""集中导出 Gateway 路由模块，供应用装配时按功能注册。"""

from . import (
    artifacts,
    assistants_compat,
    input_polish,
    mcp,
    models,
    scheduled_tasks,
    skills,
    suggestions,
    thread_runs,
    threads,
    uploads,
)

__all__ = [
    "artifacts",
    "assistants_compat",
    "input_polish",
    "mcp",
    "models",
    "scheduled_tasks",
    "skills",
    "suggestions",
    "threads",
    "thread_runs",
    "uploads",
]
