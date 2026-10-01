'''定义终端界面的配色方案和状态符号。'''

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    '''集中保存背景、边框、正文及用户、代理、工具和状态提示的颜色。'''

    bg: str = "#1a1b26"
    panel: str = "#1f2335"
    border: str = "#2f334d"
    text: str = "#c0caf5"
    dim: str = "#565f89"
    muted: str = "#737aa2"

    primary: str = "#7dcfff"
    user: str = "#7aa2f7"
    assistant: str = "#c0caf5"
    tool: str = "#bb9af7"
    accent: str = "#9ece6a"
    warning: str = "#e0af68"
    error: str = "#f7768e"


THEME = Theme()

SYMBOLS = {
    "user": "›",
    "assistant": "●",
    "tool": "⚙",
    "running": "◐",
    "ok": "✓",
    "error": "✗",
    "system": "·",
    "spinner": ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
}
