'''标注需要重启才能生效的配置字段，并生成面向配置界面的解释。'''

from __future__ import annotations

from collections.abc import Iterator

STARTUP_ONLY_PREFIX = "startup-only:"
STARTUP_ONLY_FIELDS: dict[str, str] = {
    "database": ("init_engine_from_config() runs once during langgraph_runtime() startup; the SQLAlchemy engine holds the connection pool and is not rebuilt on config.yaml edits."),
    "checkpointer": ("make_checkpointer() binds the PostgreSQL checkpointer once at startup."),
    "run_events": ("make_run_event_store() picks the memory- vs SQL-backed implementation at startup and is frozen onto app.state.run_events_config to stay paired with the underlying event store."),
    "stream_bridge": ("make_stream_bridge() constructs the stream-bridge singleton once during startup."),
    "sandbox": ("get_sandbox_provider() caches the provider singleton (``_default_sandbox_provider``); a different ``sandbox.use`` class path only takes effect on next process start."),
    "log_level": (
        "apply_logging_level() runs only during app.py startup; it sets the deerflow/app logger levels and may lower root handler thresholds so configured messages can propagate. A freshly reloaded AppConfig does not retrigger it."
    ),
    "logging": (
        "configure_logging() runs only during app.py startup; it installs/removes the trace-context filter and the enhanced formatter on root handlers, "
        "and TraceMiddleware captures logging.enhance.enabled once at startup so response X-Trace-Id headers, log trace_id fields, and Langfuse "
        "deerflow_trace_id stay coherent. A freshly reloaded AppConfig does not retrigger any of this."
    ),
    "channels": ("start_channel_service() is invoked once during startup; the live IM channel clients (Feishu, Slack, Telegram, DingTalk) are not rebuilt when channels.* changes."),
    "channel_connections": (
        "start_channel_service() wires the connection repository and channel workers once at startup, and the channel-connections router caches the merged provider config on app.state; channel_connections.* edits need a restart."
    ),
    "scheduler": (
        "ScheduledTaskService is constructed and started once during Gateway lifespan startup; enabled, poll_interval_seconds, lease_seconds, "
        "and max_concurrent_runs are captured into the service instance and the background poller task is not rebuilt on config.yaml edits."
    ),
    "run_ownership": (
        "RunOwnershipConfig is captured once into RunManager at langgraph_runtime() startup; the lease heartbeat background task is created and "
        "started there, and heartbeat_enabled / lease_seconds / grace_seconds are not re-read on config.yaml edits."
    ),
}


def iter_startup_only_field_paths() -> Iterator[str]:
    '''按声明顺序枚举仅在进程启动时读取的配置字段路径。'''
    return iter(STARTUP_ONLY_FIELDS)


def is_startup_only_field(field_path: str) -> bool:
    '''判断配置字段是否属于需要重启应用才能生效的启动期字段。'''
    return field_path in STARTUP_ONLY_FIELDS


def format_field_description(field_path: str, *, field_doc: str | None = None) -> str:
    '''把重启要求和原字段说明合并为配置接口可展示的描述文本。'''
    reason = STARTUP_ONLY_FIELDS[field_path]
    header = f"{STARTUP_ONLY_PREFIX} {reason}"
    if field_doc is None:
        return header
    return f"{header}\n\n{field_doc.strip()}"
