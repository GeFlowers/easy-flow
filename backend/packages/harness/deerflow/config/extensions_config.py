"""提供配置、extensions、配置相关功能。"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from deerflow.config.runtime_paths import existing_project_file

logger = logging.getLogger(__name__)


class McpRoutingConfig(BaseModel):
    """\u6267\u884c McpRoutingConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    mode: Literal["off", "prefer"] = Field(
        default="off",
        description="Whether to emit prompt hints preferring this MCP tool for matching requests.",
    )
    priority: int = Field(
        default=0,
        description="Ordering key for routing hints. Higher values are rendered first.",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="Operator-authored keywords that describe when this MCP tool should be preferred.",
    )
    model_config = ConfigDict(extra="forbid")

    @field_validator("priority")
    @classmethod
    def _clamp_priority(cls, value: int) -> int:
        """\u6267\u884c _clamp_priority \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        if value < 0:
            logger.warning("MCP routing priority %s is below 0; clamping to 0.", value)
            return 0
        if value > 100:
            logger.warning("MCP routing priority %s is above 100; clamping to 100.", value)
            return 100
        return value


class McpToolOverride(BaseModel):
    """\u6267\u884c McpToolOverride \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    routing: McpRoutingConfig = Field(default_factory=McpRoutingConfig)
    model_config = ConfigDict(extra="allow")


class McpOAuthConfig(BaseModel):
    """\u6267\u884c McpOAuthConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    enabled: bool = Field(default=True, description="Whether OAuth token injection is enabled")
    token_url: str = Field(description="OAuth token endpoint URL")
    grant_type: Literal["client_credentials", "refresh_token"] = Field(
        default="client_credentials",
        description="OAuth grant type",
    )
    client_id: str | None = Field(default=None, description="OAuth client ID")
    client_secret: str | None = Field(default=None, description="OAuth client secret")
    refresh_token: str | None = Field(default=None, description="OAuth refresh token (for refresh_token grant)")
    scope: str | None = Field(default=None, description="OAuth scope")
    audience: str | None = Field(default=None, description="OAuth audience (provider-specific)")
    token_field: str = Field(default="access_token", description="Field name containing access token in token response")
    token_type_field: str = Field(default="token_type", description="Field name containing token type in token response")
    expires_in_field: str = Field(default="expires_in", description="Field name containing expiry (seconds) in token response")
    default_token_type: str = Field(default="Bearer", description="Default token type when missing in token response")
    refresh_skew_seconds: int = Field(default=60, description="Refresh token this many seconds before expiry")
    extra_token_params: dict[str, str] = Field(default_factory=dict, description="Additional form params sent to token endpoint")
    model_config = ConfigDict(extra="allow")


class McpServerConfig(BaseModel):
    """\u6267\u884c McpServerConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    enabled: bool = Field(default=True, description="Whether this MCP server is enabled")
    type: str = Field(default="stdio", description="Transport type: 'stdio', 'sse', or 'http'")
    command: str | None = Field(default=None, description="Command to execute to start the MCP server (for stdio type)")
    args: list[str] = Field(default_factory=list, description="Arguments to pass to the command (for stdio type)")
    env: dict[str, str] = Field(default_factory=dict, description="Environment variables for the MCP server")
    url: str | None = Field(default=None, description="URL of the MCP server (for sse or http type)")
    headers: dict[str, str] = Field(default_factory=dict, description="HTTP headers to send (for sse or http type)")
    oauth: McpOAuthConfig | None = Field(default=None, description="OAuth configuration (for sse or http type)")
    description: str = Field(default="", description="Human-readable description of what this MCP server provides")
    routing: McpRoutingConfig = Field(default_factory=McpRoutingConfig, description="Soft routing hints for tools from this MCP server")
    tools: dict[str, McpToolOverride] = Field(default_factory=dict, description="Per-original-tool MCP configuration overrides")
    tool_call_timeout: float | None = Field(
        default=None,
        description="Timeout in seconds for individual stdio MCP tool calls. HTTP/SSE servers use transport-level timeouts. None means no timeout.",
    )
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def _accept_transport_alias(cls, data: Any) -> Any:
        """\u6267\u884c _accept_transport_alias \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        if isinstance(data, dict):
            transport = data.get("transport")
            if transport and not data.get("type"):
                data = {**data, "type": transport}
        return data


def resolve_effective_mcp_routing(server_config: McpServerConfig | None, original_tool_name: str) -> dict[str, Any]:
    """\u6267\u884c resolve_effective_mcp_routing \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    if server_config is None:
        return McpRoutingConfig().model_dump(mode="json")

    effective = server_config.routing.model_dump(mode="json")
    override = server_config.tools.get(original_tool_name)
    if override is not None and "routing" in override.model_fields_set:
        effective.update(override.routing.model_dump(mode="json", exclude_unset=True))
    return effective


