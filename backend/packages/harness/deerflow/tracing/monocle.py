'''在应用生命周期中配置 Monocle 遥测导出，并提示远程数据导出的影响。'''

from __future__ import annotations

import logging

from deerflow.config import (
    get_enabled_tracing_providers,
    get_tracing_config,
    is_monocle_tracing_enabled,
)

logger = logging.getLogger(__name__)

# 供追踪回调工厂检测：嵌入式调用方可能启用了 Monocle，却没有执行网关启动初始化。
_setup_completed = False


def is_monocle_setup_completed() -> bool:
    '''告知调用方本进程是否已经完成 Monocle 遥测初始化。'''
    return _setup_completed


def setup_monocle_tracing_if_enabled() -> bool:
    '''配置开启的 Monocle 导出器；未启用时不导入可选依赖并返回失败状态。'''
    if not is_monocle_tracing_enabled():
        return False

    monocle = get_tracing_config().monocle
    # 在安装遥测前校验导出器和凭据；校验放在启动路径，避免配置错误拖垮单次运行。
    monocle.validate()

    # Monocle 与 Langfuse 共用全局追踪提供者时会各自挂载处理器，因此启用双方会让
    # 两套导出器都接收到全部跨度，而不只是各自创建的跨度。
    exporters = monocle.exporters

    # 控制台和文件导出留在本机；这里只提示会把数据发送到外部服务的导出器。
    off_box = [e for e in monocle.exporter_list if e not in ("file", "console")]
    if off_box:
        # 由于共享全局追踪提供者，其他已启用集成产生的跨度也可能随之导出。
        langfuse_note = " Langfuse is also enabled and shares the global provider, so its spans are exported there as well." if "langfuse" in get_enabled_tracing_providers() else ""
        logger.warning(
            "Monocle is exporting trace data (prompts, tool inputs/outputs, completions) beyond the local .monocle/ file via: %s. Make sure that destination is trusted.%s",
            ", ".join(off_box),
            langfuse_note,
        )

    try:
        from monocle_apptrace import setup_monocle_telemetry
    except ImportError as exc:
        raise RuntimeError("MONOCLE_TRACING is enabled but monocle_apptrace is not installed. Install the 'monocle' extra: `uv sync --extra monocle` in backend/, or `pip install 'deerflow-harness[monocle]'`.") from exc

    # 库接口接收逗号分隔字符串，因此保留配置原值传入。
    setup_monocle_telemetry(workflow_name="deer-flow", monocle_exporters_list=exporters)
    global _setup_completed
    _setup_completed = True
    logger.info("Monocle telemetry enabled (exporters=%s)", exporters)
    return True
