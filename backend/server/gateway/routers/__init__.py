'''按业务域组织 Gateway 路由，并集中暴露应用装配所需的路由模块。'''

from server.gateway.routers.agents import agents, assistants_compat, suggestions
from server.gateway.routers.configuration import console, features, input_polish, mcp, memory, models, skills
from server.gateway.routers.conversations import artifacts, runs, thread_runs, threads, uploads
from server.gateway.routers.integrations import channel_connections, channels
from server.gateway.routers.operations import auth, feedback, scheduled_tasks

__all__ = [
    "agents",
    "artifacts",
    "assistants_compat",
    "auth",
    "channel_connections",
    "channels",
    "console",
    "features",
    "feedback",
    "input_polish",
    "mcp",
    "memory",
    "models",
    "runs",
    "scheduled_tasks",
    "skills",
    "suggestions",
    "thread_runs",
    "threads",
    "uploads",
]
