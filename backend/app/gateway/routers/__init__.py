"""按业务域组织 Gateway 路由，并集中暴露应用装配所需的路由模块。"""

from app.gateway.routers.agents import agents, assistants_compat, suggestions
from app.gateway.routers.configuration import console, features, input_polish, mcp, memory, models, skills
from app.gateway.routers.conversations import artifacts, runs, thread_runs, threads, uploads
from app.gateway.routers.integrations import channel_connections, channels, github_webhooks
from app.gateway.routers.operations import auth, feedback, scheduled_tasks

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
    "github_webhooks",
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
