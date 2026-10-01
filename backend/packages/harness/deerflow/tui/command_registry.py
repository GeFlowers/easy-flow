'''维护终端命令目录，并解析用户输入为内置命令、技能命令或普通消息。'''

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Command:
    '''描述一条内置命令或技能命令及其显示类别。'''

    name: str
    description: str
    category: Literal["builtin", "skill"] = "builtin"


@dataclass(frozen=True)
class Resolution:
    '''保存斜杠输入解析后的类别、命令名称、参数和原始文本。'''

    kind: Literal["builtin", "skill", "unknown", "message"]
    name: str = ""
    args: str = ""
    text: str = ""


BUILTIN_COMMANDS: tuple[Command, ...] = (
    Command("help", "Show commands and keybindings"),
    Command("new", "Start a fresh thread"),
    Command("threads", "Open the thread switcher"),
    Command("switch", "Open the thread switcher"),
    Command("resume", "Resume a thread by id or title"),
    Command("goal", "Set, show or clear the active goal"),
    Command("model", "Open the model picker"),
    Command("skills", "Browse enabled and available skills"),
    Command("tools", "Show built-in, MCP and sandbox tools"),
    Command("mcp", "Show MCP server status"),
    Command("memory", "Show memory status and injected facts"),
    Command("uploads", "Show uploaded files for this thread"),
    Command("artifacts", "Show generated artifacts"),
    Command("details", "Toggle verbose activity rendering"),
    Command("usage", "Show token usage and context"),
    Command("config", "Show resolved config paths and overrides"),
    Command("quit", "Exit the TUI"),
)

_BUILTIN_NAMES = frozenset(c.name for c in BUILTIN_COMMANDS)


def build_registry(skills: list[dict]) -> list[Command]:
    '''合并内置命令和当前启用的技能，同时排除与内置命令同名的技能。'''
    commands = list(BUILTIN_COMMANDS)
    for skill in skills:
        if not skill.get("enabled", False):
            continue
        name = skill.get("name")
        if not name or name in _BUILTIN_NAMES:
            continue
        commands.append(Command(name=name, description=skill.get("description", "") or "", category="skill"))
    return commands


def filter_commands(commands: list[Command], query: str) -> list[Command]:
    '''按命令名前缀、名称包含关系和描述匹配的优先顺序筛选目录。'''
    q = query.strip().lower()
    if not q:
        return commands

    prefix: list[Command] = []
    substring: list[Command] = []
    description: list[Command] = []
    for command in commands:
        name = command.name.lower()
        if name.startswith(q):
            prefix.append(command)
        elif q in name:
            substring.append(command)
        elif q in command.description.lower():
            description.append(command)
    return prefix + substring + description


def resolve(text: str, skills: list[str] | None = None) -> Resolution:
    '''将斜杠输入解析为内置命令或技能；非斜杠输入保留为普通消息。'''
    stripped = text.strip()
    if not stripped.startswith("/"):
        return Resolution(kind="message", text=text)

    body = stripped[1:]
    name, _, args = body.partition(" ")
    name = name.strip()
    args = args.strip()

    if not name:
        return Resolution(kind="unknown", name="")

    if name in _BUILTIN_NAMES:
        return Resolution(kind="builtin", name=name, args=args)

    if skills and name in skills:
        return Resolution(kind="skill", name=name, args=args)

    return Resolution(kind="unknown", name=name, args=args)
