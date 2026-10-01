'''通过事件循环桥接异步 BoxLite 虚拟机，为同步沙箱接口提供命令、文件和搜索操作。

``BoxliteBox`` — DeerFlow :class:`Sandbox` backed by a BoxLite micro-VM.

DeerFlow's ``Sandbox`` contract is synchronous; BoxLite's SDK is async-native and
its box handles are event-loop-affine. The provider (:mod:`.provider`) owns one
private asyncio loop on a daemon thread and injects a ``run`` callable that
marshals each coroutine onto it via ``run_coroutine_threadsafe`` — so every op
runs on the loop the box was started on, and stays safe no matter which
``asyncio.to_thread`` worker DeerFlow invokes us from.

Every operation is a shell command run inside the box (``cat`` / ``find`` /
``grep`` / chunked ``base64``), parsed with the shared ``deerflow.sandbox.search``
helpers — the same exec-driven approach as ``community/e2b_sandbox``. Commands
use only busybox-portable flags so any OCI image works.
'''

from __future__ import annotations

import base64
import errno
import logging
import posixpath
import re
import shlex
import threading
from typing import TYPE_CHECKING, TypeVar

from deerflow.config.paths import VIRTUAL_PATH_PREFIX
from deerflow.sandbox.sandbox import Sandbox, _validate_extra_env
from deerflow.sandbox.search import GrepMatch, path_matches, should_ignore_path, truncate_line

if TYPE_CHECKING:
    from collections.abc import Callable

    from boxlite import SimpleBox

logger = logging.getLogger(__name__)

T = TypeVar("T")

_MAX_DOWNLOAD_SIZE = 100 * 1024 * 1024  # 100 MB
_B64_CHUNK = 60000


