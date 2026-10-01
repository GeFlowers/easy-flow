#!/usr/bin/env python
'''提供可在终端交互的主智能体调试入口。

从 ``backend/`` 目录运行时会加载项目环境、初始化工具并创建主智能体，随后逐条
读取输入、打印回复及本轮新生成的文件路径。运行日志统一写入当前目录的
``debug.log``，便于本地调试时检查完整过程。
'''

import asyncio
import logging

from dotenv import load_dotenv

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory

    _HAS_PROMPT_TOOLKIT = True
except ImportError:
    _HAS_PROMPT_TOOLKIT = False

load_dotenv()

_LOG_FMT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _setup_logging(log_level: int = logging.INFO) -> None:
    '''将根日志器的现有处理器替换为写入 debug.log 的文件处理器。

    文件和根日志级别由 ``log_level`` 初始化；清理旧处理器可避免日志输出到交互
    终端。后续配置可以调整具名日志器级别，但不会自动改变这里设置的文件处理器级别。
    '''
    root = logging.root
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    root.setLevel(log_level)

    file_handler = logging.FileHandler("debug.log", mode="a", encoding="utf-8")
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(_LOG_FMT, datefmt=_LOG_DATEFMT))
    root.addHandler(file_handler)


async def main():
    # 先安装文件日志，避免加载配置期间的警告落到交互终端。
    '''初始化运行配置和工具，创建主智能体并处理逐轮交互输入。'''
    _setup_logging()

    from deerflow.config import get_app_config
    from deerflow.config.app_config import apply_logging_level

    app_config = get_app_config()
    apply_logging_level(app_config.log_level)

    # 延后导入运行时模块，使导入期间产生的日志也写入调试文件。
    from langchain_core.messages import HumanMessage
    from langgraph.runtime import Runtime

    from deerflow.agents import make_lead_agent
    from deerflow.config.paths import get_paths
    from deerflow.mcp import initialize_mcp_tools
    from deerflow.runtime.user_context import get_effective_user_id

    # 启动时连接并注册已配置的 MCP 工具。
    try:
        await initialize_mcp_tools()
    except Exception as e:
        print(f"Warning: Failed to initialize MCP tools: {e}")

    # 使用专用调试线程标识和调试选项创建本轮运行配置。
    config = {
        "configurable": {
            "thread_id": "debug-thread-001",
            "thinking_enabled": True,
            "is_plan_mode": True,
            # 如需调试其他模型，可在此设置模型名称。
            "model_name": "kimi-k2.5",
        }
    }

    runtime = Runtime(context={"thread_id": config["configurable"]["thread_id"]})
    config["configurable"]["__pregel_runtime"] = runtime

    agent = make_lead_agent(config)

    session = PromptSession(history=InMemoryHistory()) if _HAS_PROMPT_TOOLKIT else None

    print("=" * 50)
    print("Lead Agent Debug Mode")
    print("Type 'quit' or 'exit' to stop")
    print(f"Logs: debug.log (log_level={app_config.log_level})")
    if not _HAS_PROMPT_TOOLKIT:
        print("Tip: `uv sync --group dev` to enable arrow-key & history support")
    print("=" * 50)

    seen_artifacts: set[str] = set()

    while True:
        try:
            if session:
                user_input = (await session.prompt_async("\nYou: ")).strip()
            else:
                user_input = input("\nYou: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit"):
                print("Goodbye!")
                break

            # 将用户输入交给主智能体执行一轮。
            state = {"messages": [HumanMessage(content=user_input)]}
            result = await agent.ainvoke(state, config=config)

            # 输出本轮最后一条智能体消息。
            if result.get("messages"):
                last_message = result["messages"][-1]
                print(f"\nAgent: {last_message.content}")

            # 只展示此前未报告过的产物，并解析其虚拟路径对应的本地位置。
            artifacts = result.get("artifacts") or []
            new_artifacts = [p for p in artifacts if p not in seen_artifacts]
            if new_artifacts:
                thread_id = config["configurable"]["thread_id"]
                user_id = get_effective_user_id()
                paths = get_paths()
                print("\n[Presented files]")
                for virtual in new_artifacts:
                    try:
                        physical = paths.resolve_virtual_path(thread_id, virtual, user_id=user_id)
                        print(f"  - {virtual}\n    → {physical}")
                    except ValueError as exc:
                        print(f"  - {virtual}    (failed to resolve physical path: {exc})")
                seen_artifacts.update(new_artifacts)

        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")
            import traceback

            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
