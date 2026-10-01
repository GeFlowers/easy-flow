'''实现终端聊天界面，负责命令输入、线程切换、流式渲染和会话控制。'''

from __future__ import annotations

import uuid
from functools import partial

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from deerflow.runtime.goal import parse_goal_command

from .input_history import InputHistory
from .render import render_header, render_status, render_transcript
from .runtime import stream_actions
from .theme import SYMBOLS, THEME
from .view_state import (
    ClearRows,
    RunEnded,
    RunStarted,
    SystemMessage,
    ThreadTitle,
    UserSubmitted,
    initial_state,
    reduce,
)
from .widgets.composer import ComposerInput

_HELP_TEXT = "Commands:  /new  /threads  /goal  /model  /skills  /tools  /mcp  /memory  /usage  /config  /quit\nKeys:  Enter send · Ctrl+C interrupt or quit · Ctrl+L redraw · / commands · Esc close overlay"


class SelectScreen(ModalScreen):
    '''展示模型或线程选项的模态选择框，并将选中项回传给调用方。'''

    BINDINGS = [Binding("escape", "cancel", "Close")]

    def __init__(self, title: str, options: list[tuple[str, str]]) -> None:
        '''保存选择框标题及选项标识与显示文本。'''
        super().__init__()
        self._title = title
        self._options = options

    def compose(self) -> ComposeResult:
        '''构建对话框标题和可选择列表。'''
        with Vertical(id="dialog"):
            yield Label(self._title, id="dialog-title")
            yield OptionList(*[Option(label, id=oid) for oid, label in self._options], id="dialog-list")

    def on_mount(self) -> None:
        '''弹窗挂载后将键盘焦点放到选项列表。'''
        self.query_one(OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        '''选中选项后以该选项标识关闭弹窗并返回结果。'''
        self.dismiss(event.option_id)

    def action_cancel(self) -> None:
        '''取消选择并以空值关闭弹窗。'''
        self.dismiss(None)


class DeerFlowTUI(App):
    '''组织终端聊天主界面及其快捷键、命令面板、流式运行和状态展示。'''

    CSS = f"""
    Screen {{
        background: {THEME.bg};
        color: {THEME.text};
    }}
        height: 1;
        padding: 0 1;
        background: {THEME.panel};
    }}
        height: 1fr;
        padding: 1 2;
        background: {THEME.bg};
        scrollbar-size-vertical: 1;
    }}
        width: 100%;
        height: auto;
    }}
        height: 1;
        padding: 0 1;
        background: {THEME.panel};
        color: {THEME.muted};
    }}
        height: auto;
        max-height: 10;
        margin: 0 1;
        padding: 0 1;
        background: {THEME.panel};
        border: round {THEME.border};
        display: none;
    }}
        display: block;
    }}
        height: 3;
        margin: 0 1 1 1;
        border: round {THEME.border};
        background: {THEME.panel};
    }}
        border: round {THEME.primary};
    }}
    SelectScreen {{
        align: center middle;
    }}
    SelectScreen #dialog {{
        width: 72;
        max-width: 90%;
        height: auto;
        max-height: 80%;
        padding: 1 2;
        background: {THEME.panel};
        border: round {THEME.primary};
    }}
    SelectScreen #dialog-title {{
        color: {THEME.primary};
        text-style: bold;
        padding: 0 0 1 0;
    }}
    SelectScreen OptionList {{
        background: {THEME.panel};
        border: none;
        height: auto;
        max-height: 20;
    }}
    SelectScreen OptionList > .option-list--option-highlighted {{
        background: {THEME.primary};
        color: {THEME.bg};
    }}
    """

    BINDINGS = [
        Binding("ctrl+c", "interrupt", "Interrupt / Quit", priority=True, show=True),
        Binding("ctrl+l", "redraw", "Redraw", show=False),
        Binding("ctrl+u", "clear_composer", "Clear input", show=False),
        Binding("down", "nav_down", show=False, priority=True),
        Binding("up", "nav_up", show=False, priority=True),
        Binding("tab", "palette_complete", show=False, priority=True),
        Binding("escape", "escape", show=False, priority=True),
        Binding("enter", "palette_accept", show=False, priority=True),
    ]

    def __init__(self, session, plan) -> None:
        '''初始化会话、视图状态、线程模型信息、输入历史和流式交互标记。'''
        super().__init__()
        self.session = session
        self.plan = plan
        self.state = initial_state()
        self._conv_thread_id: str | None = None
        self._model = ""
        self._skill_names: list[str] = []
        self._skills = 0
        self._spinner_idx = 0
        self._streaming = False
        self._cancelled = False
        self._skills_meta: list[dict] = []
        self._model_override: str | None = None
        self._palette_open = False
        self._palette_items: list = []
        self._palette_index = 0
        self._history = InputHistory()
        self._transcript_dirty = False


    def compose(self) -> ComposeResult:
        '''创建页眉、滚动对话区、状态栏、命令面板和消息输入框。'''
        yield Static(id="header")
        with VerticalScroll(id="scroll"):
            yield Static(id="transcript")
        yield Static(id="status")
        yield Static(id="palette")
        yield ComposerInput(placeholder="Message DeerFlow…   ( / for commands )", id="composer")

    def on_mount(self) -> None:
        '''加载模型与技能信息、刷新界面、启动定时刷新并处理初始消息。'''
        self._load_session_info()
        self._refresh_all()
        self.set_interval(0.1, self._tick_spinner)
        self.set_interval(0.06, self._flush_transcript)
        self.query_one("#composer", Input).focus()
        if self.plan and getattr(self.plan, "message", None):
            self._send_to_agent(self.plan.message)


    def _load_session_info(self) -> None:
        '''解析当前线程、默认模型和启用技能；各查询失败时为界面提供空默认值。'''
        self._conv_thread_id = self.session.resolve_thread(self.plan) if self.plan else None
        client = self.session.client
        try:
            models = client.list_models().get("models", [])
            self._model = next((m.get("display_name") or m.get("name") for m in models if m.get("name")), "")
        except Exception:  # noqa: BLE001 - header is best-effort
            self._model = ""
        try:
            skills = client.list_skills(enabled_only=True).get("skills", [])
            self._skills_meta = [s for s in skills if s.get("name")]
            self._skill_names = [s["name"] for s in self._skills_meta]
            self._skills = len(self._skill_names)
        except Exception:  # noqa: BLE001
            self._skills_meta = []
            self._skill_names = []
            self._skills = 0


    def on_input_submitted(self, event: Input.Submitted) -> None:
        '''提交输入框内容，记录历史并分派斜杠命令或代理消息。'''
        text = event.value.strip()
        event.input.value = ""
        self._close_palette()
        if not text:
            return
        self._history.add(text)
        self._handle_submit(text)

    def on_input_changed(self, event: Input.Changed) -> None:
        '''根据未完成的斜杠输入更新命令候选列表。'''
        value = event.value
        if value.startswith("/") and " " not in value:
            from .command_registry import build_registry, filter_commands

            items = filter_commands(build_registry(self._skills_meta), value[1:])
            self._palette_index = 0
            self._open_palette(items)
        else:
            self._close_palette()


    def check_action(self, action: str, parameters):  # noqa: D401 - Textual hook
        '''控制快捷键是否由主界面处理，避免与模态弹窗和输入框提交冲突。'''
        custom = {"nav_up", "nav_down", "palette_complete", "palette_accept", "escape"}
        if action in custom:
            if len(self.screen_stack) > 1:
                return None
            if action in {"nav_up", "nav_down", "palette_complete", "escape"}:
                return True
            return True if self._palette_open else None
        return True

    def action_nav_up(self) -> None:
        '''向上移动命令候选项或读取更早的输入历史。'''
        if self._palette_open:
            self.action_palette_up()
        else:
            self._history_move(self._history.up(self.query_one("#composer", Input).value))

    def action_nav_down(self) -> None:
        '''向下移动命令候选项或恢复较新的输入历史草稿。'''
        if self._palette_open:
            self.action_palette_down()
        else:
            self._history_move(self._history.down())

    def _history_move(self, value: str) -> None:
        '''替换输入框文本并将光标移动到文本末尾。'''
        composer = self.query_one("#composer", Input)
        composer.value = value
        composer.cursor_position = len(value)

    def _open_palette(self, items: list) -> None:
        '''记录并显示命令候选项，同时限制选中索引在有效范围内。'''
        if not items:
            self._close_palette()
            return
        self._palette_items = items
        self._palette_index = min(self._palette_index, len(items) - 1)
        self._palette_open = True
        palette = self.query_one("#palette", Static)
        palette.add_class("open")
        self._render_palette()

    def _close_palette(self) -> None:
        '''关闭并重置命令面板及其候选项。'''
        if not self._palette_open and not self._palette_items:
            return
        self._palette_open = False
        self._palette_items = []
        self._palette_index = 0
        self.query_one("#palette", Static).remove_class("open")

    def _render_palette(self) -> None:
        '''使用终端渲染器刷新命令候选面板内容。'''
        from .render import render_palette

        self.query_one("#palette", Static).update(render_palette(self._palette_items, self._palette_index))

    def _current_palette_item(self):
        '''返回当前高亮的命令或技能候选项。'''
        if 0 <= self._palette_index < len(self._palette_items):
            return self._palette_items[self._palette_index]
        return None

    def action_palette_down(self) -> None:
        '''向下移动候选项高亮，但不越过列表末尾。'''
        if self._palette_items:
            self._palette_index = min(self._palette_index + 1, len(self._palette_items) - 1)
            self._render_palette()

    def action_palette_up(self) -> None:
        '''向上移动候选项高亮，但不越过列表开头。'''
        if self._palette_items:
            self._palette_index = max(self._palette_index - 1, 0)
            self._render_palette()

    def action_palette_complete(self) -> None:
        '''命令面板打开时将当前候选填入输入框，未打开时保留焦点。'''
        if self._palette_open:
            self._fill_from_palette()

    def action_palette_accept(self) -> None:
        '''接受当前候选；技能仅填入名称供继续输入，内置命令立即执行。'''
        item = self._current_palette_item()
        if item is None:
            return
        if getattr(item, "category", "") == "skill":
            self._fill_from_palette()
            return
        self._close_palette()
        self.query_one("#composer", Input).value = ""
        self._handle_submit(f"/{item.name}")

    def _fill_from_palette(self) -> None:
        '''将选中候选填为斜杠输入并将光标置于命令参数位置。'''
        item = self._current_palette_item()
        if item is None:
            return
        composer = self.query_one("#composer", Input)
        composer.value = f"/{item.name} "
        composer.cursor_position = len(composer.value)
        self._close_palette()

    def _handle_submit(self, text: str) -> None:
        '''解析提交内容，执行内置命令、提示未知命令或发送文本与技能请求。'''
        from .command_registry import resolve

        res = resolve(text, skills=self._skill_names)
        if res.kind == "builtin":
            self._handle_builtin(res.name, res.args)
            return
        if res.kind == "unknown":
            self._dispatch(SystemMessage(f"Unknown command /{res.name}. Try /help.", tone="error"))
            return
        self._send_to_agent(text)

    def _handle_builtin(self, name: str, args: str) -> None:
        '''执行退出、帮助、线程、模型、目标、技能、工具及状态查询等内置命令。'''
        if name == "quit":
            self.exit()
        elif name == "help":
            self._dispatch(SystemMessage(_HELP_TEXT))
        elif name == "new":
            self._conv_thread_id = None
            self.state = initial_state()
            self._dispatch(SystemMessage("Started a new thread."))
        elif name == "clear":
            self._dispatch(ClearRows())
        elif name == "model":
            self._open_model_picker()
        elif name in {"threads", "switch"}:
            self._open_thread_switcher()
        elif name == "resume":
            self._resume_thread(args)
        elif name == "goal":
            self._handle_goal(args)
        elif name == "skills":
            self._show_skills()
        elif name == "mcp":
            self._show_mcp()
        elif name == "memory":
            self._show_memory()
        elif name == "usage":
            self._show_usage()
        elif name == "config":
            self._show_config()
        elif name == "tools":
            self._dispatch(SystemMessage("Tools are listed in the agent's runtime; use /mcp for MCP servers."))
        elif name == "uploads":
            self._show_uploads()
        elif name == "artifacts":
            self._dispatch(SystemMessage("Artifacts appear inline as the agent writes them.", tone="info"))
        elif name == "details":
            self._dispatch(SystemMessage("Verbose activity is always shown in this build.", tone="info"))
        else:
            self._dispatch(SystemMessage(f"/{name} is not available yet.", tone="info"))


    def _open_model_picker(self) -> None:
        '''从服务端加载模型列表并显示选择弹窗，随后更新当前模型覆盖值。'''
        try:
            models = self.session.client.list_models().get("models", [])
        except Exception:  # noqa: BLE001
            models = []
        options = [(m["name"], (m.get("display_name") or m["name"])) for m in models if m.get("name")]
        if not options:
            self._dispatch(SystemMessage("No models configured.", tone="error"))
            return

        def on_choice(choice: str | None) -> None:
            '''将用户选择的模型设为当前会话覆盖值并刷新界面。'''
            if choice:
                self._model_override = choice
                self._model = choice
                self._dispatch(SystemMessage(f"Model set to {choice}."))
                self._refresh_header()

        self.push_screen(SelectScreen("Select model", options), on_choice)

    def _open_thread_switcher(self) -> None:
        '''加载近期线程并显示选择弹窗供用户恢复会话。'''
        try:
            threads = self.session.recent_threads(limit=20)
        except Exception:  # noqa: BLE001
            threads = []
        options: list[tuple[str, str]] = []
        for thread in threads:
            tid = thread.get("thread_id")
            if not tid:
                continue
            title = thread.get("title") or "untitled"
            options.append((tid, f"{title}   ·   {tid[:8]}"))
        if not options:
            self._dispatch(SystemMessage("No saved threads yet."))
            return

        def on_choice(choice: str | None) -> None:
            '''将所选线程切换为当前会话。'''
            if choice:
                self._switch_to_thread(choice)

        self.push_screen(SelectScreen("Resume thread", options), on_choice)

    def _resume_thread(self, ref: str) -> None:
        '''按线程标识或标题恢复线程；未提供标识时打开线程选择器。'''
        ref = ref.strip()
        if not ref:
            self._open_thread_switcher()
            return
        self._switch_to_thread(self.session.resolve_ref(ref))

    def _switch_to_thread(self, thread_id: str) -> None:
        '''切换活动线程、清空当前界面记录并刷新线程标识。'''
        self._conv_thread_id = thread_id
        self.state = initial_state()
        self._dispatch(SystemMessage(f"Resumed thread {thread_id[:8]}."))
        self._refresh_header()

    def _handle_goal(self, args: str) -> None:
        '''解析目标命令并读取、清除或设置当前线程目标。'''
        command = parse_goal_command(args)

        if command.kind == "status":
            if not self._conv_thread_id:
                self._dispatch(SystemMessage("No active goal."))
                return
            try:
                goal = self.session.client.get_goal(self._conv_thread_id).get("goal")
            except Exception:  # noqa: BLE001
                self._dispatch(SystemMessage("Could not read goal.", tone="error"))
                return
            if not goal:
                self._dispatch(SystemMessage("No active goal."))
                return
            self._dispatch(SystemMessage(f"Goal: {goal.get('objective')}"))
            return

        if command.kind == "clear":
            if self._conv_thread_id:
                try:
                    self.session.client.clear_goal(self._conv_thread_id)
                except Exception:  # noqa: BLE001
                    self._dispatch(SystemMessage("Could not clear goal.", tone="error"))
                    return
            self._dispatch(SystemMessage("Goal cleared."))
            return

        if self._conv_thread_id is None:
            self._conv_thread_id = str(uuid.uuid4())
            self._refresh_header()
        try:
            goal = self.session.client.set_goal(self._conv_thread_id, command.objective).get("goal")
        except Exception:  # noqa: BLE001
            self._dispatch(SystemMessage("Could not set goal.", tone="error"))
            return
        self._dispatch(SystemMessage(f"Goal set: {goal.get('objective') if goal else command.objective}"))

    def _show_skills(self) -> None:
        '''在对话记录中列出当前启用的技能名称。'''
        names = ", ".join(self._skill_names) or "none"
        self._dispatch(SystemMessage(f"Enabled skills ({self._skills}): {names}"))

    def _show_mcp(self) -> None:
        '''查询并展示各模型上下文协议服务器的启用状态。'''
        try:
            servers = self.session.client.get_mcp_config().get("mcp_servers", {})
        except Exception:  # noqa: BLE001
            self._dispatch(SystemMessage("Could not read MCP config.", tone="error"))
            return
        if not servers:
            self._dispatch(SystemMessage("No MCP servers configured."))
            return
        lines = [f"{name}: {'on' if cfg.get('enabled') else 'off'}" for name, cfg in servers.items()]
        self._dispatch(SystemMessage("MCP servers — " + "  ·  ".join(lines)))

    def _show_memory(self) -> None:
        '''查询并概览长期记忆事实数量及当前关注摘要。'''
        try:
            data = self.session.client.get_memory()
        except Exception:  # noqa: BLE001
            self._dispatch(SystemMessage("Could not read memory.", tone="error"))
            return
        facts = data.get("facts", []) if isinstance(data, dict) else []
        top = (data.get("topOfMind") if isinstance(data, dict) else "") or "—"
        self._dispatch(SystemMessage(f"Memory: {len(facts)} facts · top of mind: {top}"))

    def _show_usage(self) -> None:
        '''展示当前线程已记录的令牌用量字段。'''
        usage = self.state.usage or {}
        if not usage:
            self._dispatch(SystemMessage("No token usage recorded yet."))
            return
        parts = ", ".join(f"{k}={v}" for k, v in usage.items())
        self._dispatch(SystemMessage(f"Token usage — {parts}"))

    def _show_config(self) -> None:
        '''显示当前工作目录和界面选用的模型。'''
        import os

        self._dispatch(SystemMessage(f"cwd: {os.getcwd()}   model: {self._model or 'default'}"))

    def _show_uploads(self) -> None:
        '''列出当前线程的上传文件名称及总数。'''
        if not self._conv_thread_id:
            self._dispatch(SystemMessage("Start a thread before listing uploads."))
            return
        try:
            uploads = self.session.client.list_uploads(self._conv_thread_id).get("files", [])
        except Exception:  # noqa: BLE001
            self._dispatch(SystemMessage("Could not list uploads.", tone="error"))
            return
        if not uploads:
            self._dispatch(SystemMessage("No uploads in this thread."))
            return
        names = ", ".join(f.get("filename", "?") for f in uploads)
        self._dispatch(SystemMessage(f"Uploads ({len(uploads)}): {names}"))


    def _send_to_agent(self, text: str) -> None:
        '''确保当前没有其他运行后创建线程标识、更新界面并启动后台代理流。'''
        if self._streaming:
            self._dispatch(SystemMessage("Still working — wait for the current run to finish.", tone="info"))
            return
        if self._conv_thread_id is None:
            self._conv_thread_id = str(uuid.uuid4())
        self._cancelled = False
        self._dispatch(UserSubmitted(text))
        self.run_worker(
            partial(self._stream_worker, text, self._conv_thread_id),
            thread=True,
            exclusive=True,
            group="agent",
        )

    def _stream_worker(self, text: str, thread_id: str) -> None:
        '''在后台消费代理流事件并投递至界面线程；成功完成后保存线程标题。'''
        kwargs: dict = {}
        if self._model_override:
            kwargs["model_name"] = self._model_override

        writer = getattr(self.session, "writer", None)
        if writer is not None:
            writer.ensure_created(thread_id, assistant_id="lead-agent", metadata={"source": "tui"})

        latest_title: str | None = None
        for action in stream_actions(self.session.client, text, thread_id=thread_id, **kwargs):
            if self._cancelled:
                break
            if isinstance(action, ThreadTitle):
                latest_title = action.title
            self.call_from_thread(self._on_action, action)

        if writer is not None and latest_title and not self._cancelled:
            writer.set_title(thread_id, latest_title)

    def _on_action(self, action) -> None:
        '''归约单个运行事件并更新流状态、对话显示和底部状态栏。'''
        self.state = reduce(self.state, action)
        if isinstance(action, RunStarted):
            self._streaming = True
            self._transcript_dirty = True
        elif isinstance(action, RunEnded):
            self._streaming = False
            self._transcript_dirty = False
            self._refresh_transcript()
        else:
            self._transcript_dirty = True
        self._refresh_status()

    def _flush_transcript(self) -> None:
        '''合并短时间内积累的流式文本刷新，减少终端重复渲染。'''
        if self._transcript_dirty:
            self._transcript_dirty = False
            self._refresh_transcript()


    def action_interrupt(self) -> None:
        '''中断正在运行的任务；没有任务时退出终端界面。'''
        if self._streaming:
            self._interrupt_run()
        else:
            self.exit()

    def action_escape(self) -> None:
        '''命令面板打开时关闭它，运行中则请求中断当前任务。'''
        if self._palette_open:
            self._close_palette()
        elif self._streaming:
            self._interrupt_run()

    def _interrupt_run(self) -> None:
        '''取消后台代理工作组并将当前视图状态改为运行结束。'''
        self._cancelled = True
        self.workers.cancel_group(self, "agent")
        self._streaming = False
        self.state = reduce(self.state, RunEnded())
        self._dispatch(SystemMessage("Interrupted.", tone="info"))

    def action_redraw(self) -> None:
        '''重新计算终端布局并刷新所有可见区域。'''
        self.refresh(layout=True)
        self._refresh_all()

    def action_clear_composer(self) -> None:
        '''清空消息输入框。'''
        self.query_one("#composer", Input).value = ""


    def _dispatch(self, action) -> None:
        '''归约本地界面动作，并立即更新对话记录和状态栏。'''
        self.state = reduce(self.state, action)
        self._refresh_transcript()
        self._refresh_status()

    def _tick_spinner(self) -> None:
        '''运行期间推进加载动画，并重绘状态栏。'''
        if self._streaming:
            self._spinner_idx = (self._spinner_idx + 1) % len(SYMBOLS["spinner"])
            self._refresh_status()

    def _thread_label(self) -> str:
        '''生成当前线程的短标签；尚未创建线程时显示新线程状态。'''
        if not self._conv_thread_id:
            return "new thread"
        return f"thread {self._conv_thread_id[:8]}"

    def _refresh_all(self) -> None:
        '''依次刷新页眉、对话记录和运行状态。'''
        self._refresh_header()
        self._refresh_transcript()
        self._refresh_status()

    def _refresh_header(self) -> None:
        '''刷新页眉中的模型、线程、工作目录和技能数量。'''
        import os

        self.query_one("#header", Static).update(
            render_header(
                model=self._model,
                thread_label=self._thread_label(),
                cwd=os.getcwd(),
                skills=self._skills,
            )
        )

    def _refresh_transcript(self) -> None:
        '''渲染对话行并自动滚动到最新内容。'''
        self.query_one("#transcript", Static).update(render_transcript(self.state))
        self.query_one("#scroll", VerticalScroll).scroll_end(animate=False)

    def _refresh_status(self) -> None:
        '''刷新流式状态、模型、线程和加载动画信息。'''
        spinner = SYMBOLS["spinner"][self._spinner_idx] if self._streaming else ""
        self.query_one("#status", Static).update(render_status(self.state, model=self._model, thread_label=self._thread_label(), spinner=spinner))


def run_tui(plan) -> int:
    '''创建终端会话并运行界面，退出后确保数据库和后台线程资源关闭。'''
    from .session import open_session

    session = open_session()
    app = DeerFlowTUI(session, plan)
    try:
        app.run()
    finally:
        session.close()
    return 0
