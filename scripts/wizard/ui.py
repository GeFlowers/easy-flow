"""提供配置向导的终端样式与交互输入组件。"""

from __future__ import annotations

import getpass
import shutil
import sys

try:
    import termios
    import tty
except ImportError:  # pragma: no cover - non-Unix fallback
    termios = None
    tty = None

# ── ANSI colours ──────────────────────────────────────────────────────────────

def _supports_color() -> bool:
    """判断终端是否支持 ANSI 彩色文本。"""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    """在终端支持颜色时为文本添加指定 ANSI 样式。"""
    if _supports_color():
        return f"\033[{code}m{text}\033[0m"
    return text


def green(text: str) -> str:
    """将文本渲染为绿色。"""
    return _c(text, "32")


def red(text: str) -> str:
    """将文本渲染为红色。"""
    return _c(text, "31")


def yellow(text: str) -> str:
    """将文本渲染为黄色。"""
    return _c(text, "33")


def cyan(text: str) -> str:
    """将文本渲染为青色。"""
    return _c(text, "36")


def bold(text: str) -> str:
    """将文本渲染为粗体。"""
    return _c(text, "1")


def inverse(text: str) -> str:
    """将文本渲染为反色高亮。"""
    return _c(text, "7")


# ── UI primitives ─────────────────────────────────────────────────────────────

def print_header(title: str) -> None:
    """输出配置向导的主标题。"""
    width = max(len(title) + 4, 44)
    bar = "═" * width
    print()
    print(f"╔{bar}╗")
    print(f"║  {title.ljust(width - 2)}║")
    print(f"╚{bar}╝")
    print()


def print_section(title: str) -> None:
    """输出配置向导的分节标题。"""
    print()
    print(bold(f"── {title} ──"))
    print()


def print_success(message: str) -> None:
    """输出成功状态消息。"""
    print(f"  {green('✓')} {message}")


def print_warning(message: str) -> None:
    """输出警告状态消息。"""
    print(f"  {yellow('!')} {message}")


def print_error(message: str) -> None:
    """执行错误对应的单一步骤；仅作用于调用方传入的范围，并将异常交由调用方处理。"""
    print(f"  {red('✗')} {message}")


def print_info(message: str) -> None:
    """输出普通提示消息。"""
    print(f"  {cyan('→')} {message}")


def _ask_choice_with_numbers(prompt: str, options: list[str], default: int | None = None) -> int:
    """使用数字输入方式获取单选项索引。"""
    for i, opt in enumerate(options, 1):
        marker = f" {green('*')}" if default is not None and i - 1 == default else "  "
        print(f"{marker} {i}. {opt}")
    print()

    while True:
        suffix = f" [{default + 1}]" if default is not None else ""
        raw = input(f"{prompt}{suffix}: ").strip()
        if raw == "" and default is not None:
            return default
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return idx
        print(f"  Please enter a number between 1 and {len(options)}.")


def _supports_arrow_menu() -> bool:
    """判断当前终端是否支持方向键交互菜单。"""
    return (
        termios is not None
        and tty is not None
        and hasattr(sys.stdin, "isatty")
        and hasattr(sys.stdout, "isatty")
        and sys.stdin.isatty()
        and sys.stdout.isatty()
        and sys.stderr.isatty()
    )


def _clear_rendered_lines(count: int) -> None:
    """清除终端中上一轮菜单渲染的指定行数。"""
    if count <= 0:
        return
    sys.stdout.write("\x1b[2K\r")
    for _ in range(count):
        sys.stdout.write("\x1b[1A\x1b[2K\r")


def _read_key(fd: int) -> str:
    """以原始终端模式读取一次按键输入。"""
    first = sys.stdin.read(1)
    if first != "\x1b":
        return first

    second = sys.stdin.read(1)
    if second != "[":
        return first

    third = sys.stdin.read(1)
    return f"\x1b[{third}"


def _terminal_width() -> int:
    """返回当前终端宽度，无法获取时使用默认值。"""
    return max(shutil.get_terminal_size(fallback=(80, 24)).columns, 40)


def _truncate_line(text: str, max_width: int) -> str:
    """按显示宽度截断文本并在需要时添加省略号。"""
    if len(text) <= max_width:
        return text
    if max_width <= 1:
        return text[:max_width]
    return f"{text[: max_width - 1]}…"


