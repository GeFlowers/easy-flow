"""缓存 MCP 工具，并在扩展配置发生变化时自动失效。"""

import asyncio
import hashlib
import logging
from pathlib import Path

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

_mcp_tools_cache: list[BaseTool] | None = None
_cache_initialized = False
_initialization_lock = asyncio.Lock()
_ConfigSignature = tuple[float | None, int | None, str | None]
_config_path: Path | None = None
_config_signature: _ConfigSignature | None = None


def _resolve_config_path() -> Path | None:
    """解析当前扩展配置文件的路径。"""
    from deerflow.config.extensions_config import ExtensionsConfig

    return ExtensionsConfig.resolve_config_path()


def _get_config_signature(config_path: Path) -> _ConfigSignature | None:
    """返回用于检测配置内容变化的文件签名。"""
    try:
        stat_result = config_path.stat()
    except OSError:
        return None
    digest = hashlib.sha256()
    try:
        with config_path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return (stat_result.st_mtime, stat_result.st_size, None)

    return (stat_result.st_mtime, stat_result.st_size, digest.hexdigest())


def _current_config_state() -> tuple[Path | None, _ConfigSignature | None]:
    """获取当前配置文件路径及其签名。"""
    config_path = _resolve_config_path()
    if config_path is None:
        return None, None
    return config_path, _get_config_signature(config_path)


def _is_cache_stale() -> bool:
    """判断已初始化的 MCP 工具缓存是否因配置变化而过期。"""
    if not _cache_initialized:
        return False

    current_path, current_signature = _current_config_state()
    if _config_signature is None or current_signature is None:
        return False

    if current_path != _config_path:
        logger.info("MCP config path changed (%s -> %s), cache is stale", _config_path, current_path)
        return True

    if current_signature != _config_signature:
        logger.info("MCP config content changed (signature %s -> %s), cache is stale", _config_signature, current_signature)
        return True

    return False


async def initialize_mcp_tools() -> list[BaseTool]:
    """初始化并缓存当前已启用 MCP 服务器提供的工具。"""
    global _mcp_tools_cache, _cache_initialized, _config_path, _config_signature

    async with _initialization_lock:
        if _cache_initialized:
            logger.info("MCP tools already initialized")
            return _mcp_tools_cache or []

        from deerflow.mcp.tools import get_mcp_tools

        logger.info("Initializing MCP tools...")
        _mcp_tools_cache = await get_mcp_tools()
        _cache_initialized = True
        _config_path, _config_signature = _current_config_state()
        logger.info("MCP tools initialized: %d tool(s) loaded (config path: %s)", len(_mcp_tools_cache), _config_path)

        return _mcp_tools_cache


def get_cached_mcp_tools() -> list[BaseTool]:
    """返回缓存的 MCP 工具，必要时同步完成惰性初始化。"""
    global _cache_initialized
    if _is_cache_stale():
        logger.info("MCP cache is stale, resetting for re-initialization...")
        reset_mcp_tools_cache()

    if not _cache_initialized:
        logger.info("MCP tools not initialized, performing lazy initialization...")
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, initialize_mcp_tools())
                    future.result()
            else:
                loop.run_until_complete(initialize_mcp_tools())
        except RuntimeError:
            try:
                asyncio.run(initialize_mcp_tools())
            except Exception:
                logger.exception("Failed to lazy-initialize MCP tools")
                return []
        except Exception:
            logger.exception("Failed to lazy-initialize MCP tools")
            return []

    return _mcp_tools_cache or []


def reset_mcp_tools_cache() -> None:
    """清空 MCP 工具缓存，并关闭和重置关联的会话池。"""
    global _mcp_tools_cache, _cache_initialized, _config_path, _config_signature
    _mcp_tools_cache = None
    _cache_initialized = False
    _config_path = None
    _config_signature = None
    #
    try:
        from deerflow.mcp.session_pool import get_session_pool

        get_session_pool().close_all_sync()
    except Exception:
        logger.debug("Could not close MCP session pool on cache reset", exc_info=True)

    from deerflow.mcp.session_pool import reset_session_pool

    reset_session_pool()
    logger.info("MCP tools cache reset")
