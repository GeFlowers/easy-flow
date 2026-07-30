"""提供向用户请求澄清信息的内置工具。"""
from typing import Literal

from langchain.tools import tool


@tool("ask_clarification", parse_docstring=True, return_direct=True)
def ask_clarification_tool(
    question: str,
    clarification_type: Literal[
        "missing_info",
        "ambiguous_requirement",
        "approach_choice",
        "risk_confirmation",
        "suggestion",
    ],
    context: str | None = None,
    options: list[str] | None = None,
) -> str:
    """发出澄清请求，并以中断命令暂停当前流程。"""
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
    return "Clarification request processed by middleware"
