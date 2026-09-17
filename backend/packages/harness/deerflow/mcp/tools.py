"""使用 langchain-mcp-adapters 加载 MCP 工具，并为 stdio 传输复用会话。"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Iterable, Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from langchain_core.tools import BaseTool, StructuredTool
from langgraph.config import get_config

from deerflow.config.extensions_config import ExtensionsConfig, resolve_effective_mcp_routing
from deerflow.config.paths import VIRTUAL_PATH_PREFIX, Paths, get_paths
from deerflow.mcp.client import build_servers_config
from deerflow.mcp.oauth import build_oauth_tool_interceptor, get_initial_oauth_headers
from deerflow.mcp.session_pool import get_session_pool
from deerflow.reflection import resolve_variable
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.tools.mcp_metadata import tag_mcp_routing, tag_mcp_tool
from deerflow.tools.sync import make_sync_tool_wrapper
from deerflow.tools.types import Runtime

logger = logging.getLogger(__name__)

# MCP tool names arrive verbatim from external (potentially hostile/compromised)
# servers. A tool name is only ever a function identifier: the provider's
# function-calling API validates it against this same charset at bind time. But
# deferred (tool_search) MCP tools are withheld from binding, so that provider
# check never runs on their names — they only ever live in the system-prompt
# string, where a crafted name (newlines, markdown, angle brackets) could forge
# framework prompt structure. Canonicalizing at the load boundary constrains
# both bound and deferred names to the same safe identifier charset, mirroring
# the load-time validation skill names get (skills/storage/skill_storage.py).
_VALID_MCP_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]+$")

# Subdirectory under the thread's workspace used as the temp dir for stdio MCP
# subprocesses. Pinning the process temp dir here (alongside its cwd) makes
# tools that write to ``os.tmpdir()`` / ``tempfile.gettempdir()`` land inside
# the mounted user-data tree, where their output is resolvable by the
# sandbox/artifact API — instead of on an unreachable host temp path.
_MCP_TMP_SUBDIR = ".mcp/tmp"

# Matches local-file references embedded in free text returned by an MCP server.
# Some servers (notably Playwright's ``browser_take_screenshot``) report saved
# files only as text/markdown links rather than ``ResourceLink`` blocks. Those
# references may be absolute paths, ``file://`` URIs, or paths relative to the
# server process cwd (e.g. ``temp/page.yml``, ``./shot.png``). Each match is
# only rewritten when it resolves to an existing file inside the thread's
# user-data tree, so an over-eager match is harmless (left untouched).
_LOCAL_PATH_IN_TEXT_RE = re.compile(r"(?:file://)?/[^\s'\"<>|*?]+|(?:\.{0,2}/|[\w.-]+/)[^\s'\"<>|*?]+")

# Trailing characters that are punctuation/markup rather than part of a path.
_TEXT_PATH_TRAILING_CHARS = ".,;:!?)]}>\"'`"

_FILE_SNAPSHOT = dict[Path, tuple[int, int]]


def _local_path_from_uri(uri: str, *, base_dir: Path | None = None) -> Path | None:
    """若 *uri* 指向本地文件则返回绝对 ``Path``，否则返回 ``None``。

    支持裸路径和 ``file://`` URI。远程 URI（``http``、``https``、``data`` 等）返回
    ``None``，以便调用方保持原样。仅在提供 *base_dir* 时解析相对路径。
    """
    if not uri:
        return None
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        raw = unquote(parsed.path)
    elif parsed.scheme == "":
        raw = uri
    else:
        return None
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        if base_dir is None:
            return None
        path = base_dir / path
    return path


def _local_uri_to_virtual_path(
    uri: str,
    *,
    thread_id: str,
    user_id: str,
    source_base_dir: Path | None = None,
) -> str | None:
    """将本地文件引用转换为 ``/mnt/user-data/...`` 虚拟路径。

    stdio MCP 服务器的工作目录和临时目录固定在线程挂载的用户数据树中（见
    ``_make_session_pool_tool``），因此其生成的文件已位于沙箱和制品 API 可服务的位置；
    仅缺少 DeerFlow 其他部分使用的虚拟路径前缀。本方法只执行确定性的主机路径到虚拟路径
    映射：不复制文件、不维护受信任根目录列表，也不暴露线程数据树外的文件。

    URI 为远程地址、无法解析、位于当前线程用户数据树外或不指向现有文件时返回 ``None``，
    调用方将保持原引用。相对引用相对于 *source_base_dir*（服务器工作目录）解析。
    """
    src = _local_path_from_uri(uri, base_dir=source_base_dir)
    if src is None:
        return None

    try:
        real = src.resolve()
    except OSError:
        return None
    if not real.is_file():
        return None

    try:
        user_data_root = get_paths().sandbox_user_data_dir(thread_id, user_id=user_id).resolve()
    except OSError:
        return None

    try:
        relative = real.relative_to(user_data_root)
    except ValueError:
        # The file lives outside this thread's user-data mount; we cannot
        # express it as a virtual path, so leave the original reference as-is.
        logger.debug("MCP path rewrite skipped outside user-data tree: %s", real)
        return None

    virtual_path = f"{VIRTUAL_PATH_PREFIX}/{relative.as_posix()}"
    logger.debug("MCP path rewrite: %s -> %s", real, virtual_path)
    return virtual_path


def _snapshot_workspace_files(root: Path) -> _FILE_SNAPSHOT:
    """返回 *root* 下普通文件的轻量级快照。"""
    snapshot: _FILE_SNAPSHOT = {}
    if not root.exists():
        return snapshot

    try:
        candidates = root.rglob("*")
        for path in candidates:
            try:
                stat = path.stat()
            except OSError:
                continue
            if path.is_file():
                snapshot[path] = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return snapshot
    return snapshot


def _changed_workspace_files(root: Path, before: _FILE_SNAPSHOT) -> list[Path]:
    """返回 *root* 下相对 *before* 新建或已修改的文件。"""
    after = _snapshot_workspace_files(root)
    return [path for path, signature in after.items() if before.get(path) != signature]


def _prepare_stdio_workspace(paths: Paths, *, thread_id: str, user_id: str) -> tuple[Path, Path, _FILE_SNAPSHOT]:
    """为固定工作目录的 stdio MCP 子进程准备线程工作区。

    将创建目录、准备临时目录和调用前快照等同步文件系统操作集中到此辅助函数，使调用方可
    通过 ``asyncio.to_thread`` 在线程中执行。返回工作区 cwd、固定的临时目录和调用前文件
    快照。
    """
    paths.ensure_thread_dirs(thread_id, user_id=user_id)
    source_base_dir = paths.sandbox_work_dir(thread_id, user_id=user_id)
    tmp_dir = source_base_dir / _MCP_TMP_SUBDIR
    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir.chmod(0o700)
    except OSError:
        logger.warning("Failed to prepare MCP temp dir: %s", tmp_dir, exc_info=True)
    before_files = _snapshot_workspace_files(source_base_dir)
    return source_base_dir, tmp_dir, before_files


def _result_has_text_content(call_tool_result: Any) -> bool:
    """当 MCP 结果包含任意文本内容时返回 ``True``。

    调用后的快照差异只用于自由文本中的裸文件名关联。结果没有文本块时无需改写，调用方可
    完全跳过第二次递归遍历。
    """
    from mcp.types import EmbeddedResource, TextContent, TextResourceContents

    content = getattr(call_tool_result, "content", None)
    if not content:
        return False
    for item in content:
        if isinstance(item, TextContent):
            return True
        if isinstance(item, EmbeddedResource) and isinstance(item.resource, TextResourceContents):
            return True
    return False


def _rewrite_unique_bare_filenames(
    text: str,
    *,
    changed_files: Iterable[Path],
    thread_id: str,
    user_id: str,
    source_base_dir: Path | None = None,
) -> str:
    """仅在本次调用生成唯一匹配时改写裸文件名。

    ``Saved as page-2026.yml`` 这类响应在结构上并不是路径。安全的解释方式只能是将文件名
    与本次工具调用新建或修改的文件关联，并且仅当该文件名在当前线程挂载的用户数据树中
    唯一对应一个文件时才改写。
    """
    candidates: dict[str, list[str]] = {}
    for path in changed_files:
        virtual_path = _local_uri_to_virtual_path(
            str(path),
            thread_id=thread_id,
            user_id=user_id,
            source_base_dir=source_base_dir,
        )
        if virtual_path is None:
            continue
        candidates.setdefault(path.name, []).append(virtual_path)

    unique = {name: paths[0] for name, paths in candidates.items() if len(set(paths)) == 1}
    if not unique:
        if candidates:
            logger.debug("MCP bare filename rewrite skipped: no unique candidate in %s", sorted(candidates))
        else:
            logger.debug("MCP bare filename rewrite skipped: no snapshot candidates")
        return text

    rewritten = text
    for name in sorted(unique, key=len, reverse=True):
        # Do not rewrite inside longer paths/words. A final sentence period is
        # allowed, but ".bak" or another path segment is not.
        pattern = re.compile(rf"(?<![\w./-]){re.escape(name)}(?!(?:[\w/-]|\.[\w]))")
        rewritten_text, count = pattern.subn(unique[name], rewritten)
        if count:
            logger.debug("MCP bare filename rewrite: %s -> %s", name, unique[name])
        rewritten = rewritten_text
    return rewritten


def _rewrite_local_paths_in_text(
    text: str,
    *,
    thread_id: str,
    user_id: str,
    source_base_dir: Path | None = None,
    changed_files: Iterable[Path] | None = None,
) -> str:
    """尽力改写自由文本中出现的本地文件引用。

    某些 MCP 服务器（尤其是 Playwright 的 ``browser_take_screenshot``）仅以自由文本报告
    保存的文件，例如 ``Took the screenshot and saved it as temp/page-2026.png``，而非使用
    ``ResourceLink``。自由文本不是可靠协议，因此此处刻意保守：每个候选令牌都交给
    ``_local_uri_to_virtual_path``，只有能解析为当前线程用户数据树内现有文件时才改写。
    不是真实路径或指向其他位置的令牌会保持原样，即使正则表达式匹配过宽也不会造成影响。
    """
    translated_by_source: dict[str, str | None] = {}

    def _replace(match: re.Match[str]) -> str:
        """将匹配到的路径令牌在可安全解析时替换为虚拟路径。"""
        token = match.group(0)
        # A path can end a sentence ("saved as temp/a.png."); strip trailing
        # punctuation and restore it after the (possibly rewritten) path.
        stripped = token.rstrip(_TEXT_PATH_TRAILING_CHARS)
        trailing = token[len(stripped) :]
        if stripped not in translated_by_source:
            translated_by_source[stripped] = _local_uri_to_virtual_path(
                stripped,
                thread_id=thread_id,
                user_id=user_id,
                source_base_dir=source_base_dir,
            )
        rewritten = translated_by_source[stripped]
        if rewritten is None:
            return token
        return f"{rewritten}{trailing}"

    rewritten = _LOCAL_PATH_IN_TEXT_RE.sub(_replace, text)
    if changed_files is None:
        return rewritten
    return _rewrite_unique_bare_filenames(
        rewritten,
        changed_files=changed_files,
        thread_id=thread_id,
        user_id=user_id,
        source_base_dir=source_base_dir,
    )


def _extract_thread_id(runtime: Runtime | None) -> str:
    """从注入的工具运行时或 LangGraph 配置中提取 thread_id。"""
    if runtime is not None:
        tid = runtime.context.get("thread_id") if runtime.context else None
        if tid is not None:
            return str(tid)
        config = runtime.config or {}
        tid = config.get("configurable", {}).get("thread_id")
        if tid is not None:
            return str(tid)

    try:
        tid = get_config().get("configurable", {}).get("thread_id")
        return str(tid) if tid is not None else "default"
    except RuntimeError:
        return "default"


def _convert_call_tool_result(
    call_tool_result: Any,
    *,
    thread_id: str | None = None,
    user_id: str | None = None,
    source_base_dir: Path | None = None,
    changed_files: Iterable[Path] | None = None,
) -> Any:
    """将 MCP ``CallToolResult`` 转换为 LangChain 的 ``content_and_artifact`` 格式。

    实现与适配器相同的转换逻辑，但不依赖私有符号
    ``langchain_mcp_adapters.tools._convert_call_tool_result``。

    提供 ``thread_id`` 和 ``user_id`` 时，``ResourceLink`` 块或普通文本中引用的本地文件
    （例如 Playwright MCP 保存的截图）会从主机路径转换为 ``/mnt/user-data/...`` 虚拟路径，
    使沙箱和制品 API 可以解析它们。文件本身不会被复制：stdio 服务器的 cwd 与临时目录已
    固定在挂载树内，文件本就位于可服务的位置。远程 URI 及线程用户数据树外的文件保持不变。
    """
    from langchain_core.messages import ToolMessage
    from langchain_core.messages.content import create_file_block, create_image_block, create_text_block
    from langchain_core.tools import ToolException
    from mcp.types import EmbeddedResource, ImageContent, ResourceLink, TextContent, TextResourceContents

    # Pass ToolMessage through directly (interceptor short-circuit).
    if isinstance(call_tool_result, ToolMessage):
        return call_tool_result, None

    # Pass LangGraph Command through directly when langgraph is installed.
    try:
        from langgraph.types import Command

        if isinstance(call_tool_result, Command):
            return call_tool_result, None
    except ImportError:
        # langgraph is optional; if unavailable, continue with standard MCP content conversion.
        pass

    def _resolve_link_url(uri: str) -> str:
        """在可解析时将资源链接地址转换为虚拟路径。"""
        if thread_id is None or user_id is None:
            return uri
        rewritten = _local_uri_to_virtual_path(uri, thread_id=thread_id, user_id=user_id, source_base_dir=source_base_dir)
        return rewritten if rewritten is not None else uri

    def _resolve_text(text: str) -> str:
        # Servers like Playwright report saved files only as plain text, with no
        # ResourceLink to hook into. Scan the text for local paths and translate
        # them so the produced files are readable through the sandbox/artifact API.
        """在可解析时改写文本中引用的本地文件路径。"""
        if thread_id is None or user_id is None:
            return text
        return _rewrite_local_paths_in_text(
            text,
            thread_id=thread_id,
            user_id=user_id,
            source_base_dir=source_base_dir,
            changed_files=changed_files,
        )

    # Convert MCP content blocks to LangChain content blocks.
    lc_content = []
    for item in call_tool_result.content:
        if isinstance(item, TextContent):
            lc_content.append(create_text_block(text=_resolve_text(item.text)))
        elif isinstance(item, ImageContent):
            lc_content.append(create_image_block(base64=item.data, mime_type=item.mimeType))
        elif isinstance(item, ResourceLink):
            mime = item.mimeType or None
            url = _resolve_link_url(str(item.uri))
            if mime and mime.startswith("image/"):
                lc_content.append(create_image_block(url=url, mime_type=mime))
            else:
                lc_content.append(create_file_block(url=url, mime_type=mime))
        elif isinstance(item, EmbeddedResource):
            from mcp.types import BlobResourceContents

            res = item.resource
            if isinstance(res, TextResourceContents):
                lc_content.append(create_text_block(text=_resolve_text(res.text)))
            elif isinstance(res, BlobResourceContents):
                mime = res.mimeType or None
                if mime and mime.startswith("image/"):
                    lc_content.append(create_image_block(base64=res.blob, mime_type=mime))
                else:
                    lc_content.append(create_file_block(base64=res.blob, mime_type=mime))
            else:
                lc_content.append(create_text_block(text=str(res)))
        else:
            lc_content.append(create_text_block(text=str(item)))

    if call_tool_result.isError:
        error_parts = [item["text"] for item in lc_content if isinstance(item, dict) and item.get("type") == "text"]
        raise ToolException("\n".join(error_parts) if error_parts else str(lc_content))

    artifact = None
    if call_tool_result.structuredContent is not None:
        artifact = {"structured_content": call_tool_result.structuredContent}

    return lc_content, artifact


def _make_session_pool_tool(
    tool: BaseTool,
    server_name: str,
    connection: dict[str, Any],
    tool_interceptors: list[Any] | None = None,
    tool_call_timeout: float | None = None,
) -> BaseTool:
    """包装 MCP 工具，使其复用会话池中的持久化会话。

    以按 ``(server_name, user_id:thread_id)`` 划分的池化会话替代每次调用都创建会话的方式，
    从而使 Playwright 等有状态 MCP 服务器在同一线程的多次工具调用间保留状态，同时保持用户
    之间隔离。

    保留配置的 ``tool_interceptors``（OAuth 或自定义拦截器），并在每次调用池化会话前应用。
    """
    # Strip the server-name prefix to recover the original MCP tool name.
    original_name = tool.name
    prefix = f"{server_name}_"
    if original_name.startswith(prefix):
        original_name = original_name[len(prefix) :]

    pool = get_session_pool()

    async def call_with_persistent_session(
        runtime: Runtime | None = None,
        **arguments: Any,
    ) -> Any:
        """通过按用户和线程隔离的持久化会话调用当前 MCP 工具。"""
        thread_id = _extract_thread_id(runtime)
        user_id = resolve_runtime_user_id(runtime)
        # Scope the pooled session by user *and* thread. Filesystem isolation is
        # per-(user_id, thread_id), so a thread_id alone could otherwise let two
        # users with a colliding thread_id share one stateful MCP session.
        scope_key = f"{user_id}:{thread_id}"
        session_connection = dict(connection)
        # cwd/temp pinning and the workspace snapshot only matter for stdio
        # servers, which run as local subprocesses writing to a real filesystem.
        # SSE/HTTP servers have no local cwd to pin, so skip the filesystem work
        # entirely for them (avoids needless dir creation and recursive walks).
        is_stdio = session_connection.get("transport", "stdio") == "stdio"
        source_base_dir: Path | None = None
        process_cwd: Path | None = None
        before_files: _FILE_SNAPSHOT | None = None
        if is_stdio:
            paths = get_paths()
            # Bundle the synchronous filesystem prep (dir creation, temp-dir
            # setup, pre-call snapshot) and run it off the event loop — the
            # snapshot walks the whole workspace and would otherwise block.
            source_base_dir, tmp_dir, before_files = await asyncio.to_thread(_prepare_stdio_workspace, paths, thread_id=thread_id, user_id=user_id)
            # Stdio MCP servers resolve relative output links against their
            # process cwd. Keep that cwd inside the thread's mounted user-data
            # tree so files produced by tools like Playwright land where the
            # sandbox/artifact API can serve them and their references can be
            # translated to virtual paths.
            configured_cwd = session_connection.get("cwd", str(source_base_dir))
            session_connection["cwd"] = str(configured_cwd)
            process_cwd = Path(configured_cwd)
            # Pin the subprocess temp dir under the same mounted tree. Tools that
            # default to the OS temp dir (Node's os.tmpdir(), Python's tempfile,
            # many CLIs) then write inside user-data instead of an unreachable
            # host path — the tool-agnostic counterpart to fixing the cwd. Merge
            # rather than replace any operator-provided env.
            session_env = dict(session_connection.get("env") or {})
            session_env.setdefault("TMPDIR", str(tmp_dir))
            session_env.setdefault("TMP", str(tmp_dir))
            session_env.setdefault("TEMP", str(tmp_dir))
            session_connection["env"] = session_env
        session = await pool.get_session(server_name, scope_key, session_connection)

        # Build common call_tool kwargs once — only add keys when needed so
        # existing call-sites that assert on exact arguments are not affected.
        call_kwargs: dict[str, Any] = {}
        if tool_call_timeout:
            call_kwargs["read_timeout_seconds"] = timedelta(seconds=tool_call_timeout)

        if tool_interceptors:
            from langchain_mcp_adapters.interceptors import MCPToolCallRequest

            async def base_handler(request: MCPToolCallRequest) -> Any:
                # Preserve interceptor-injected headers for stdio MCP calls by
                # forwarding them through MCP call meta.
                """执行最终 MCP 调用，并转发拦截器注入的请求头。"""
                kwargs = dict(call_kwargs)
                if request.headers:
                    if isinstance(request.headers, Mapping):
                        kwargs["meta"] = {"headers": dict(request.headers)}
                    else:
                        logger.warning("Ignoring MCP interceptor headers with unsupported type: %s", type(request.headers).__name__)
                return await session.call_tool(
                    request.name,
                    request.args,
                    **kwargs,
                )

            handler = base_handler
            for interceptor in reversed(tool_interceptors):
                outer = handler

                async def wrapped(req: Any, _i: Any = interceptor, _h: Any = outer) -> Any:
                    """将当前拦截器包裹在下一处理器之外。"""
                    return await _i(req, _h)

                handler = wrapped

            request = MCPToolCallRequest(
                name=original_name,
                args=arguments,
                server_name=server_name,
                runtime=runtime,
            )
            call_tool_result = await handler(request)
        else:
            call_tool_result = await session.call_tool(
                original_name,
                arguments,
                **call_kwargs,
            )

        # The after-call snapshot diff only feeds bare-filename correlation in
        # free text, so skip the second recursive walk when there is no text
        # content to rewrite. Both the diff and the per-token path resolution
        # inside _convert_call_tool_result touch the filesystem, so run them off
        # the event loop.
        changed_files: list[Path] | None = None
        if is_stdio and before_files is not None and _result_has_text_content(call_tool_result):
            changed_files = await asyncio.to_thread(_changed_workspace_files, source_base_dir, before_files)
        return await asyncio.to_thread(
            _convert_call_tool_result,
            call_tool_result,
            thread_id=thread_id,
            user_id=user_id,
            source_base_dir=process_cwd,
            changed_files=changed_files,
        )

    return StructuredTool(
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        coroutine=call_with_persistent_session,
        response_format="content_and_artifact",
        metadata=tool.metadata,
    )


async def get_mcp_tools() -> list[BaseTool]:
    """获取全部已启用 MCP 服务器提供的工具。

    使用 stdio 传输的工具会被包装为持久化会话逻辑，使同一线程内连续调用复用同一 MCP
    会话。HTTP/SSE 工具保持未包装状态，以避免跨任务清理 TaskGroup 的错误。

    返回：
        全部已启用 MCP 服务器提供的 LangChain 工具列表。
    """
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        logger.warning("langchain-mcp-adapters not installed. Install it to enable MCP tools: pip install langchain-mcp-adapters")
        return []

    # NOTE: We use ExtensionsConfig.from_file() instead of get_extensions_config()
    # to always read the latest configuration from disk. This ensures that changes
    # made through the Gateway API (which runs in a separate process) are immediately
    # reflected when initializing MCP tools.
    extensions_config = ExtensionsConfig.from_file()
    servers_config = build_servers_config(extensions_config)

    if not servers_config:
        logger.info("No enabled MCP servers configured")
        return []

    try:
        # Create the multi-server MCP client
        logger.info(f"Initializing MCP client with {len(servers_config)} server(s)")

        # Inject initial OAuth headers for server connections (tool discovery/session init)
        initial_oauth_headers = await get_initial_oauth_headers(extensions_config)
        for server_name, auth_header in initial_oauth_headers.items():
            if server_name not in servers_config:
                continue
            if servers_config[server_name].get("transport") in ("sse", "http"):
                existing_headers = dict(servers_config[server_name].get("headers", {}))
                existing_headers["Authorization"] = auth_header
                servers_config[server_name]["headers"] = existing_headers

        tool_interceptors: list[Any] = []
        oauth_interceptor = build_oauth_tool_interceptor(extensions_config)
        if oauth_interceptor is not None:
            tool_interceptors.append(oauth_interceptor)

        # Load custom interceptors declared in extensions_config.json
        # Format: "mcpInterceptors": ["pkg.module:builder_func", ...]
        raw_interceptor_paths = (extensions_config.model_extra or {}).get("mcpInterceptors")
        if isinstance(raw_interceptor_paths, str):
            raw_interceptor_paths = [raw_interceptor_paths]
        elif not isinstance(raw_interceptor_paths, list):
            if raw_interceptor_paths is not None:
                logger.warning(f"mcpInterceptors must be a list of strings, got {type(raw_interceptor_paths).__name__}; skipping")
            raw_interceptor_paths = []
        for interceptor_path in raw_interceptor_paths:
            try:
                builder = resolve_variable(interceptor_path)
                interceptor = builder()
                if callable(interceptor):
                    tool_interceptors.append(interceptor)
                    logger.info(f"Loaded MCP interceptor: {interceptor_path}")
                elif interceptor is not None:
                    logger.warning(f"Builder {interceptor_path} returned non-callable {type(interceptor).__name__}; skipping")
            except Exception as e:
                logger.warning(
                    f"Failed to load MCP interceptor {interceptor_path}: {e}",
                    exc_info=True,
                )

        client = MultiServerMCPClient(
            servers_config,
            tool_interceptors=tool_interceptors,
            tool_name_prefix=True,
        )

        async def load_server_tools(server_name: str) -> list[BaseTool]:
            """独立加载指定服务器的工具，失败时不影响其他服务器。"""
            try:
                return await client.get_tools(server_name=server_name)
            except Exception as e:
                logger.warning(
                    f"Skipping MCP server '{server_name}' after tool discovery failed: {e}",
                    exc_info=True,
                )
                return []

        # Get tools from each server independently so one broken MCP server does
        # not prevent healthy servers from contributing their tools.
        tools_by_server = await asyncio.gather(*(load_server_tools(name) for name in servers_config))
        tools = [tool for server_tools in tools_by_server for tool in server_tools]
        logger.info(f"Successfully loaded {len(tools)} tool(s) from MCP servers")

        # Wrap each tool with persistent-session logic.
        # Only pool stdio sessions. HTTP/SSE transports use anyio TaskGroups
        # internally which cannot be closed from a different async task, so
        # pooling them causes RuntimeError on cleanup (see #3203).
        wrapped_tools: list[BaseTool] = []
        # Route each tool by the server that actually produced it: tools_by_server[i]
        # corresponds to the i-th server in servers_config. Inferring the source server by
        # scanning servers_config for a name prefix is ambiguous when one server name is a
        # prefix of another (e.g. "web" vs "web_scraper" → "web_scraper_search".startswith(
        # "web_") matches "web" first), which pools the tool under the wrong server. Using the
        # source grouping makes routing exact; the prefix guard preserves the previous
        # behavior of leaving unprefixed tools unwrapped.
        for source_name, server_tools in zip(servers_config.keys(), tools_by_server, strict=True):
            transport = servers_config[source_name].get("transport", "stdio")
            server_cfg = extensions_config.mcp_servers.get(source_name)
            for tool in server_tools:
                if not _VALID_MCP_TOOL_NAME.fullmatch(tool.name or ""):
                    logger.warning(
                        "Dropping MCP tool from server '%s' with invalid name %r: tool names must match %s. A name outside this charset cannot be bound as a function tool and could forge prompt structure when listed as a deferred tool.",
                        source_name,
                        tool.name,
                        _VALID_MCP_TOOL_NAME.pattern,
                    )
                    continue
                tag_mcp_tool(tool)
                prefix = f"{source_name}_"
                original_name = tool.name[len(prefix) :] if tool.name.startswith(prefix) else tool.name
                routing = resolve_effective_mcp_routing(server_cfg, original_name)
                if routing.get("mode") != "off":
                    tag_mcp_routing(tool, routing)
                if tool.name.startswith(f"{source_name}_") and transport == "stdio":
                    _timeout = server_cfg.tool_call_timeout if server_cfg else None
                    wrapped_tools.append(_make_session_pool_tool(tool, source_name, servers_config[source_name], tool_interceptors, tool_call_timeout=_timeout))
                else:
                    if transport != "stdio" and server_cfg and server_cfg.tool_call_timeout is not None:
                        logger.warning(
                            "Ignoring tool_call_timeout for MCP server '%s' because transport '%s' is not stdio; configure HTTP/SSE transport-level timeouts instead.",
                            source_name,
                            transport,
                        )
                    wrapped_tools.append(tool)

        # Patch tools to support sync invocation, as deerflow client streams synchronously
        for tool in wrapped_tools:
            if getattr(tool, "func", None) is None and getattr(tool, "coroutine", None) is not None:
                tool.func = make_sync_tool_wrapper(tool.coroutine, tool.name)

        return wrapped_tools

    except Exception as e:
        logger.error(f"Failed to load MCP tools: {e}", exc_info=True)
        return []
