"""根据应用配置解析并构造聊天模型，同时规范化供应商参数。"""

import logging

from langchain.chat_models import BaseChatModel
from langchain_openai.chat_models.base import BaseChatOpenAI

from deerflow.config import get_app_config
from deerflow.config.app_config import AppConfig
from deerflow.reflection import resolve_class
from deerflow.tracing import build_tracing_callbacks

logger = logging.getLogger(__name__)


def _deep_merge_dicts(base: dict | None, override: dict) -> dict:
    """递归合并配置字典；嵌套字典逐层合并，其他值由覆盖项替换。"""
    merged = dict(base or {})
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _vllm_disable_chat_template_kwargs(chat_template_kwargs: dict) -> dict:
    """为 vLLM/Qwen 生成关闭思考模式的模板参数，只修改调用方实际提供的开关。"""
    disable_kwargs: dict[str, bool] = {}
    if "thinking" in chat_template_kwargs:
        disable_kwargs["thinking"] = False
    if "enable_thinking" in chat_template_kwargs:
        disable_kwargs["enable_thinking"] = False
    return disable_kwargs


def _declares_api_base(model_class: type) -> bool:
    """判断模型类是否将 ``api_base`` 声明为自身字段，以区分真实参数和别名误用。"""
    return "api_base" in getattr(model_class, "model_fields", {})


def _normalize_openai_base_url(model_class: type, model_settings_from_config: dict) -> None:
    """将 OpenAI 兼容模型配置中的 ``api_base`` 别名规范为 ``base_url``。

    原生声明 ``api_base`` 的供应商类保留该字段；若同时提供规范 endpoint 字段，则丢弃别名并记录警告。
    """
    if not issubclass(model_class, BaseChatOpenAI) or _declares_api_base(model_class):
        return
    if "api_base" not in model_settings_from_config:
        return
    if "base_url" in model_settings_from_config or "openai_api_base" in model_settings_from_config:
        # 已提供规范地址字段时移除别名，避免同一配置表达两个冲突意图。
        model_settings_from_config.pop("api_base", None)
        logger.warning("Model config sets both an endpoint key (base_url/openai_api_base) and 'api_base'; using the former and ignoring 'api_base'.")
        return
    model_settings_from_config["base_url"] = model_settings_from_config.pop("api_base")
    logger.debug("Normalized model config key 'api_base' -> 'base_url' for OpenAI-compatible client.")


def _warn_unknown_model_settings(model_class, model_name: str, model_settings_from_config: dict) -> None:
    """在构造 OpenAI 兼容模型时提示拼写错误或不受支持的配置键。

    按 Pydantic 字段名和别名校验，并允许工厂及 OpenAI 客户端使用的标准透传参数；其他供应商不套用此规则。
    """
    if not issubclass(model_class, BaseChatOpenAI):
        return
    known = getattr(model_class, "model_fields", None)
    if not known:
        return
    valid_names = set(known.keys())
    for field in known.values():
        alias = getattr(field, "alias", None)
        if alias:
            valid_names.add(alias)
    # 允许工厂注入、但不一定由模型字段显式声明的通用参数。
    valid_names |= {
        "model",
        "model_kwargs",
        "extra_body",
        "default_headers",
        "default_query",
        "stream_usage",
        "stream_chunk_timeout",
        "reasoning_effort",
    }
    unknown = sorted(k for k in model_settings_from_config if k not in valid_names)
    if unknown:
        logger.warning(
            "Model '%s' (%s): config key(s) %s are not recognized parameters of the model class and will be forwarded as-is; this may raise at request time. Check for typos (e.g. 'maxx_tokens' -> 'max_tokens').",
            model_name,
            getattr(model_class, "__name__", "?"),
            unknown,
        )