class BoxliteBox(Sandbox):
    '''把同步沙箱操作转发到提供方管理的虚拟机，并合并默认及单次调用环境变量。

    Adapter that delegates to a running BoxLite ``SimpleBox``.

        Args:
            id: DeerFlow-side sandbox id (the BoxLite box id).
            box: A started async ``SimpleBox``. The provider owns its lifecycle; this
                adapter stops it on :meth:`close`.
            run: Runs a coroutine on the provider's private loop, returning its result
                (blocking the caller thread).
            default_env: Static environment merged into every command, overridden by
                per-call ``env`` (request-scoped secrets).
    '''

    TERMINAL_ERROR_MARKERS = (
        "vsock",
        "disconnected",
        "broken pipe",
        "connection reset",
        "connection refused",
        "no such box",
        "box has been stopped",
        "engine reported an error",
    )
    RETRYABLE_ERROR_MARKERS = (
        "transport not ready",
        "retry later",
        "temporarily unavailable",
        "resource busy",
    )

    def __init__(
        self,
        id: str,
        box: SimpleBox,
        run: Callable[..., T],
        *,
        default_env: dict[str, str] | None = None,
        on_terminal_failure: Callable[[str, str], None] | None = None,
    ) -> None:
        '''保存虚拟机、异步调用桥和环境变量，并初始化关闭状态与并发锁。'''
        super().__init__(id)
        self._box = box
        self._run = run
        self._default_env = dict(default_env or {})
        self._on_terminal_failure = on_terminal_failure
        self._lock = threading.Lock()
        self._closed = False

    @classmethod
    def _is_terminal_box_failure(cls, error: Exception) -> bool:
        '''区分虚拟机终止类连接故障和可稍后重试的暂时性错误。'''
        if isinstance(error, (BrokenPipeError, ConnectionError, EOFError)):
            return True
        if not isinstance(error, RuntimeError | OSError):
            return False
        msg = str(error).lower()
        if any(marker in msg for marker in cls.RETRYABLE_ERROR_MARKERS):
            return False
        return any(marker in msg for marker in cls.TERMINAL_ERROR_MARKERS)


    def _exec(
        self,
        *argv: str,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ):
        '''在虚拟机上运行命令，并在终止性故障时通知提供方清理实例。'''
        try:
            with self._lock:
                if self._closed:
                    raise RuntimeError("sandbox has been closed")
                box = self._box
            return self._run(box.exec(*argv, env=env, timeout=timeout), timeout=timeout)
        except Exception as e:
            if self._on_terminal_failure is not None and self._is_terminal_box_failure(e):
                try:
                    self._on_terminal_failure(self.id, str(e))
                except Exception:
                    logger.exception("Terminal BoxLite failure callback errored for %s", self.id)
            raise

    def _sh(
        self,
        script: str,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ):
        '''通过虚拟机内的登录 Shell 执行命令文本。'''
        return self._exec("sh", "-lc", script, env=env, timeout=timeout)

    def close(self) -> None:
        '''幂等关闭沙箱并请求停止虚拟机；停止失败仅记录警告。'''
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._run(self._box.stop())
        except Exception as e:
            logger.warning("Error stopping BoxLite box %s: %s", self.id, e)

    @property
    def is_closed(self) -> bool:
        '''在线程锁保护下返回沙箱是否已经关闭。'''
        with self._lock:
            return self._closed


    @staticmethod
    def _guard_traversal(path: str) -> str:
        '''拒绝空路径和任何父目录片段，防止路径越界访问。'''
        if not path:
            raise ValueError("path must be a non-empty string")
        normalized = path.replace("\\", "/")
        for segment in normalized.split("/"):
            if segment == "..":
                raise PermissionError(f"Access denied: path traversal detected in '{path}'")
        return normalized

    def _resolve_path(self, path: str) -> str:
        '''保留已映射到虚拟机根目录的虚拟路径，仅执行目录穿越检查。'''
        return self._guard_traversal(path)


    def execute_command(
        self,
        command: str,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> str:
        '''在虚拟机中执行 Shell 命令，合并环境变量并将标准输出和错误输出整理为文本。

        Run ``command`` through a shell in the box and return its output.

                DeerFlow passes a bash command *string*; BoxLite's ``exec`` takes argv, so
                it runs through ``sh -lc``. Per-call ``env`` is layered over the static
                config environment and scoped to this command only.

                *timeout* bounds both layers: BoxLite's SDK ``exec(timeout=...)`` handles
                command timeout inside the VM, and the event-loop bridge receives the
                same value so ``run_coroutine_threadsafe(...).result(timeout)`` cannot
                block the caller forever if the SDK future itself never resolves.
        '''
        _validate_extra_env(env)
        if self.is_closed:
            return "Error: sandbox has been closed"
        merged_env = {**self._default_env, **(env or {})} or None
        try:
            result = self._exec("sh", "-lc", command, env=merged_env, timeout=timeout)
        except Exception as e:
            logger.error("Failed to execute command in BoxLite box %s: %s", self.id, e)
            return f"Error: {e}"

        stdout = result.stdout or ""
        stderr = result.stderr or ""
        if stdout and stderr:
            output = f"{stdout}\n{stderr}"
        else:
            output = stdout or stderr
        if result.exit_code not in (0, None) and not output:
            output = f"Command exited with code {result.exit_code}"
        return output if output else "(no output)"


    def read_file(self, path: str) -> str:
        '''读取虚拟机中的指定文件，失败时返回可供代理理解的错误文本。'''
        resolved = self._resolve_path(path)
        try:
            r = self._exec("cat", "--", resolved)
        except Exception as e:
            logger.error("read_file %s failed: %s", resolved, e)
            return f"Error: {e}"
        if r.exit_code not in (0, None):
            return f"Error: {(r.stderr or '').strip() or 'cannot read file'}"
        return r.stdout or ""

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        '''将 UTF-8 文本写入指定路径，可选择追加到已有内容后。'''
        self._write_bytes(self._resolve_path(path), content.encode("utf-8"), append=append)

    def update_file(self, path: str, content: bytes) -> None:
        '''用给定字节内容覆盖虚拟机中的指定文件。'''
        self._write_bytes(self._resolve_path(path), content, append=False)

    def _write_bytes(self, resolved: str, data: bytes, *, append: bool) -> None:
        '''按 Base64 分块传输文件内容，先创建父目录并支持覆盖或追加写入。'''
        parent = posixpath.dirname(resolved)
        if parent:
            mk = self._sh(f"mkdir -p {shlex.quote(parent)}")
            if mk.exit_code not in (0, None):
                raise OSError(f"cannot create parent of '{resolved}': {(mk.stderr or '').strip()}")

        b64 = base64.b64encode(data).decode("ascii")
        if not b64:
            r = self._sh(f": {'>>' if append else '>'} {shlex.quote(resolved)}")
            if r.exit_code not in (0, None):
                raise OSError(f"write '{resolved}' failed: {(r.stderr or '').strip()}")
            return

        first = True
        for i in range(0, len(b64), _B64_CHUNK):
            chunk = b64[i : i + _B64_CHUNK]
            redir = ">>" if (append or not first) else ">"
            r = self._sh(f"printf %s {shlex.quote(chunk)} | base64 -d {redir} {shlex.quote(resolved)}")
            if r.exit_code not in (0, None):
                raise OSError(f"write '{resolved}' failed: {(r.stderr or '').strip()}")
            first = False

    def download_file(self, path: str) -> bytes:
        '''仅下载用户数据虚拟目录内且未超过大小限制的文件，并解码为原始字节。'''
        normalized = self._guard_traversal(path)
        stripped = normalized.lstrip("/")
        allowed = VIRTUAL_PATH_PREFIX.lstrip("/")
        if stripped != allowed and not stripped.startswith(f"{allowed}/"):
            raise PermissionError(f"Access denied: path must be under '{VIRTUAL_PATH_PREFIX}': '{path}'")

        size_r = self._sh(f"wc -c < {shlex.quote(normalized)}")
        if size_r.exit_code not in (0, None):
            raise OSError(f"cannot read '{path}' from box: {(size_r.stderr or '').strip() or 'not found'}")
        try:
            size = int((size_r.stdout or "0").strip() or "0")
        except ValueError:
            size = 0
        if size > _MAX_DOWNLOAD_SIZE:
            raise OSError(errno.EFBIG, f"File exceeds maximum download size of {_MAX_DOWNLOAD_SIZE} bytes", path)

        r = self._sh(f"base64 {shlex.quote(normalized)}")
        if r.exit_code not in (0, None):
            raise OSError(f"cannot read '{path}' from box: {(r.stderr or '').strip()}")
        try:
            return base64.b64decode("".join((r.stdout or "").split()))
        except Exception as e:
            raise OSError(f"failed to decode '{path}' from box: {e}") from e

    def list_dir(self, path: str, max_depth: int = 2) -> list[str]:
        '''使用 find 列出指定目录深度内的文件和目录，最多返回五百项。'''
        resolved = self._resolve_path(path)
        r = self._sh(f"find {shlex.quote(resolved)} -maxdepth {int(max_depth)} \\( -type f -o -type d \\) 2>/dev/null | head -500")
        return [line.strip() for line in (r.stdout or "").splitlines() if line.strip()]

    def glob(
        self,
        path: str,
        pattern: str,
        *,
        include_dirs: bool = False,
        max_results: int = 200,
    ) -> tuple[list[str], bool]:
        '''枚举指定目录下匹配相对路径模式的文件，并返回是否达到结果上限。'''
        resolved = self._resolve_path(path)
        types = ("f", "d") if include_dirs else ("f",)
        type_expr = " -o ".join(f"-type {t}" for t in types)
        hard_limit = max(max_results * 4, max_results + 50)
        r = self._sh(f"find {shlex.quote(resolved)} \\( {type_expr} \\) -print 2>/dev/null | head -{hard_limit}")

        matches: list[str] = []
        root = resolved.rstrip("/") or "/"
        root_prefix = root if root == "/" else f"{root}/"
        for entry in (r.stdout or "").splitlines():
            entry = entry.strip()
            if not entry or (entry != root and not entry.startswith(root_prefix)):
                continue
            if should_ignore_path(entry):
                continue
            rel_path = entry[len(root) :].lstrip("/")
            if not rel_path:
                continue
            if path_matches(pattern, rel_path):
                matches.append(entry)
                if len(matches) >= max_results:
                    return matches, True
        return matches, False

    def grep(
        self,
        path: str,
        pattern: str,
        *,
        glob: str | None = None,
        literal: bool = False,
        case_sensitive: bool = False,
        max_results: int = 100,
    ) -> tuple[list[GrepMatch], bool]:
        '''在虚拟机文件中递归搜索文本，将匹配行转换为统一结果并应用路径过滤。'''
        if not literal:
            re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)

        resolved = self._resolve_path(path)
        flags = ["-r", "-n", "-I"]
        if not case_sensitive:
            flags.append("-i")
        flags.append("-F" if literal else "-E")
        total_cap = max(max_results * 4, max_results + 50)
        cmd = "grep " + " ".join(flags) + f" -e {shlex.quote(pattern)} {shlex.quote(resolved)} 2>/dev/null | head -{total_cap}"
        r = self._sh(cmd)

        include = glob.split("/")[-1] if glob else None
        matches: list[GrepMatch] = []
        truncated = False
        for raw in (r.stdout or "").splitlines():
            try:
                file_path, line_no_str, line_text = raw.split(":", 2)
            except ValueError:
                continue
            try:
                line_number = int(line_no_str)
            except ValueError:
                continue
            if should_ignore_path(file_path):
                continue
            if include and not path_matches(include, posixpath.basename(file_path)):
                continue
            matches.append(GrepMatch(path=file_path, line_number=line_number, line=truncate_line(line_text)))
            if len(matches) >= max_results:
                truncated = True
                break
        return matches, truncated
