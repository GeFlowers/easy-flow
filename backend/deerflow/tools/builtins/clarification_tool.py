'''提供向用户请求澄清信息的内置工具。'''

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
    '''当无法在缺少用户输入的情况下继续时，向用户提出澄清问题。

    适用于以下情况：
    - **信息缺失**：未提供必要的路径、网址或具体要求。
    - **要求有歧义**：存在多种合理解释。
    - **方案选择**：多种方案均可行，需要用户表达偏好。
    - **高风险操作**：删除文件、修改生产环境等破坏性操作需要明确确认。
    - **建议**：提出推荐方案，希望先获得用户同意。

    调用后执行会自动中断，问题将展示给用户；收到用户回复后再继续。

    使用建议：
    - 每次只提出一个澄清问题，措辞应具体清楚。
    - 需要澄清时不要自行假设。
    - 高风险操作始终先请求确认。

    Args:
        question: 要向用户提出的澄清问题，应具体清楚。
        clarification_type: 澄清类型，可为 missing_info、ambiguous_requirement、
            approach_choice、risk_confirmation 或 suggestion。
        context: 可选背景，说明为什么需要澄清，帮助用户理解当前情况。
        options: 可选选项列表，适用于 approach_choice 或 suggestion；选项应清楚易选。
    '''
    return "Clarification request processed by middleware"