def _render_choice_menu(options: list[str], selected: int) -> int:
    """渲染方向键单选菜单并返回占用的终端行数。"""
    number_width = len(str(len(options)))
    menu_width = _terminal_width()
    content_width = max(menu_width - 3, 20)
    for i, opt in enumerate(options, 1):
        line = _truncate_line(f"{i:>{number_width}}. {opt}", content_width)
        if i - 1 == selected:
            print(f"{green('›')} {inverse(bold(line))}")
        else:
            print(f"  {line}")
    sys.stdout.flush()
    return len(options)


def _ask_choice_with_arrows(prompt: str, options: list[str], default: int | None = None) -> int:
    """使用方向键菜单获取单选项索引。"""
    selected = default if default is not None else 0
    typed = ""
    fd = sys.stdin.fileno()
    original_settings = termios.tcgetattr(fd)
    rendered_lines = 0

    try:
        sys.stdout.write("\x1b[?25l")
        sys.stdout.flush()
        tty.setcbreak(fd)
        prompt_help = f"{prompt}  (↑/↓ move, Enter confirm, number quick-select)"
        print(cyan(_truncate_line(prompt_help, max(_terminal_width() - 2, 20))))

        while True:
            if rendered_lines:
                _clear_rendered_lines(rendered_lines)
            rendered_lines = _render_choice_menu(options, selected)

            key = _read_key(fd)

            if key == "\x03":
                raise KeyboardInterrupt

            if key in ("\r", "\n"):
                if typed:
                    idx = int(typed) - 1
                    if 0 <= idx < len(options):
                        selected = idx
                    typed = ""
                break

            if key == "\x1b[A":
                selected = (selected - 1) % len(options)
                typed = ""
                continue
            if key == "\x1b[B":
                selected = (selected + 1) % len(options)
                typed = ""
                continue
            if key in ("\x7f", "\b"):
                typed = typed[:-1]
                continue
            if key.isdigit():
                typed += key
                continue

        if rendered_lines:
            _clear_rendered_lines(rendered_lines)
        print(f"{prompt}: {options[selected]}")
        return selected
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original_settings)
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()


def ask_choice(prompt: str, options: list[str], default: int | None = None) -> int:
    """根据终端能力使用方向键菜单或数字菜单获取单选结果。"""
    if _supports_arrow_menu():
        return _ask_choice_with_arrows(prompt, options, default=default)
    return _ask_choice_with_numbers(prompt, options, default=default)


def ask_multi_choice(prompt: str, options: list[str], default: list[int] | None = None) -> list[int]:
    """通过逗号分隔的数字输入获取多个选项索引。"""
    has_default = default is not None
    default_indexes = list(default or [])
    for i, opt in enumerate(options, 1):
        marker = f" {green('*')}" if has_default and i - 1 in default_indexes else "  "
        print(f"{marker} {i}. {opt}")
    print()

    suffix = ""
    if default_indexes:
        suffix = f" [{','.join(str(idx + 1) for idx in default_indexes)}]"
    elif has_default:
        suffix = " [none]"

    while True:
        raw = input(f"{prompt}{suffix}: ").strip().lower()
        if raw == "" and has_default:
            return default_indexes
        if raw in {"none", "no", "n", "skip"}:
            return []
        if raw == "all":
            return list(range(len(options)))

        parts = [part.strip() for part in raw.replace(" ", ",").split(",") if part.strip()]
        selected: list[int] = []
        valid = bool(parts)
        for part in parts:
            if not part.isdigit():
                valid = False
                break
            idx = int(part) - 1
            if not 0 <= idx < len(options):
                valid = False
                break
            if idx not in selected:
                selected.append(idx)
        if valid:
            return selected

        print(f"  Enter comma-separated numbers between 1 and {len(options)}, 'all', or 'none'.")


def ask_text(prompt: str, default: str = "", required: bool = False) -> str:
    """读取文本输入，并处理默认值与必填校验。"""
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"{prompt}{suffix}: ").strip()
        if value:
            return value
        if default:
            return default
        if not required:
            return ""
        print("  This field is required.")


def ask_secret(prompt: str) -> str:
    """以隐藏回显方式读取敏感文本。"""
    while True:
        value = getpass.getpass(f"{prompt}: ").strip()
        if value:
            return value
        print("  API key cannot be empty.")


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    """读取是非选择并应用默认答案。"""
    suffix = "[Y/N]"
    while True:
        raw = input(f"{prompt} {suffix}: ").strip().lower()
        if raw == "":
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please enter y or n.")
