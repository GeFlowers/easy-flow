'未说明'

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    '未说明'
    bg: str = "#1a1b26"
    panel: str = "#1f2335"
    border: str = "#2f334d"
    text: str = "#c0caf5"
    dim: str = "#565f89"
    muted: str = "#737aa2"

    primary: str = "#7dcfff"  # headings / app accent
    user: str = "#7aa2f7"  # user speaker
    assistant: str = "#c0caf5"  # assistant speaker
    tool: str = "#bb9af7"  # tool activity
    accent: str = "#9ece6a"  # success / ok
    warning: str = "#e0af68"  # running / caution
    error: str = "#f7768e"  # errors


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