class SkillStateConfig(BaseModel):
    """\u6267\u884c SkillStateConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    enabled: bool = Field(default=True, description="Whether this skill is enabled")


class ExtensionsConfig(BaseModel):
    """\u6267\u884c ExtensionsConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    mcp_servers: dict[str, McpServerConfig] = Field(
        default_factory=dict,
        description="Map of MCP server name to configuration",
        alias="mcpServers",
    )
    skills: dict[str, SkillStateConfig] = Field(
        default_factory=dict,
        description="Map of skill name to state configuration",
    )
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    @classmethod
    def resolve_config_path(cls, config_path: str | None = None) -> Path | None:
        """\u6267\u884c resolve_config_path \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        if config_path:
            path = Path(config_path)
            if not path.exists():
                raise FileNotFoundError(f"Extensions config file specified by param `config_path` not found at {path}")
            return path
        elif os.getenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH"):
            path = Path(os.getenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH"))
            if not path.exists():
                raise FileNotFoundError(f"Extensions config file specified by environment variable `DEER_FLOW_EXTENSIONS_CONFIG_PATH` not found at {path}")
            return path
        else:
            project_config = existing_project_file(("extensions_config.json", "mcp_config.json"))
            if project_config is not None:
                return project_config

            backend_dir = Path(__file__).resolve().parents[4]
            repo_root = backend_dir.parent
            for path in (
                backend_dir / "extensions_config.json",
                repo_root / "extensions_config.json",
                backend_dir / "mcp_config.json",
                repo_root / "mcp_config.json",
            ):
                if path.exists():
                    return path

                        # 中文说明：此处用于执行相关处理。
            return None

    @classmethod
    def from_file(cls, config_path: str | None = None) -> "ExtensionsConfig":
        """\u6267\u884c from_file \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        resolved_path = cls.resolve_config_path(config_path)
        if resolved_path is None:
                        # 中文说明：此处用于执行相关处理。
            return cls(mcp_servers={}, skills={})

        try:
            with open(resolved_path, encoding="utf-8") as f:
                config_data = json.load(f)
            config_data = cls.resolve_env_variables(config_data)
            return cls.model_validate(config_data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Extensions config file at {resolved_path} is not valid JSON: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Failed to load extensions config from {resolved_path}: {e}") from e

    @classmethod
    def resolve_env_variables(cls, config: Any) -> Any:
        """\u6267\u884c resolve_env_variables \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        if isinstance(config, str):
            if not config.startswith("$"):
                return config
            env_value = os.getenv(config[1:])
            if env_value is None:
                                # 中文说明：此处用于执行相关处理。
                                # 中文说明：此处用于执行相关处理。
                                # 中文说明：此处用于执行相关处理。
                return ""
            return env_value

        if isinstance(config, dict):
            return {key: cls.resolve_env_variables(value) for key, value in config.items()}

        if isinstance(config, list):
            return [cls.resolve_env_variables(item) for item in config]

        if isinstance(config, tuple):
            return tuple(cls.resolve_env_variables(item) for item in config)

        return config

    def get_enabled_mcp_servers(self) -> dict[str, McpServerConfig]:
        """\u6267\u884c get_enabled_mcp_servers \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return {name: config for name, config in self.mcp_servers.items() if config.enabled}

    def is_skill_enabled(self, skill_name: str, skill_category: str) -> bool:
        """\u6267\u884c is_skill_enabled \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        skill_config = self.skills.get(skill_name)
        if skill_config is None:
                        # 中文说明：此处用于执行相关处理。
            return skill_category in ("public", "custom", "legacy")
        return skill_config.enabled


_extensions_config: ExtensionsConfig | None = None


def get_extensions_config() -> ExtensionsConfig:
    """\u6267\u884c get_extensions_config \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    global _extensions_config
    if _extensions_config is None:
        _extensions_config = ExtensionsConfig.from_file()
    return _extensions_config


def reload_extensions_config(config_path: str | None = None) -> ExtensionsConfig:
    """\u6267\u884c reload_extensions_config \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    global _extensions_config
    _extensions_config = ExtensionsConfig.from_file(config_path)
    return _extensions_config


def reset_extensions_config() -> None:
    """\u6267\u884c reset_extensions_config \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    global _extensions_config
    _extensions_config = None


def set_extensions_config(config: ExtensionsConfig) -> None:
    """\u6267\u884c set_extensions_config \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    global _extensions_config
    _extensions_config = config
