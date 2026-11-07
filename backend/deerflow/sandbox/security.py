'''提供本地沙箱宿主命令执行的安全判定。'''

from deerflow.config import get_app_config

_LOCAL_SANDBOX_PROVIDER_MARKERS = (
    "deerflow.sandbox.local:LocalSandboxProvider",
    "deerflow.sandbox.local.local_sandbox_provider:LocalSandboxProvider",
)

LOCAL_HOST_BASH_DISABLED_MESSAGE = "LocalSandboxProvider 已禁用宿主 bash 执行，因为它不构成安全的沙箱边界。仅可在完全可信的本地环境中设置 sandbox.allow_host_bash: true。"

LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE = "LocalSandboxProvider 已禁用 bash 子代理，因为宿主 bash 执行不构成安全的沙箱边界。仅可在完全可信的本地环境中设置 sandbox.allow_host_bash: true。"


def uses_local_sandbox_provider(config=None) -> bool:
    '''判断配置是否选用了本地文件系统沙箱提供者。'''
    if config is None:
        config = get_app_config()

    sandbox_cfg = getattr(config, "sandbox", None)
    sandbox_use = getattr(sandbox_cfg, "use", "")
    if sandbox_use in _LOCAL_SANDBOX_PROVIDER_MARKERS:
        return True
    return sandbox_use.endswith(":LocalSandboxProvider") and "deerflow.sandbox.local" in sandbox_use


def is_host_bash_allowed(config=None) -> bool:
    '''判断当前配置是否明确允许本地沙箱执行宿主命令。'''
    if config is None:
        config = get_app_config()

    sandbox_cfg = getattr(config, "sandbox", None)
    if sandbox_cfg is None:
        return False
    if not uses_local_sandbox_provider(config):
        return True
    return bool(getattr(sandbox_cfg, "allow_host_bash", False))
