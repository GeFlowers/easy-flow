'''把已配置的外部 ACP 智能体封装为工具，并桥接会话、权限和 MCP 服务。'''

import logging
import os
import shutil
from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, InjectedToolArg, StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class _InvokeACPAgentInput(BaseModel):
    '''约束外部智能体调用只接受目标代理名和独立任务提示。'''

    agent: str = Field(description="Name of the ACP agent to invoke")
    prompt: str = Field(description="The concise task prompt to send to the agent")


def _get_work_dir(thread_id: str | None) -> str:
    '''为当前线程创建 ACP 工作目录；无效线程标识时退回共享临时工作区。'''
    from deerflow.config.paths import get_paths
    from deerflow.runtime.user_context import get_effective_user_id

    paths = get_paths()
    if thread_id:
        try:
            work_dir = paths.acp_workspace_dir(thread_id, user_id=get_effective_user_id())
        except ValueError:
            logger.warning("Invalid thread_id %r for ACP workspace, falling back to global", thread_id)
            work_dir = paths.base_dir / "acp-workspace"
    else:
        work_dir = paths.base_dir / "acp-workspace"

    work_dir.mkdir(parents=True, exist_ok=True)
    logger.info("ACP agent work_dir: %s", work_dir)
    return str(work_dir)


def _build_mcp_servers() -> dict[str, dict[str, Any]]:
    '''将应用扩展配置转换为 ACP 客户端可连接的 MCP 服务配置。'''
    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.mcp.client import build_servers_config

    return build_servers_config(ExtensionsConfig.from_file())


def _build_acp_mcp_servers() -> list[dict[str, Any]]:
    '''筛选已启用服务并转换为 ACP 会话要求的传输专属字段结构。'''
    from deerflow.config.extensions_config import ExtensionsConfig

    extensions_config = ExtensionsConfig.from_file()
    enabled_servers = extensions_config.get_enabled_mcp_servers()

    mcp_servers: list[dict[str, Any]] = []
    for name, server_config in enabled_servers.items():
        transport_type = server_config.type or "stdio"
        payload: dict[str, Any] = {"name": name, "type": transport_type}

        if transport_type == "stdio":
            if not server_config.command:
                raise ValueError(f"MCP server '{name}' with stdio transport requires 'command' field")
            payload["command"] = server_config.command
            payload["args"] = server_config.args
            payload["env"] = [{"name": key, "value": value} for key, value in server_config.env.items()]
        elif transport_type in ("http", "sse"):
            if not server_config.url:
                raise ValueError(f"MCP server '{name}' with {transport_type} transport requires 'url' field")
            payload["url"] = server_config.url
            payload["headers"] = [{"name": key, "value": value} for key, value in server_config.headers.items()]
        else:
            raise ValueError(f"MCP server '{name}' has unsupported transport type: {transport_type}")

        mcp_servers.append(payload)

    return mcp_servers


def _build_permission_response(options: list[Any], *, auto_approve: bool) -> Any:
    '''按代理是否允许自动授权选择一次性批准选项，否则拒绝该权限请求。'''
    from acp import RequestPermissionResponse
    from acp.schema import AllowedOutcome, DeniedOutcome

    if auto_approve:
        for preferred_kind in ("allow_once", "allow_always"):
            for option in options:
                if getattr(option, "kind", None) != preferred_kind:
                    continue

                option_id = getattr(option, "option_id", None)
                if option_id is None:
                    option_id = getattr(option, "optionId", None)
                if option_id is None:
                    continue

                return RequestPermissionResponse(
                    outcome=AllowedOutcome(outcome="selected", optionId=option_id),
                )

    return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))


def _format_invocation_error(agent: str, cmd: str, exc: Exception) -> str:
    '''将启动失败转换为可操作的错误提示，特别说明 Codex 命令与 ACP 适配器区别。'''
    if not isinstance(exc, FileNotFoundError):
        return f"Error invoking ACP agent '{agent}': {exc}"

    message = f"Error invoking ACP agent '{agent}': Command '{cmd}' was not found on PATH."
    if cmd == "codex-acp" and shutil.which("codex"):
        return f"{message} The installed `codex` CLI does not speak ACP directly. Install a Codex ACP adapter (for example `npx @zed-industries/codex-acp`) or update `acp_agents.codex.command` and `args` in config.yaml."

    return f"{message} Install the agent binary or update `acp_agents.{agent}.command` in config.yaml."


