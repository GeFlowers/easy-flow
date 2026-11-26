'''按业务域组织 Gateway 路由，并集中暴露应用装配所需的路由模块。'''

from server.gateway.routers.agents import suggestions
from server.gateway.routers.configuration import global_instructions, input_polish, mcp, memory, models, skills
from server.gateway.routers.conversations import artifacts, thread_runs, threads, uploads
from server.gateway.routers.integrations import channel_connections, channels
from server.gateway.routers.operations import auth, feedback, scheduled_tasks

__all__ = [
    "artifacts",
    "auth",
    "channel_connections",
    "channels",
    "feedback",
    "global_instructions",
    "input_polish",
    "mcp",
    "memory",
    "models",
    "scheduled_tasks",
    "skills",
    "suggestions",
    "thread_runs",
    "threads",
    "uploads",
]
