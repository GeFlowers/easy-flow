'''

同步检查点保存器工厂。

为 LangGraph 图编译和命令行工具提供**同步单例**与**同步上下文管理器**。

支持 PostgreSQL 后端；旧版独立 ``checkpointer`` 配置仍可提供连接字符串。

用法::

    from deerflow.runtime.checkpointer.provider import get_checkpointer, checkpointer_context

    cp = get_checkpointer()

    with checkpointer_context() as cp:
        graph.invoke(input, config={"configurable": {"thread_id": "1"}})
'''

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Iterator

from langgraph.types import Checkpointer

from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.config.checkpointer_config import CheckpointerConfig, ensure_config_loaded, get_checkpointer_config

logger = logging.getLogger(__name__)


POSTGRES_INSTALL = (
    "langgraph-checkpoint-postgres is required for the PostgreSQL checkpointer. Install the package extra with: pip install 'deer-flow[postgres]' (or use: uv sync --all-packages --extra postgres when developing locally)"
)
POSTGRES_CONN_REQUIRED = "checkpointer.connection_string is required for the postgres backend"




def _resolve_checkpointer_config(app_config: AppConfig) -> CheckpointerConfig:
    '''

    从旧版或统一应用配置中解析检查点后端。

        存在旧版 ``checkpointer`` 配置节时优先采用它，使检查点保存器与存储器
        使用相同后端；否则由统一 ``database`` 配置节决定后端，与异步
        :func:`~deerflow.runtime.checkpointer.async_provider.make_checkpointer`
        工厂及同步存储器提供方的 ``_resolve_store_config`` 保持一致。
    '''
    if app_config.checkpointer is not None:
        return app_config.checkpointer

    database = app_config.database
    if database is None or not database.postgres_url:
        raise ValueError("database.postgres_url is required for the postgres backend")
    return CheckpointerConfig(type="postgres", connection_string=database.postgres_url)


def _get_checkpointer_config() -> CheckpointerConfig:
    '''

    在未持有提供方单例锁时加载检查点配置。'''
    ensure_config_loaded()

    legacy_config = get_checkpointer_config()
    if legacy_config is not None:
        return legacy_config
    try:
        app_config = get_app_config()
    except FileNotFoundError as exc:
        raise RuntimeError("PostgreSQL checkpointer configuration is required") from exc
    return _resolve_checkpointer_config(app_config)




@contextlib.contextmanager
def _sync_checkpointer_cm(config: CheckpointerConfig) -> Iterator[Checkpointer]:
    '''

    创建同步 PostgreSQL 检查点器并在上下文结束时关闭连接。

        提供已配置的 ``Checkpointer`` 实例。底层连接或连接池的清理由本模块
        上层辅助函数（如单例工厂或上下文管理器）管理，不另外返回清理回调。
    '''
    if config.type == "postgres":
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
        except ImportError as exc:
            raise ImportError(POSTGRES_INSTALL) from exc

        if not config.connection_string:
            raise ValueError(POSTGRES_CONN_REQUIRED)

        with PostgresSaver.from_conn_string(config.connection_string) as saver:
            saver.setup()
            logger.info("Checkpointer: using PostgresSaver")
            yield saver
        return

    raise ValueError(f"Unknown checkpointer type: {config.type!r}")



_checkpointer: Checkpointer | None = None
_checkpointer_ctx = None
_checkpointer_lock = threading.Lock()


def get_checkpointer() -> Checkpointer:
    '''

    返回全局同步检查点保存器单例，首次调用时创建。

        配置了旧版 ``checkpointer`` 节时优先使用它，
        否则由统一 PostgreSQL ``database`` 配置节选择后端。

        Raises:
            ImportError: 未安装所配置后端所需的软件包。
            ValueError: 后端需要 ``connection_string``，但配置中未提供。
    '''
    global _checkpointer, _checkpointer_ctx

    if _checkpointer is not None:
        return _checkpointer

    config = _get_checkpointer_config()

    with _checkpointer_lock:
        if _checkpointer is not None:
            return _checkpointer

        checkpointer_ctx = _sync_checkpointer_cm(config)
        checkpointer = checkpointer_ctx.__enter__()
        _checkpointer_ctx = checkpointer_ctx
        _checkpointer = checkpointer

    return _checkpointer


def reset_checkpointer() -> None:
    '''

    重置同步单例，使下次调用重新创建实例。

        关闭已打开的后端连接并清空缓存实例，适用于测试或配置变更后。
    '''
    global _checkpointer, _checkpointer_ctx
    with _checkpointer_lock:
        if _checkpointer_ctx is not None:
            try:
                _checkpointer_ctx.__exit__(None, None, None)
            except Exception:
                logger.warning("Error during checkpointer cleanup", exc_info=True)
            _checkpointer_ctx = None
        _checkpointer = None




@contextlib.contextmanager
def checkpointer_context() -> Iterator[Checkpointer]:
    '''

    提供同步检查点保存器，并在上下文退出时清理资源。

        与 :func:`get_checkpointer` 不同，此处**不缓存**实例；
        每个 ``with`` 块创建并关闭自己的连接，适用于需要确定性清理的
        命令行脚本或测试::

            with checkpointer_context() as cp:
                graph.invoke(input, config={"configurable": {"thread_id": "1"}})

        配置了旧版 ``checkpointer`` 节时优先使用它，
        否则由统一 PostgreSQL ``database`` 配置节选择后端。
    '''

    config = _resolve_checkpointer_config(get_app_config())
    with _sync_checkpointer_cm(config) as saver:
        yield saver