# OpenAI 兼容模型流式响应的默认分块间隔超时。推理模型首块可能较慢，较宽限时减少误判；
# 用户可按模型覆盖此值，真实停滞仍由 LLM 错误处理中间件重试。
_DEFAULT_STREAM_CHUNK_TIMEOUT_SECONDS: float = 240.0


def _apply_stream_chunk_timeout_default(model_class: type, model_settings_from_config: dict) -> None:
    """为 OpenAI 兼容模型补充流式分块超时，并从其他模型配置中移除不适用的参数。"""
    if not issubclass(model_class, BaseChatOpenAI):
        model_settings_from_config.pop("stream_chunk_timeout", None)
        return
    if "stream_chunk_timeout" in model_settings_from_config:
        return
    model_settings_from_config["stream_chunk_timeout"] = _DEFAULT_STREAM_CHUNK_TIMEOUT_SECONDS


def create_chat_model(name: str | None = None, thinking_enabled: bool = False, *, app_config: AppConfig | None = None, attach_tracing: bool = True, **kwargs) -> BaseChatModel:
    """按模型配置创建聊天模型，并按调用场景控制思考模式和追踪回调。

        Args:
            name: 要创建的模型名称；None 时使用配置中的首个模型。
            thinking_enabled: 在模型支持时启用扩展思考。
            app_config: 可选显式配置；省略时读取缓存的全局配置。
            attach_tracing: When True (default), attach tracing callbacks (Langfuse,
                LangSmith) directly to the model instance. Standalone callers — anything
                that invokes the model outside a LangGraph run that already wires tracing
                at the invocation root (``MemoryUpdater``, ad-hoc utilities, etc.) — keep
                this default so the model-level callback still produces traces. Callers
                that already attach tracing at the graph root (``make_lead_agent``, the
                in-graph ``TitleMiddleware``) MUST pass ``attach_tracing=False``; otherwise
                the same LLM call emits duplicate spans (one rooted at the graph, one at
                the model) and ``session_id`` / ``user_id`` metadata never reach the trace
                because the model becomes a nested observation whose ``langfuse_*`` keys
                get stripped.

        Returns:
            已配置完成的聊天模型实例。
    """
    config = app_config or get_app_config()
    if name is None:
        name = config.models[0].name
    model_config = config.get_model_config(name)
    if model_config is None:
        raise ValueError(f"Model {name} not found in config") from None
    #这一行代码十分关键，确定Agent使用的模型
    model_class = resolve_class(model_config.use, BaseChatModel)
    model_settings_from_config = model_config.model_dump(
        exclude_none=True,
        exclude={
            "use",
            "name",
            "display_name",
            "description",
            "supports_thinking",
            "supports_reasoning_effort",
            "when_thinking_enabled",
            "when_thinking_disabled",
            "thinking",
            "supports_vision",
            # Presentation-only metadata (consumed by the console's cost
            # display) — must never reach the provider client, which would
            # forward unknown kwargs into the completion request payload.
            "pricing",
        },
    )
    # Compute effective when_thinking_enabled by merging in the `thinking` shortcut field.
    # The `thinking` shortcut is equivalent to setting when_thinking_enabled["thinking"].
    has_thinking_settings = (model_config.when_thinking_enabled is not None) or (model_config.thinking is not None)
    effective_wte: dict = dict(model_config.when_thinking_enabled) if model_config.when_thinking_enabled else {}
    if model_config.thinking is not None:
        merged_thinking = {**(effective_wte.get("thinking") or {}), **model_config.thinking}
        effective_wte = {**effective_wte, "thinking": merged_thinking}
    if thinking_enabled and has_thinking_settings:
        if not model_config.supports_thinking:
            raise ValueError(f"Model {name} does not support thinking. Set `supports_thinking` to true in the `config.yaml` to enable thinking.") from None
        if effective_wte:
            model_settings_from_config.update(effective_wte)
    if not thinking_enabled:
        if model_config.when_thinking_disabled is not None:
            # User-provided disable settings take full precedence
            model_settings_from_config.update(model_config.when_thinking_disabled)
        elif has_thinking_settings and effective_wte.get("extra_body", {}).get("thinking", {}).get("type"):
            # OpenAI-compatible gateway: thinking is nested under extra_body
            model_settings_from_config["extra_body"] = _deep_merge_dicts(
                model_settings_from_config.get("extra_body"),
                {"thinking": {"type": "disabled"}},
            )
            model_settings_from_config["reasoning_effort"] = "minimal"
        elif has_thinking_settings and (disable_chat_template_kwargs := _vllm_disable_chat_template_kwargs(effective_wte.get("extra_body", {}).get("chat_template_kwargs") or {})):
            # vLLM uses chat template kwargs to switch thinking on/off.
            model_settings_from_config["extra_body"] = _deep_merge_dicts(
                model_settings_from_config.get("extra_body"),
                {"chat_template_kwargs": disable_chat_template_kwargs},
            )
        elif has_thinking_settings and effective_wte.get("thinking", {}).get("type"):
            # Native langchain_anthropic: thinking is a direct constructor parameter
            model_settings_from_config["thinking"] = {"type": "disabled"}
    if not model_config.supports_reasoning_effort:
        kwargs.pop("reasoning_effort", None)
        model_settings_from_config.pop("reasoning_effort", None)

    # Normalize the api_base -> base_url alias FIRST, so the downstream OpenAI-compatible
    # heuristics (stream_usage default below / stream_chunk_timeout) see the canonical endpoint key.
    _normalize_openai_base_url(model_class, model_settings_from_config)
    _apply_stream_chunk_timeout_default(model_class, model_settings_from_config)

    # For Codex Responses API models: map thinking mode to reasoning_effort
    from deerflow.models.openai_codex_provider import CodexChatModel

    if issubclass(model_class, CodexChatModel):
        # The ChatGPT Codex endpoint currently rejects max_tokens/max_output_tokens.
        model_settings_from_config.pop("max_tokens", None)

        # Use explicit reasoning_effort from frontend if provided (low/medium/high)
        explicit_effort = kwargs.pop("reasoning_effort", None)
        if not thinking_enabled:
            model_settings_from_config["reasoning_effort"] = "none"
        elif explicit_effort and explicit_effort in ("low", "medium", "high", "xhigh"):
            model_settings_from_config["reasoning_effort"] = explicit_effort
        elif "reasoning_effort" not in model_settings_from_config:
            model_settings_from_config["reasoning_effort"] = "medium"

    # For MindIE models: enforce conservative retry defaults.
    # Timeout normalization is handled inside MindIEChatModel itself.
    if getattr(model_class, "__name__", "") == "MindIEChatModel":
        # Enforce max_retries constraint to prevent cascading timeouts.
        model_settings_from_config["max_retries"] = model_settings_from_config.get("max_retries", 1)

    # Ensure stream_usage is enabled so that token usage metadata is available
    # in streaming responses.  LangChain's BaseChatOpenAI only defaults
    # stream_usage=True when no custom base_url/api_base is set, so models
    # hitting third-party endpoints (e.g. doubao, deepseek) silently lose
    # usage data.  We default it to True unless explicitly configured.
    if "stream_usage" not in model_settings_from_config and "stream_usage" not in kwargs:
        if "stream_usage" in getattr(model_class, "model_fields", {}):
            model_settings_from_config["stream_usage"] = True

    _warn_unknown_model_settings(model_class, name, model_settings_from_config)

    model_instance = model_class(**kwargs, **model_settings_from_config)

    if attach_tracing:
        callbacks = build_tracing_callbacks()
        if callbacks:
            existing_callbacks = model_instance.callbacks or []
            model_instance.callbacks = [*existing_callbacks, *callbacks]
            logger.debug(f"Tracing attached to model '{name}' with providers={len(callbacks)}")
    return model_instance
