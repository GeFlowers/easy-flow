'''通过 E2B 远程代码执行服务实现 DeerFlow 沙箱的命令和文件操作。'''

from __future__ import annotations

import errno
import logging
import re
import shlex
import threading

from e2b_code_interpreter import Sandbox as E2BClientSandbox

from deerflow.config.paths import VIRTUAL_PATH_PREFIX
from deerflow.sandbox.sandbox import Sandbox, _validate_extra_env
from deerflow.sandbox.search import GrepMatch, path_matches, should_ignore_path, truncate_line

logger = logging.getLogger(__name__)

_MAX_DOWNLOAD_SIZE = 100 * 1024 * 1024  # 100 MB

DEFAULT_E2B_HOME_DIR = "/home/user"

_E2B_NOT_FOUND_SIGNATURES = (
    "sandbox was not found",
    "sandbox not found",
    "paused sandbox",
)


def _is_sandbox_gone_error(exc: BaseException) -> bool:
    '''根据服务端错误文本判断远程沙箱是否已不存在或已被关闭。'''
    msg = str(exc).lower()
    return any(sig in msg for sig in _E2B_NOT_FOUND_SIGNATURES)


class E2BSandbox(Sandbox):
    '''把 E2B 客户端对象适配为 DeerFlow 沙箱接口，并处理远程会话失效。

    DeerFlow Sandbox adapter that delegates to an e2b cloud sandbox.

        Args:
            id: DeerFlow-side sandbox id (used as cache key in the provider).
            client: A live ``e2b_code_interpreter.Sandbox`` (sync) instance.
                The caller owns the connection and is responsible for ``kill()``;
                this wrapper only calls ``close()`` on its host-side HTTP client
                during release.
            home_dir: Directory inside the sandbox that backs the
                ``VIRTUAL_PATH_PREFIX`` (``/mnt/user-data``) prefix.  Defaults to
                :data:`DEFAULT_E2B_HOME_DIR`.
    '''

    def __init__(
        self,
        id: str,
        client: E2BClientSandbox,
        *,
        home_dir: str = DEFAULT_E2B_HOME_DIR,
    ) -> None:
        '''保存远程沙箱客户端、沙箱标识和可选路径映射信息。'''
        super().__init__(id)
        self._client = client
        self._home_dir = home_dir.rstrip("/") or "/"
        self._lock = threading.Lock()
        self._closed = False
        self._dead = False


    @property
    def client(self) -> E2BClientSandbox:
        '''返回底层 E2B 沙箱客户端。'''
        return self._client

    @property
    def home_dir(self) -> str:
        '''返回远程沙箱中用户主目录路径。'''
        return self._home_dir

    @property
    def sandbox_id(self) -> str:
        '''返回服务端沙箱标识，该标识与 DeerFlow 内部缓存键不同。

        e2b-side sandbox id (different from DeerFlow's ``self.id`` cache key).'''
        return getattr(self._client, "sandbox_id", self.id)

    def close(self) -> None:
        '''关闭远程沙箱会话并释放服务端资源。'''
        with self._lock:
            if self._closed:
                return
            self._closed = True
            client = self._client
            self._client = None

        if client is None:
            return

        for closer in (
            getattr(client, "close", None),
            getattr(getattr(client, "_transport", None), "close", None),
        ):
            if callable(closer):
                try:
                    closer()
                except Exception as e:
                    logger.warning("Error closing E2BSandbox %s: %s", self.id, e)
                return

    def _resolve_path(self, path: str) -> str:
        '''将项目虚拟路径转换为沙箱内路径，并拒绝逃逸挂载根目录的路径。

        Map DeerFlow virtual paths into the e2b sandbox filesystem.

                ``VIRTUAL_PATH_PREFIX`` (``/mnt/user-data``) is rewritten under
                :attr:`home_dir`, which acts as the remote counterpart of the
                local workspace mounted at ``/mnt/user-data``.
                Other absolute paths are returned verbatim so the sandbox can reach
                system directories (``/tmp``, ``/etc``, …) when needed.
        '''
        if not path:
            raise ValueError("path must be a non-empty string")
        normalised = path.replace("\\", "/")
        for segment in normalised.split("/"):
            if segment == "..":
                raise PermissionError(f"Access denied: path traversal detected in '{path}'")
        if normalised == VIRTUAL_PATH_PREFIX or normalised.startswith(f"{VIRTUAL_PATH_PREFIX}/"):
            tail = normalised[len(VIRTUAL_PATH_PREFIX) :].lstrip("/")
            return f"{self._home_dir}/{tail}".rstrip("/") if tail else self._home_dir
        return normalised

    def execute_command(
        self,
        command: str,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> str:
        '''在远程沙箱执行命令，应用超时和环境变量并返回标准输出与错误输出。

        Execute a shell command via ``sandbox.commands.run``.

                Returns the combined stdout/stderr.
                The lock serialises concurrent calls on the same instance
                because the e2b SDK shares a single HTTP/2 connection per sandbox.

                Args:
                    command: The command to execute.
                    env: Optional per-call environment variables (request-scoped secrets,
                        issue #3861). Validated against the POSIX env-var name rule
                        (shared with the local and AIO sandboxes) and passed through to
                        e2b as ``envs``, which are scoped to this command only and never
                        placed in the command string.
                    timeout: Optional per-call command timeout in seconds. ``None`` keeps
                        the e2b SDK default (60s).
        '''
        _validate_extra_env(env)
        with self._lock:
            client = self._client
            if client is None:
                return "Error: sandbox client has been closed"
            if self._dead:
                return "Error: e2b sandbox has been reaped by the control plane (idle timeout or explicit pause). The provider will rebuild a fresh sandbox on the next tool call."
            try:
                kwargs: dict[str, object] = {}
                if env is not None:
                    kwargs["envs"] = env
                if timeout is not None:
                    kwargs["timeout"] = timeout
                result = client.commands.run(command, **kwargs)
                stdout = getattr(result, "stdout", "") or ""
                stderr = getattr(result, "stderr", "") or ""
                exit_code = getattr(result, "exit_code", 0)
                if stdout and stderr:
                    output = f"{stdout}\n{stderr}"
                else:
                    output = stdout or stderr
                if exit_code not in (0, None) and not output:
                    output = f"Command exited with code {exit_code}"
                return output if output else "(no output)"
            except Exception as e:
                if _is_sandbox_gone_error(e):
                    self._dead = True
                logger.error("Failed to execute command in e2b sandbox: %s", e)
                return f"Error: {e}"

    @property
    def is_dead(self) -> bool:
        '''通过远程客户端状态判断沙箱是否已终止或无法继续使用。

        Whether the underlying e2b VM is known to be reaped.

                Updated lazily by ``execute_command`` and the provider's ``ping`` /
                bootstrap calls — there is no proactive heartbeat. Reading the value
                does *not* round-trip to the API.
        '''
        with self._lock:
            return self._dead

    def ping(self) -> bool:
        '''向远程服务发起轻量检查，确认沙箱仍可响应。

        Cheap health check: returns False if the e2b VM has been reaped.

                Run as ``commands.run("true")`` so successful execution implies the
                full HTTP path (auth + control plane + envd) is alive.  Sets
                ``_dead = True`` on the same "sandbox not found" signature
                :func:`_is_sandbox_gone_error` recognises so subsequent calls
                short-circuit.
        '''
        with self._lock:
            if self._dead or self._client is None:
                return False
            client = self._client
        try:
            client.commands.run("true")
            return True
        except Exception as e:
            if _is_sandbox_gone_error(e):
                with self._lock:
                    self._dead = True
                return False
            logger.warning("e2b sandbox ping raised non-fatal error: %s", e)
            return True

    def read_file(self, path: str) -> str:
        '''读取远程沙箱中的文本文件，并把服务错误转换为工具可识别的错误文本。'''
        resolved = self._resolve_path(path)
        try:
            content = self._client.files.read(resolved)
            if isinstance(content, bytes):
                return content.decode("utf-8", errors="replace")
            return content if content is not None else ""
        except Exception as e:
            logger.error("Failed to read file %s in e2b sandbox: %s", resolved, e)
            return f"Error: {e}"

    def download_file(self, path: str) -> bytes:
        '''从沙箱下载指定文件的原始字节内容。'''
        normalised = path.replace("\\", "/")
        for segment in normalised.split("/"):
            if segment == "..":
                logger.error("Refused download due to path traversal: %s", path)
                raise PermissionError(f"Access denied: path traversal detected in '{path}'")

        stripped_path = normalised.lstrip("/")
        allowed_prefix = VIRTUAL_PATH_PREFIX.lstrip("/")
        if stripped_path != allowed_prefix and not stripped_path.startswith(f"{allowed_prefix}/"):
            logger.error(
                "Refused download outside allowed directory: path=%s, allowed_prefix=%s",
                path,
                VIRTUAL_PATH_PREFIX,
            )
            raise PermissionError(f"Access denied: path must be under '{VIRTUAL_PATH_PREFIX}': '{path}'")

        resolved = self._resolve_path(path)
        with self._lock:
            client = self._client
            if client is None:
                raise RuntimeError("sandbox client has been closed")
            try:
                data = client.files.read(resolved, format="stream")
            except TypeError:
                try:
                    data = client.files.read(resolved, format="bytes")
                except Exception as e:
                    logger.error("Failed to download file %s from e2b sandbox: %s", resolved, e)
                    raise OSError(f"Failed to download file '{path}' from sandbox: {e}") from e
            except Exception as e:
                logger.error("Failed to download file %s from e2b sandbox: %s", resolved, e)
                raise OSError(f"Failed to download file '{path}' from sandbox: {e}") from e

        if data is None:
            return b""

        if isinstance(data, (bytes, bytearray)):
            if len(data) > _MAX_DOWNLOAD_SIZE:
                raise OSError(
                    errno.EFBIG,
                    f"File exceeds maximum download size of {_MAX_DOWNLOAD_SIZE} bytes",
                    path,
                )
            return bytes(data)
        if isinstance(data, str):
            encoded = data.encode("utf-8")
            if len(encoded) > _MAX_DOWNLOAD_SIZE:
                raise OSError(
                    errno.EFBIG,
                    f"File exceeds maximum download size of {_MAX_DOWNLOAD_SIZE} bytes",
                    path,
                )
            return encoded

        chunks: list[bytes] = []
        total = 0
        close = getattr(data, "close", None)
        try:
            try:
                for chunk in data:
                    if not chunk:
                        continue
                    chunk_bytes = chunk if isinstance(chunk, bytes) else bytes(chunk)
                    total += len(chunk_bytes)
                    if total > _MAX_DOWNLOAD_SIZE:
                        raise OSError(
                            errno.EFBIG,
                            f"File exceeds maximum download size of {_MAX_DOWNLOAD_SIZE} bytes",
                            path,
                        )
                    chunks.append(chunk_bytes)
            except OSError:
                raise
            except Exception as e:
                logger.error("Failed to stream file %s from e2b sandbox: %s", resolved, e)
                raise OSError(f"Failed to download file '{path}' from sandbox: {e}") from e
        finally:
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        return b"".join(chunks)

    def list_dir(self, path: str, max_depth: int = 2) -> list[str]:
        '''列出指定路径下限深度的目录项。'''
        resolved = self._resolve_path(path)
        with self._lock:
            client = self._client
            if client is None:
                return []
            try:
                result = client.commands.run(f"find {shlex.quote(resolved)} -maxdepth {int(max_depth)} \\( -type f -o -type d \\) 2>/dev/null | head -500")
                output = getattr(result, "stdout", "") or ""
                return [line.strip() for line in output.splitlines() if line.strip()]
            except Exception as e:
                logger.error("Failed to list_dir %s in e2b sandbox: %s", resolved, e)
                return []

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        '''将文本写入远程文件，可选追加到现有文件末尾。'''
        resolved = self._resolve_path(path)
        with self._lock:
            client = self._client
            if client is None:
                raise RuntimeError("sandbox client has been closed")
            try:
                if append:
                    existing = ""
                    try:
                        existing = client.files.read(resolved) or ""
                        if isinstance(existing, bytes):
                            existing = existing.decode("utf-8", errors="replace")
                    except Exception:
                        existing = ""
                    content = (existing or "") + content
                client.files.write(resolved, content)
            except Exception as e:
                logger.error("Failed to write file %s in e2b sandbox: %s", resolved, e)
                raise

    def update_file(self, path: str, content: bytes) -> None:
        '''以给定字节内容覆盖远程文件。'''
        resolved = self._resolve_path(path)
        with self._lock:
            client = self._client
            if client is None:
                raise RuntimeError("sandbox client has been closed")
            try:
                client.files.write(resolved, content)
            except Exception as e:
                logger.error("Failed to update file %s in e2b sandbox: %s", resolved, e)
                raise

    def glob(
        self,
        path: str,
        pattern: str,
        *,
        include_dirs: bool = False,
        max_results: int = 200,
    ) -> tuple[list[str], bool]:
        '''按相对路径模式筛选沙箱目录中的文件，并指示结果是否达到上限。'''
        resolved = self._resolve_path(path)
        types = "f,d" if include_dirs else "f"
        with self._lock:
            client = self._client
            if client is None:
                return [], False
            try:
                hard_limit = max(max_results * 4, max_results + 50)
                cmd = f"find {shlex.quote(resolved)} \\( " + " -o ".join(f"-type {t}" for t in types.split(",")) + f" \\) -print 2>/dev/null | head -{hard_limit}"
                result = client.commands.run(cmd)
                output = getattr(result, "stdout", "") or ""
            except Exception as e:
                logger.error("Failed to glob in e2b sandbox: %s", e)
                return [], False

        matches: list[str] = []
        root = resolved.rstrip("/") or "/"
        root_prefix = root if root == "/" else f"{root}/"
        for entry in output.splitlines():
            entry = entry.strip()
            if not entry:
                continue
            if entry != root and not entry.startswith(root_prefix):
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
        '''在远程目录递归搜索文本，支持文件模式、字面量和大小写选项。'''
        regex_source = re.escape(pattern) if literal else pattern
        re.compile(regex_source, 0 if case_sensitive else re.IGNORECASE)

        resolved = self._resolve_path(path)
        flags = ["-r", "-n", "-H", "-I"]
        if not case_sensitive:
            flags.append("-i")
        if literal:
            flags.append("-F")
        else:
            flags.append("-E")
        if glob is not None:
            include_pattern = glob.split("/")[-1] or glob
            flags.append(f"--include={include_pattern}")

        per_file_cap = max(max_results, 50)
        total_cap = max(max_results * 4, max_results + 50)
        flags.append(f"-m{per_file_cap}")

        cmd = "grep " + " ".join(flags) + f" -- {shlex.quote(regex_source)} {shlex.quote(resolved)} 2>/dev/null" + f" | head -{total_cap}"

        with self._lock:
            client = self._client
            if client is None:
                return [], False
            try:
                result = client.commands.run(cmd)
                output = getattr(result, "stdout", "") or ""
            except Exception as e:
                logger.error("Failed to grep in e2b sandbox: %s", e)
                return [], False

        matches: list[GrepMatch] = []
        truncated = False
        for raw in output.splitlines():
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
            matches.append(
                GrepMatch(
                    path=file_path,
                    line_number=line_number,
                    line=truncate_line(line_text),
                )
            )
            if len(matches) >= max_results:
                truncated = True
                break
        return matches, truncated