def build_invoke_acp_agent_tool(agents: dict) -> BaseTool:
    '''构造可调用外部 ACP 代理的工具，并将会话输出汇总为文本返回。'''
    agent_lines = "\n".join(f"- {name}: {cfg.description}" for name, cfg in agents.items())
    description = (
        "Invoke an external ACP-compatible agent and return its final response.\n\n"
        "Available agents:\n"
        f"{agent_lines}\n\n"
        "IMPORTANT: ACP agents operate in their own independent workspace. "
        "Do NOT include /mnt/user-data paths in the prompt. "
        "Give the agent a self-contained task description — it will produce results in its own workspace. "
        "After the agent completes, its output files are accessible at /mnt/acp-workspace/ (read-only)."
    )
    _agents = dict(agents)

    async def _invoke(agent: str, prompt: str, config: Annotated[RunnableConfig, InjectedToolArg] = None) -> str:
        '''校验代理名称，启动独立进程并执行一次 ACP 提示会话。'''
        logger.info("Invoking ACP agent %s (prompt length: %d)", agent, len(prompt))
        logger.debug("Invoking ACP agent %s with prompt: %.200s%s", agent, prompt, "..." if len(prompt) > 200 else "")
        if agent not in _agents:
            available = ", ".join(_agents.keys())
            return f"Error: Unknown agent '{agent}'. Available: {available}"

        agent_config = _agents[agent]
        thread_id: str | None = ((config or {}).get("configurable") or {}).get("thread_id")

        try:
            from acp import PROTOCOL_VERSION, Client, text_block
            from acp.schema import ClientCapabilities, Implementation
        except ImportError:
            return "Error: agent-client-protocol package is not installed. Run `uv sync` to install project dependencies."

        class _CollectingClient(Client):
            '''收集 ACP 会话响应，并依据代理配置处理权限请求。'''

            def __init__(self) -> None:
                '''初始化本次会话的文本片段缓冲区。'''
                self._chunks: list[str] = []

            @property
            def collected_text(self) -> str:
                '''将会话过程中收到的文本片段拼接为最终响应。'''
                return "".join(self._chunks)

            async def session_update(self, session_id: str, update, **kwargs) -> None:  # type: ignore[override]
                '''从 ACP 会话更新中提取文本内容并追加到响应缓冲区。'''
                try:
                    from acp.schema import TextContentBlock

                    if hasattr(update, "content") and isinstance(update.content, TextContentBlock):
                        self._chunks.append(update.content.text)
                except Exception:
                    pass

            async def request_permission(self, options, session_id: str, tool_call, **kwargs):  # type: ignore[override]
                '''依据 ``auto_approve_permissions`` 决定批准或拒绝外部代理的工具权限请求。'''
                response = _build_permission_response(options, auto_approve=agent_config.auto_approve_permissions)
                outcome = response.outcome.outcome
                if outcome == "selected":
                    logger.info("ACP permission auto-approved for tool call %s in session %s", tool_call.tool_call_id, session_id)
                else:
                    logger.warning("ACP permission denied for tool call %s in session %s (set auto_approve_permissions: true in config.yaml to enable)", tool_call.tool_call_id, session_id)
                return response

        client = _CollectingClient()
        cmd = agent_config.command
        args = agent_config.args or []
        physical_cwd = _get_work_dir(thread_id)
        try:
            mcp_servers = _build_acp_mcp_servers()
        except ValueError as exc:
            logger.warning(
                "Invalid MCP server configuration for ACP agent '%s'; continuing without MCP servers: %s",
                agent,
                exc,
            )
            mcp_servers = []
        agent_env: dict[str, str] | None = None
        if agent_config.env:
            agent_env = {k: (os.environ.get(v[1:], "") if v.startswith("$") else v) for k, v in agent_config.env.items()}

        try:
            from acp import spawn_agent_process

            async with spawn_agent_process(client, cmd, *args, env=agent_env, cwd=physical_cwd) as (conn, proc):
                logger.info("Spawning ACP agent '%s' with command '%s' and args %s in cwd %s", agent, cmd, args, physical_cwd)
                await conn.initialize(
                    protocol_version=PROTOCOL_VERSION,
                    client_capabilities=ClientCapabilities(),
                    client_info=Implementation(name="deerflow", title="DeerFlow", version="0.1.0"),
                )
                session_kwargs: dict[str, Any] = {"cwd": physical_cwd, "mcp_servers": mcp_servers}
                if agent_config.model:
                    session_kwargs["model"] = agent_config.model
                session = await conn.new_session(**session_kwargs)
                await conn.prompt(
                    session_id=session.session_id,
                    prompt=[text_block(prompt)],
                )
            result = client.collected_text
            logger.info("ACP agent '%s' returned %s", agent, result[:1000])
            logger.info("ACP agent '%s' returned %d characters", agent, len(result))
            return result or "(no response)"
        except Exception as e:
            logger.error("ACP agent '%s' invocation failed: %s", agent, e)
            return _format_invocation_error(agent, cmd, e)

    return StructuredTool.from_function(
        name="invoke_acp_agent",
        description=description,
        coroutine=_invoke,
        args_schema=_InvokeACPAgentInput,
    )
