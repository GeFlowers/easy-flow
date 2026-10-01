'''定义本地沙箱路径策略、挂载规则及命令执行限制。'''

from pydantic import BaseModel, ConfigDict, Field


class VolumeMountConfig(BaseModel):
    '''描述映射到沙箱命名空间的主机目录及其访问模式。'''

    host_path: str = Field(
        ...,
        description=(
            "Source path visible to the Gateway process. With LocalSandboxProvider, "
            "this is a path on the host when running locally, or a path inside the "
            "Gateway container when using Docker Compose. Remote providers may "
            "upload the configured files instead of mounting them."
        ),
    )
    container_path: str = Field(..., description="Virtual path exposed to the agent")
    read_only: bool = Field(default=False, description="Whether the mount is read-only")


class SandboxConfig(BaseModel):
    '''为本地沙箱工具提供工作区、命令超时和文件访问配置。'''

    use: str = Field(
        ...,
        description="Class path of the sandbox provider (e.g. deerflow.sandbox.local:LocalSandboxProvider)",
    )
    allow_host_bash: bool = Field(
        default=False,
        description="Allow the bash tool to execute directly on the host when using LocalSandboxProvider. Dangerous; intended only for fully trusted local environments.",
    )
    image: str | None = Field(
        default=None,
        description="OCI image used by VM-backed sandbox providers such as BoxLite",
    )
    replicas: int | None = Field(
        default=None,
        description="Maximum active + warm sandboxes/VMs per gateway process (default: 3). Warm/least-recently-used entries are evicted to make room; active sandboxes are not forcibly stopped.",
    )
    idle_timeout: int | None = Field(
        default=None,
        description="Idle timeout in seconds before released warm sandboxes/VMs are stopped (default: 600 = 10 minutes). Set to 0 to disable.",
    )
    health_check_skip_seconds: float | None = Field(
        default=None,
        ge=0,
        description="BoxLite-only reclaim skip window in seconds for boxes recently released by this provider instance. Set to 0 to always validate before warm reuse.",
    )
    mounts: list[VolumeMountConfig] = Field(
        default_factory=list,
        description="List of host directories to map or upload into the sandbox",
    )
    environment: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables to pass to the sandbox runtime. Values starting with $ will be resolved from the Gateway environment.",
    )

    bash_output_max_chars: int = Field(
        default=20000,
        ge=0,
        description="Maximum characters to keep from bash tool output. Output exceeding this limit is middle-truncated (head + tail), preserving the first and last half. Set to 0 to disable truncation.",
    )
    read_file_output_max_chars: int = Field(
        default=50000,
        ge=0,
        description="Maximum characters to keep from read_file tool output. Output exceeding this limit is head-truncated. Set to 0 to disable truncation.",
    )
    ls_output_max_chars: int = Field(
        default=20000,
        ge=0,
        description="Maximum characters to keep from ls tool output. Output exceeding this limit is head-truncated. Set to 0 to disable truncation.",
    )
    bash_command_timeout: int = Field(
        default=600,
        gt=0,
        description=(
            "Maximum wall-clock seconds a host bash command may run before it is terminated, process group and all (LocalSandboxProvider). "
            "Keeps a blocking foreground command (e.g. an un-backgrounded server) from hanging the turn; background `&` processes return immediately."
        ),
    )

    model_config = ConfigDict(extra="allow")
